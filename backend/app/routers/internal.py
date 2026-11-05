"""Internal ingestion endpoints (node agents). Auth via shared secret header.

Duas famílias aqui, e as duas são de processos que rodam FORA deste servidor e
falam com ele pelo segredo compartilhado (`NODE_SECRET`):

  - `/nodes` — o agente de métricas de cada máquina (cpu/mem/disco).
  - `/transcricao` — o transcritor: ele pergunta em que salas entrar, e devolve
    cada fala com a identidade de quem falou.

Por que o transcritor pede as salas e o token aqui, em vez de ter as chaves do
LiveKit: ele roda numa máquina própria (ASR quer GPU; a Lightsail do app não
tem) e uma cópia a mais da chave do LiveKit é uma cópia a mais para vazar. Com
isto ele guarda um segredo só, e as chaves do SFU continuam em um lugar.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from ..config import settings
from ..db import pool, tem_tabela
from ..realtime.hub import hub
from ..services import presenca
from ..services.livekit_service import (
    create_token_do_transcritor,
    livekit_participant_counts,
)
from .. import nodes

logger = logging.getLogger("bwl.transcricao")

router = APIRouter(prefix="/api/internal", tags=["internal"])


def _autorizar(segredo: str | None) -> None:
    """Único guarda deste router.

    `not settings.node_secret` recusa: servidor sem segredo configurado não
    autentica ninguém. O contrário -- aceitar qualquer coisa quando o segredo
    está vazio -- transformaria um env esquecido numa rota aberta de escrita no
    banco da aula.
    """
    if not settings.node_secret or segredo != settings.node_secret:
        raise HTTPException(401, "bad node secret")


class NodeMetrics(BaseModel):
    name: str
    role: str = ""
    cpu: float = 0
    mem: float = 0
    disk: float = 0


@router.post("/nodes")
async def post_node_metrics(body: NodeMetrics, x_node_secret: str | None = Header(default=None)):
    _autorizar(x_node_secret)
    nodes.put(body.name, body.model_dump())
    return {"ok": True}


# ── Transcrição: o agente pergunta onde entrar, e devolve o que ouviu ────────


@router.get("/transcricao/salas")
async def salas_para_transcrever(x_node_secret: str | None = Header(default=None)):
    """Em que salas o transcritor deve estar AGORA, com o token de cada uma.

    O agente PERGUNTA, em vez de o servidor avisar. A alternativa seria o
    webhook `room_started` do LiveKit, que já chega neste backend — mas webhook
    é evento, e evento perdido não volta: o agente reiniciado no meio de um
    encontro ficaria fora dele até o próximo. Perguntando a cada rodada, o pior
    caso é entrar alguns segundos depois.

    Dois filtros, e os dois importam:

    - **aula OpenPBL em andamento** (`stage <> 'done'`): transcrever uma sala de
      reunião qualquer gastaria GPU sem ninguém pedir, e a transcrição do MVP é
      do encontro.
    - **gente conectada no SFU**: entrar numa sala vazia mantém uma conexão e um
      modelo carregado à espera de ninguém. A contagem vem do LiveKit numa só
      chamada (`list_rooms`), não uma por sala.

    Devolve `[]` quando o LiveKit não responde: o agente não entra em lugar
    nenhum e tenta na rodada seguinte. É o mesmo viés do resto da sala -- na
    dúvida, não agir.
    """
    _autorizar(x_node_secret)
    linhas = await pool().fetch(
        "SELECT c.room_id AS uuid, c.stage, r.room_id AS sala "
        "FROM video_room_openpbl_class c JOIN video_rooms r ON r.id = c.room_id "
        "WHERE c.stage <> 'done'")
    if not linhas:
        return {"salas": []}
    contagem = await livekit_participant_counts()
    salas = []
    for l in linhas:
        sala = l["sala"]
        if contagem.get(sala, 0) <= 0:
            continue
        identidade = presenca.identidade_do_transcritor(str(l["uuid"]))
        salas.append({
            "room_id": str(l["uuid"]),
            "sala": sala,
            "stage": l["stage"],
            "identity": identidade,
            "url": settings.livekit_url,
            "token": create_token_do_transcritor(room_name=sala, identity=identidade),
        })
    return {"salas": salas}


class FalaTranscrita(BaseModel):
    room_id: str
    #: Identidade do participante no LiveKit — QUEM falou, por construção: no
    #: LiveKit a faixa de áudio pertence a um participante. Não é diarização.
    identity: str
    nome: str = ""
    #: Começo e fim da fala, em ISO. Vêm do agente porque é ele que tem o
    #: relógio do áudio; o instante da chegada aqui inclui a fila do ASR e
    #: ordenaria a transcrição pelo tempo de processamento, não pelo da fala.
    inicio: datetime
    fim: datetime
    texto: str
    motor: str = ""


@router.post("/transcricao")
async def post_transcricao(body: FalaTranscrita, x_node_secret: str | None = Header(default=None)):
    """Grava uma fala e avisa a sala.

    IDEMPOTENTE: `ON CONFLICT DO NOTHING` sobre (sala, identidade, início). O
    agente reenvia quando a resposta não chega, e uma resposta que não chega é
    indistinguível de uma gravação que não aconteceu — sem isto, rede ruim faria
    a transcrição gaguejar na tela.

    A ETAPA é estampada AQUI, não enviada pelo agente: quem sabe em que etapa a
    sala está é este servidor, e pedir ao agente que acompanhe a cadência
    criaria uma segunda cópia do estado da aula para divergir da primeira.

    Recusa texto vazio com 200, não com erro: silêncio que o reconhecedor
    devolveu em branco não é falha de ninguém, e um 4xx aqui faria o agente
    reenviar para sempre.
    """
    _autorizar(x_node_secret)
    texto = (body.texto or "").strip()
    if not texto:
        return {"ok": True, "gravado": False, "porque": "texto vazio"}
    if not await tem_tabela("video_room_transcricao"):
        # Publicar não aplica migration (ver `db.tem_tabela`). Sem a tabela a
        # transcrição fica inerte, e o agente não fica em loop de erro.
        return {"ok": True, "gravado": False, "porque": "sem a tabela (migration 022)"}
    if not presenca.e_pessoa(body.identity):
        # O gravador republica o áudio de todos: transcrevê-lo duplicaria a aula
        # inteira, com o nome errado. O agente já filtra; esta é a segunda
        # tranca, do lado de quem grava.
        return {"ok": True, "gravado": False, "porque": "não é fala de pessoa"}

    # `timestamptz` quer datetime COM fuso. Sem isto, um agente que mandasse
    # horário ingênuo gravaria a fala no fuso do servidor do banco -- a
    # transcrição ficaria deslocada em três horas, em ordem certa e com o
    # horário errado, que é o jeito mais difícil de perceber.
    inicio = body.inicio if body.inicio.tzinfo else body.inicio.replace(tzinfo=timezone.utc)
    fim = body.fim if body.fim.tzinfo else body.fim.replace(tzinfo=timezone.utc)

    stage = await pool().fetchval(
        "SELECT stage FROM video_room_openpbl_class WHERE room_id=$1", body.room_id)
    try:
        gravou = await pool().fetchval(
            "INSERT INTO video_room_transcricao "
            "(room_id, identity, nome, inicio, fim, texto, stage, motor) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
            "ON CONFLICT (room_id, identity, inicio) DO NOTHING RETURNING id",
            body.room_id, body.identity, body.nome or "", inicio, fim,
            texto, stage or "", body.motor or "")
    except Exception:
        logger.exception("[transcricao] falha ao gravar fala de %s na sala %s",
                         body.identity, body.room_id)
        raise HTTPException(503, "falha ao gravar")
    if not gravou:
        return {"ok": True, "gravado": False, "porque": "já gravada"}

    await hub.broadcast(body.room_id, "transcricao", {
        "identity": body.identity,
        "nome": body.nome or "",
        "inicio": inicio.isoformat(),
        "fim": fim.isoformat(),
        "texto": texto,
        "stage": stage or "",
        "motor": body.motor or "",
    })
    return {"ok": True, "gravado": True}

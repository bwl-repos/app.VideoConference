"""Aula OpenPBL ao vivo — a webconf substitui o pacote PRESENTATION do facilitador.

Replica exatamente a sequência que o pacote faz contra a integration.openpbl.ai
(ContentBuilder C#):
  1. POST /api/Presentation {ActivityId, email}            → presentationCode
  2. POST /api/ClassCourse {name,email,courseId:"",code}   → ClassCourseId + 6 grupos
  Liberar Riscos:      POST /api/ClassRoom/release/{email}/{ccid}/performance
  Liberar Percepções:  POST /api/ClassRoom/release/{email}/{ccid}
  Encerrar registro:   POST /api/Presentation/CloseChecking {Code, ActivityCourseId}
Os pacotes dos alunos já fazem polling desses estados (5s) — nada muda para eles.

O chat do facilitador é um proxy do chat.openpbl.ai (painel do professor, HTTP
Basic). O aluno continua mandando pelo chat do pacote; o facilitador responde
daqui de dentro da sala.
"""
import asyncio
import logging
import json
import math
import time
import httpx
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth import get_current_user, optional_user, CurrentUser
from ..config import settings
from ..db import pool, tem_coluna, tem_tabela
from ..realtime.hub import hub
from ..services import cadencia, comunicacoes, encontro, lider as regra_do_lider, presenca, sorteio, voz_porta
from ..services.livekit_service import create_token, list_participant_identities
from ..services.progresso import (
    e_avaliacao_de_pares,
    e_resposta_de_risco,
    respondeu,
    respostas_de_risco,
)

#: `bwl.cadencia` e nao o logger raiz: a cadencia decide sozinha e, quando
#: alguem perguntar 'por que a aula avancou ali', a resposta tem de estar
#: isolavel no log. O formato do app e uma linha por evento (`main.py`).
logger = logging.getLogger("bwl.cadencia")
from .breakouts import _broadcast_state as _broadcast_breakout_state, abrir_grupos, fechar_grupos
from ..services.cliente_http import cliente_http

router = APIRouter(prefix="/api/rooms", tags=["openpbl-class"])


# ── schemas ───────────────────────────────────────────────────────────────
class ClassStart(BaseModel):
    activity_id: str
    facilitator_email: str | None = None   # default: user.id quando for e-mail


class ClassRelease(BaseModel):
    gate: str   # "risks" (dimensões, /performance) | "perceptions"


class ChatReply(BaseModel):
    content: str


class ModoDaCadencia(BaseModel):
    """Liga ou desliga o facilitador automático desta sala."""
    auto: bool


class VotoDaTurma(BaseModel):
    """A resposta de um aluno a "pode seguir?"."""
    sim: bool


class AvaliacaoDesempenho(BaseModel):
    """A nota que o facilitador dá a um aluno na plenária, pela própria sala.

    Ele clica com o botão direito na câmera e escolhe ali, sem trocar de tela:
    sair da videoconferência no meio da plenária para preencher um formulário
    em outra aba é a diferença entre a avaliação acontecer e não acontecer.
    """

    #: A identidade LiveKit do participante — é o que o clique tem em mãos. O
    #: e-mail é resolvido aqui, contra `video_room_participants`: aceitar o
    #: e-mail direto do navegador deixaria o facilitador (ou qualquer um com o
    #: token dele) escrever nota sobre quem não está na sala.
    identity: str
    #: 4 = DESTACADA · 3 = pró-ativa · 2 = reativa · 1 = resistente.
    nota: int
    #: Em qual critério ele se destacou (índice da dimensão). Só com nota 4.
    #: Um 4 vale 4 apenas nesse critério; nos outros vale 3 — é a regra do
    #: `N12` da planilha, aplicada no elearn, na leitura.
    destaque: int | None = None


# ── helpers ───────────────────────────────────────────────────────────────
def _integration_headers() -> dict:
    if not settings.openpbl_integration_apikey:
        raise HTTPException(503, "Integração OpenPBL não configurada (apikey ausente)")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "apikey": settings.openpbl_integration_apikey,
    }


def _chat_auth() -> tuple[str, str]:
    if not settings.openpbl_chat_user:
        raise HTTPException(503, "Chat OpenPBL não configurado (credenciais ausentes)")
    return (settings.openpbl_chat_user, settings.openpbl_chat_pass)


async def _require_host(user: CurrentUser):
    if not user.is_staff:
        raise HTTPException(403)


def _fim_da_etapa(row) -> str | None:
    """Quando a etapa corrente vence, em ISO — ou `None`.

    `None` em três casos, e os três querem dizer "não há contagem a mostrar":
    a sala não tem as colunas da cadência (banco sem a 018), a etapa não tem
    relógio, ou ela ainda não começou.
    """
    if "stage_started_at" not in row or not row["stage_started_at"]:
        return None
    # A duração CONFIGURADA (painel admin → `services/encontro.py`), em cache.
    # `atuais()` não vai ao banco de propósito: esta função monta a resposta de
    # estado, que é lida no polling de todo mundo que está na aula.
    duracao = encontro.atuais()["duracoes"].get(row["stage"])
    if not duracao:
        return None
    fim = row["stage_started_at"] + timedelta(seconds=duracao)
    # O prazo dos riscos encurta a etapa, nunca a estende: o limite continua valendo.
    if row["stage"] == "release_risks" and "riscos_prazo" in row and row["riscos_prazo"]:
        fim = min(fim, row["riscos_prazo"])
    return fim.isoformat()


def _json_da_coluna(row, coluna, padrao):
    valor = row[coluna] if coluna in row else None
    if isinstance(valor, str):
        valor = json.loads(valor or "null")
    return padrao if valor is None else valor


def _lider_do_estado(row) -> dict | None:
    """O líder geral como a tela precisa. Vão quem já votou e o total de cada candidato, para
    a votação aparecer em tempo real. Em quem cada um votou não interessa a ninguém na sala."""
    if "lider_fase" not in row or not row["lider_fase"]:
        return None
    return {
        "fase": row["lider_fase"],
        "ate": row["lider_fase_ate"].isoformat() if row["lider_fase_ate"] else None,
        "identity": row["lider_identity"],
        "voluntarios": _json_da_coluna(row, "lider_voluntarios", []),
        "candidatos": _json_da_coluna(row, "lider_candidatos", []),
        "votantes": list(_json_da_coluna(row, "lider_votos", {}).keys()),
        "contagem": dict(regra_do_lider.ranking(
            _json_da_coluna(row, "lider_votos", {}), _json_da_coluna(row, "lider_candidatos", []))),
    }


def _row_to_state(row) -> dict:
    groups = row["group_codes"]
    if isinstance(groups, str):
        groups = json.loads(groups)
    return {
        "active": True,
        "activity_id": row["activity_id"],
        "presentation_code": row["presentation_code"],
        "class_course_id": row["class_course_id"],
        "group_codes": groups,
        "facilitator_email": row["facilitator_email"],
        "facilitator_name": row["facilitator_name"],
        "checking_open": row["checking_open"],
        "released_dimensions": row["released_dimensions"],
        "released": row["released"],
        "code_hidden": row["code_hidden"],
        "stage": row["stage"] if "stage" in row else "session_start",
        # ── Cadência ────────────────────────────────────────────────────────
        # `auto` desligado = a sala não avança sozinha e o host dirige, como
        # sempre dirigiu. Os campos do voto vão mesmo quando não há voto: a
        # tela distingue "não há pergunta" de "a pergunta fechou" pelo `None`,
        # e omitir a chave faria as duas coisas parecerem a mesma.
        "auto_mode": bool(row["auto_mode"]) if "auto_mode" in row else False,
        "stage_started_at": (row["stage_started_at"].isoformat()
                             if "stage_started_at" in row and row["stage_started_at"] else None),
        # QUANDO A ETAPA VENCE, já calculado. A tela desce a contagem a partir
        # daqui, como já faz com `vote_ends_at`.
        #
        # Pronto do servidor porque a DURAÇÃO mora em `cadencia.py`: mandá-la
        # para a tela calcular criaria uma segunda tabela de durações, que
        # divergiria da primeira no dia em que alguém ajustasse o ritmo do
        # encontro — e a tela passaria a prometer um tempo que não é o que a
        # cadência cumpre.
        #
        # `None` quando a etapa não tem relógio ou ainda não começou, e aí a
        # tela não mostra contagem nenhuma em vez de mostrar zero.
        "stage_ends_at": _fim_da_etapa(row),
        "questao_atual": row["questao_atual"] if "questao_atual" in row else 0,
        "riscos_prazo": (row["riscos_prazo"].isoformat()
                         if "riscos_prazo" in row and row["riscos_prazo"] else None),
        "lider": _lider_do_estado(row),
        "vote_ends_at": (row["vote_ends_at"].isoformat()
                         if "vote_ends_at" in row and row["vote_ends_at"] else None),
        "vote_stage": row["vote_stage"] if "vote_stage" in row else None,
        "votes": ((json.loads(row["votes"]) if isinstance(row["votes"], str) else row["votes"])
                  if "votes" in row and row["votes"] else {}),
    }


def _room_scoped_email(email: str, room_id: str) -> str:
    """Email exclusivo da sala, usado como IDENTIFICADOR da apresentação no OpenPBL
    (nada é enviado a ele). Plus-addressing: `nome+r<8hex>@dominio`. Determinístico
    por sala — a mesma sala sempre gera a mesma chave (código estável durante a
    sessão), salas diferentes geram chaves diferentes (código novo por aula).

    Se o email já tiver um '+', o local é truncado antes dele para não empilhar tags a
    cada chamada. Sem '@' (não deveria ocorrer aqui), devolve o email intacto."""
    short = room_id.replace("-", "")[:8]
    local, sep, domain = email.partition("@")
    if not sep:
        return email
    local = local.split("+", 1)[0]
    return f"{local}+r{short}@{domain}"


def _facilitator_base_email(scoped: str) -> str:
    """Recupera o email SEM o sufixo por-sala (`+r<id>`).

    O email derivado tem um '+' e o endpoint de release do ContentBuilder o coloca na
    URL — onde o '+' quebra o roteamento (404), mesmo URL-encodado. A criação não sofre
    disso (email vai no corpo JSON). O release é chaveado pelo ccid; o email na path é só
    roteamento, então usamos a base sem '+'. Salas antigas (sem '+') passam intactas."""
    local, sep, domain = (scoped or "").partition("@")
    if not sep:
        return scoped
    return f"{local.split('+', 1)[0]}@{domain}"


async def _get_class(room_id: str):
    return await pool().fetchrow(
        "SELECT * FROM video_room_openpbl_class WHERE room_id=$1", room_id)


# ── Cadência: a sala avança de etapa sozinha ─────────────────────────────────
#
# A regra inteira vive em `services/cadencia.py`, pura e provada. Aqui está só
# a tubulação: ler o estado, perguntar à regra o que fazer, e gravar.
#
# ## Por que a avaliação é PREGUIÇOSA, e não um laço de fundo
#
# A cadência é avaliada a cada leitura do estado da aula — e todo mundo na sala
# faz essa leitura por polling. Um laço de fundo precisaria sobreviver a
# reinício de processo, a deploy no meio de um encontro e a duas réplicas
# decidindo a mesma coisa ao mesmo tempo. A avaliação preguiçosa não tem
# nenhum desses problemas: se ninguém está olhando, não há encontro para
# conduzir.

async def _presentes(room_id: str) -> list[str]:
    """Identidades dos ALUNOS conectados AGORA, segundo o LiveKit.

    Quem está na sala é o SFU que sabe. A tabela `video_room_participants` NÃO
    serve para isso: nada no backend fecha `left_at` -- não existe handler de
    `participant_left` --, então `left_at IS NULL` quer dizer "já entrou nesta
    sala alguma vez", para sempre. Medido em produção: 321 linhas, nenhuma
    fechada em toda a história do banco; uma sala de julho tinha 12 "presentes".

    E isso não apareceria como erro. Apareceria como uma sala que nunca avança:
    quem não vota conta como "não", e maioria estrita de uma turma que foi
    embora há três meses é inalcançável. A regra estava certa; a entrada dela
    era mentira.

    O banco entra só para o PAPEL: o LiveKit diz quem está conectado, a tabela
    diz quem é staff. O host sai da conta porque não vota sobre o próprio ritmo
    -- ele tem o botão.

    E nem todo conectado é gente: o gravador, o transcritor e a aba que espelha
    um grupo também aparecem na lista do SFU. Cada um deles seria um "aluno" que
    nunca vota, isto é, um "não" permanente -- gravar a aula deixaria a cadência
    mais difícil de passar. `services/presenca.py` é quem decide isso, com
    prova; aqui só se aplica o filtro.

    Lista vazia (sala vazia, ou LiveKit fora do ar -- `list_participant_identities`
    devolve `[]` quando falha) não avança nada: `maioria` exige `total > 0`. O
    viés é o mesmo de toda a cadência, que é esperar.
    """
    vivos = presenca.so_pessoas(
        await list_participant_identities(await _nome_no_livekit(room_id)))
    if not vivos:
        return []
    linhas = await pool().fetch(
        "SELECT user_id FROM video_room_participants "
        "WHERE room_id=$1 AND is_staff", room_id)
    staff = {l["user_id"] for l in linhas}
    return sorted(i for i in vivos if i not in staff)


async def _nome_no_livekit(room_id: str) -> str:
    """O nome que ESTA sala tem no LiveKit.

    `room_id` significa duas coisas diferentes neste banco, e é uma armadilha
    que já custou caro:

      - `video_rooms.id`          -> uuid. É o que chega aqui pela URL e o que
                                     `video_room_openpbl_class.room_id` guarda.
      - `video_rooms.room_id`     -> TEXTO, tipo `room_C21_FdzQMQY`. É o nome
                                     da sala no LiveKit, e é o que `create_token`
                                     põe no grant.

    Passar o uuid para o LiveKit pergunta por uma sala que não existe. O erro
    não aparece: `list_participant_identities` devolve `[]` quando falha, então
    o sintoma é "0 de 0 alunos responderam" com a sala cheia -- e, pior, a
    cadência nunca avança nas etapas que dependem de voto, porque `maioria`
    exige `total > 0`.

    Sem linha (sala apagada), devolve o próprio `room_id`: o LiveKit responde
    vazio e a cadência espera, que é o viés certo.
    """
    nome = await pool().fetchval("SELECT room_id FROM video_rooms WHERE id=$1", room_id)
    return nome or room_id


def _estado_da_cadencia(row) -> cadencia.Estado:
    votos = row["votes"] if "votes" in row.keys() else None
    if isinstance(votos, str):
        votos = json.loads(votos or "{}")
    return cadencia.Estado(
        stage=row["stage"],
        auto=bool(row["auto_mode"]) if "auto_mode" in row.keys() else False,
        comecou_em=row["stage_started_at"] if "stage_started_at" in row.keys() else None,
        voto_fecha_em=row["vote_ends_at"] if "vote_ends_at" in row.keys() else None,
        voto_da_etapa=row["vote_stage"] if "vote_stage" in row.keys() else None,
        votos=votos or {},
    )


async def _registrar_comunicacao(room_id: str, evento, texto: str = "") -> None:
    """Grava uma comunicação do facilitador no histórico do encontro.

    `evento` é a tupla `(tipo, meta)` de `comunicacoes`, ou `None` — e `None`
    não grava nada: decisão de "seguir como está" não é algo que alguém precise
    ler.

    INERTE sem a tabela, de propósito. Publicar não aplica migration, e isto é
    chamado de dentro da cadência e do botão do host — caminhos que já existiam.
    Um erro aqui levaria a cadência junto para entregar um histórico que ninguém
    ainda pediu. É a mesma regra que a 018 ensinou: funcionalidade nova pode
    nascer inerte, não pode levar a antiga.
    """
    if not evento:
        return
    if not await tem_tabela("video_room_comunicacoes"):
        return
    tipo, meta = evento
    try:
        await pool().execute(
            "INSERT INTO video_room_comunicacoes (room_id, tipo, texto, meta) "
            "VALUES ($1,$2,$3,$4::jsonb)",
            room_id, tipo, texto, json.dumps(meta))
    except Exception:
        # Histórico é registro, não caminho crítico: a aula não para porque o
        # INSERT falhou. O log acima já guardou a mesma decisão.
        logger.exception("[comunicacoes] falha ao registrar %s na sala %s", tipo, room_id)


async def _aplicar_cadencia(room_id: str, row):
    """Avalia a cadência e grava o que ela mandar. Devolve a linha corrente.

    Devolve a linha ATUALIZADA (ou a mesma, quando nada mudou) para quem chamou
    não precisar reler — e para não haver duas versões do estado circulando na
    mesma resposta.
    """
    if not row or "auto_mode" not in row.keys():
        return row            # banco sem a migration 018 ainda
    estado = _estado_da_cadencia(row)
    if not estado.auto:
        return row            # atalho: modo manual não lê presença nem grava

    # ETAPA QUE A CADÊNCIA NÃO CONHECE = SALA PARADA, E EM SILÊNCIO.
    #
    # Sem duração não há `stage_ends_at` (nada de relógio) e `decidir` nunca
    # manda avançar. A sala fica ligada no automático sem andar, e de fora
    # parece "esperando o facilitador".
    #
    # Aconteceu de verdade: a migration 013 nunca foi aplicada em produção, o
    # DEFAULT da coluna seguiu `presentation`, e TODA sala nova nascia numa
    # etapa fora do vocabulário — 43 salas quando foi medido em 04/11/2026.
    # Não normalizo aqui de propósito: rebobinar uma aula viva por causa de um
    # valor inesperado é pior que não andar. O log é o que torna o defeito
    # achável, e o host vê o mesmo aviso na tela.
    config = await encontro.carregar()
    params = encontro.parametros(config)
    if estado.stage not in params.duracoes:
        logger.warning(
            "[cadencia] sala=%s etapa '%s' fora do vocabulario: sem relogio e "
            "sem avanco automatico (schema desatualizado?)", room_id, estado.stage)
        return row

    agora = datetime.now(timezone.utc)

    # ── RESGATE DAS SALAS SEM RELÓGIO ───────────────────────────────────────
    #
    # `stage_started_at` nasceu NULL em todas as salas quando a migration 018
    # entrou, e o único jeito de marcá-lo era o host clicar no ▶. Medido em
    # produção: 97 salas em modo automático, ZERO com relógio — ou seja, a
    # cadência estava ligada e parada em todas.
    #
    # Marcar AGORA, na primeira vez que alguém mexe na sala, é o que a torna
    # automática de verdade. E tem de ser aqui, e não em `decidir`: aquela
    # função é pura e não escreve: sem gravar, o relógio recomeçaria a cada
    # consulta e a etapa nunca venceria.
    if estado.comecou_em is None:
        await pool().execute(
            "UPDATE video_room_openpbl_class SET stage_started_at=$2 WHERE room_id=$1",
            room_id, agora)
        logger.info("[cadencia] sala=%s relogio iniciado em %s", room_id, estado.stage)
        row = await _get_class(room_id)
        estado = _estado_da_cadencia(row)

    # A lista de presentes custa uma chamada ao LiveKit, e isto roda no polling
    # de todo mundo que está na aula. Só a apuração precisa dela -- quem decide
    # se é o caso é a própria regra, para a condição não viver em dois lugares.
    presentes = (await _presentes(room_id)
                 if cadencia.precisa_de_presenca(estado, agora) else [])
    if estado.stage == "release_risks" and "riscos_prazo" in row:
        estado = replace(estado, prazo=row["riscos_prazo"])
    d = cadencia.decidir(estado, agora, presentes, params)
    # Com perguntas ainda por mostrar, o tempo vencido passa para a PRÓXIMA PERGUNTA, não
    # para a próxima etapa: são 7 minutos por questão.
    if d.acao == "avancar" and estado.stage == "question" and "questao_atual" in row \
            and row["questao_atual"] + 1 < await _total_de_questoes(room_id):
        await _mudar_de_questao(room_id, row["questao_atual"] + 1)
        return await _get_class(room_id)

    if d.acao == "abrir_voto":
        await pool().execute(
            "UPDATE video_room_openpbl_class "
            "SET vote_ends_at=$2, vote_stage=$3, votes='{}'::jsonb WHERE room_id=$1",
            room_id, d.voto_fecha_em, estado.stage)
    elif d.acao == "avancar":
        # SÓ UM EXECUTA. Isto roda no polling de toda a turma, então várias leituras chegam
        # aqui ao mesmo tempo com a mesma decisão. Agora os efeitos abrem grupos e liberam
        # questionários: repetidos, derrubariam a mídia de todo mundo. Quem conseguir mudar
        # o relógio é quem executa; os demais leem a linha e seguem.
        zera_prazo = ", riscos_prazo=NULL" if "riscos_prazo" in row else ""
        reservou = await pool().execute(
            f"UPDATE video_room_openpbl_class SET stage_started_at=$2, vote_ends_at=NULL, "
            f"vote_stage=NULL, votes='{{}}'::jsonb{zera_prazo} "
            f"WHERE room_id=$1 AND stage=$3 AND stage_started_at IS NOT DISTINCT FROM $4",
            room_id, agora, estado.stage, row["stage_started_at"])
        if reservou != "UPDATE 1":
            return await _get_class(room_id)

        # O EFEITO ANTES DA ETAPA. Encerrar o registro não é trocar uma string:
        # é chamar o OpenPBL e dividir os grupos. Gravar a etapa primeiro e
        # falhar no efeito deixaria a sala dizendo "registro encerrado" com o
        # registro aberto do outro lado.
        if estado.stage == "registration_close":
            await _efetivar_encerramento_do_registro(room_id, row, estrito=False)

        await pool().execute(
            "UPDATE video_room_openpbl_class "
            "SET stage=$2, stage_started_at=$3, vote_ends_at=NULL, vote_stage=NULL, "
            "    votes='{}'::jsonb WHERE room_id=$1",
            room_id, d.proxima, agora)
        # Depois da etapa gravada: quem volta de um grupo relê o estado ao reconectar, e
        # precisa encontrar a etapa nova.
        await _ao_mudar_de_etapa(room_id, row, estado.stage, d.proxima, automatico=True)
    elif d.acao == "estender":
        # A etapa recomeça a contar a partir de AGORA menos a duração, mais a
        # tolerância: ela ganha só o empurrão, não outro período inteiro.
        dur = params.duracoes.get(estado.stage) or 0
        novo_inicio = agora - timedelta(seconds=dur) + params.tolerancia
        await pool().execute(
            "UPDATE video_room_openpbl_class "
            "SET stage_started_at=$2, vote_ends_at=NULL, vote_stage=NULL, "
            "    votes='{}'::jsonb WHERE room_id=$1",
            room_id, novo_inicio)
    else:
        return row

    logger.info("[cadencia] sala=%s %s (%s) %d/%d",
                room_id, d.acao, d.porque, d.sim, d.total)
    await _registrar_comunicacao(
        room_id, comunicacoes.da_decisao(estado.stage, d.acao, d.proxima, d.sim, d.total))
    nova = await _get_class(room_id)
    if d.acao in ("abrir_voto", "avancar"):
        await hub.broadcast(room_id, "openpbl-class", _row_to_state(nova))
    return nova


# ── endpoints ─────────────────────────────────────────────────────────────
@router.post("/{room_id}/openpbl/start")
async def start_class(room_id: str, body: ClassStart, user: CurrentUser = Depends(get_current_user)):
    """Gera o class-code e cria a turma — igual ao pacote PRESENTATION ao abrir."""
    await _require_host(user)
    room = await pool().fetchrow("SELECT id FROM video_rooms WHERE id=$1", room_id)
    if not room:
        raise HTTPException(404, "room not found")

    real_email = (body.facilitator_email or "").strip() or (user.id if "@" in user.id else "")
    if not real_email:
        raise HTTPException(400, "facilitator_email é obrigatório (identidade sem e-mail)")
    activity_id = body.activity_id.strip()
    if not activity_id:
        raise HTTPException(400, "activity_id é obrigatório")

    # Class-code POR SALA. O /api/Presentation do OpenPBL reusa o código quando a chave
    # (activityId, email) se repete dentro de uma janela de horas — então dar duas aulas
    # do MESMO episódio caía no mesmo código, misturando as turmas. Derivamos um email
    # exclusivo da sala (o OpenPBL usa o email só como identificador, não envia nada):
    # sala nova → chave nova → código novo na hora; reabrir a MESMA sala mantém o código
    # (o id da sala é estável), preservando a sessão em andamento.
    email = _room_scoped_email(real_email, room_id)

    base = settings.openpbl_integration_url.rstrip("/")
    headers = _integration_headers()
    async with cliente_http(timeout=20) as c:
        # 1. presentationCode
        r1 = await c.post(f"{base}/api/Presentation",
                          headers=headers,
                          json={"ActivityId": activity_id, "email": email})
        if r1.status_code != 200:
            # O CORPO ENTRA NO LOG, e não só o status. Um 502 que diz apenas
            # "falhou (400)" não distingue atividade inexistente de payload
            # recusado de chave inválida -- e, do lado da tela, o host via
            # apenas uma sala que não avançava.
            logger.error("[openpbl/start] sala=%s /api/Presentation %s: %s | enviado: "
                         "ActivityId=%s email=%s",
                         room_id, r1.status_code, r1.text[:400], activity_id, email)
            raise HTTPException(
                502, f"OpenPBL /api/Presentation falhou ({r1.status_code}): {r1.text[:200]}")
        code = r1.json() if r1.headers.get("content-type", "").startswith("application/json") else r1.text.strip('"')
        if not code or not isinstance(code, str):
            raise HTTPException(502, "OpenPBL não retornou o código da sessão")

        # 2. ClassCourse (turma + 6 grupos)
        r2 = await c.post(f"{base}/api/ClassCourse",
                          headers=headers,
                          json={"name": user.name or "Facilitador", "email": email,
                                "courseId": "", "presentationCode": code})
        if r2.status_code != 200:
            logger.error("[openpbl/start] sala=%s /api/ClassCourse %s: %s | enviado: "
                         "presentationCode=%s email=%s",
                         room_id, r2.status_code, r2.text[:400], code, email)
            raise HTTPException(
                502, f"OpenPBL /api/ClassCourse falhou ({r2.status_code}): {r2.text[:200]}")
        cc = r2.json() or {}
        ccid = cc.get("id")
        group_codes = [g.get("codigo") for g in (cc.get("classeRooms") or []) if g.get("codigo")]
        if not ccid:
            raise HTTPException(502, "OpenPBL não retornou o ClassCourseId")

    await pool().execute(
        """
        INSERT INTO video_room_openpbl_class
          (room_id, activity_id, presentation_code, class_course_id, group_codes,
           facilitator_email, facilitator_name, checking_open, released_dimensions, released)
        VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,true,false,false)
        ON CONFLICT (room_id) DO UPDATE SET
          activity_id=EXCLUDED.activity_id, presentation_code=EXCLUDED.presentation_code,
          class_course_id=EXCLUDED.class_course_id, group_codes=EXCLUDED.group_codes,
          facilitator_email=EXCLUDED.facilitator_email, facilitator_name=EXCLUDED.facilitator_name,
          checking_open=true, released_dimensions=false, released=false, created_at=now()
        """,
        # Guarda o email DERIVADO: é ele que identifica esta apresentação no OpenPBL, e
        # as liberações (release_gate) precisam usar o mesmo. O nome segue o real.
        room_id, activity_id, code, str(ccid), json.dumps(group_codes),
        email, user.name or "")

    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


@router.get("/{room_id}/openpbl")
async def get_class(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    # optional_user (não host): é estado só de leitura — mesma política de roster/roles/
    # risk-chart. Necessário para o gravador (egress) espelhar a etapa atual sem host.
    row = await _get_class(room_id)
    if not row:
        return {"active": False}
    # A CADÊNCIA É AVALIADA AQUI, na leitura, e não num laço de fundo: um laço
    # precisaria sobreviver a reinício de processo, a deploy no meio de um
    # encontro e a duas réplicas decidindo a mesma coisa. Sem ninguém olhando,
    # não há encontro a conduzir.
    #
    # ATENÇÃO, E ISTO JÁ QUEBROU: a escolha só funciona enquanto ALGUÉM CHAMA
    # ESTE ENDPOINT DE TEMPOS EM TEMPOS. Até 04/11/2026 o comentário aqui dizia
    # que "todo mundo na sala faz polling deste endpoint" — e não fazia: o
    # frontend chamava `classState` uma vez na entrada e depois só em
    # reconexão de WebSocket. A sala avançava quando alguém entrava, e parava.
    # Quem garante a chamada periódica é o `setInterval(load, 10000)` do
    # `useEffect` de `pblClass` em `VideoRoom.tsx`; a prova confere que ele
    # continua lá, porque sem ele esta linha nunca roda.
    row = await _aplicar_cadencia(room_id, row) or row
    row = await _aplicar_lider(room_id, row)
    return _row_to_state(row)


@router.post("/{room_id}/openpbl/release")
async def release_gate(room_id: str, body: ClassRelease, user: CurrentUser = Depends(get_current_user)):
    """Libera um questionário para a turma (Riscos → /performance; Percepções → base)."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    if body.gate not in ("risks", "perceptions"):
        raise HTTPException(400, "gate deve ser 'risks' ou 'perceptions'")
    return await _liberar_questionario(room_id, row, body.gate)


async def _liberar_questionario(room_id: str, row, gate: str) -> dict:
    """Fora do endpoint porque a cadência também libera: no automático não há clique."""
    base = settings.openpbl_integration_url.rstrip("/")
    # Email SEM o sufixo por-sala: o '+' do email derivado quebra a URL do release (404).
    # O que identifica a turma é o ccid; o email na path é só roteamento.
    email, ccid = _facilitator_base_email(row["facilitator_email"]), row["class_course_id"]
    suffix = "/performance" if gate == "risks" else ""
    async with cliente_http(timeout=20) as c:
        r = await c.post(f"{base}/api/ClassRoom/release/{email}/{ccid}{suffix}",
                         headers={"Accept": "*/*", "apikey": settings.openpbl_integration_apikey})
        if r.status_code != 200:
            raise HTTPException(502, f"OpenPBL release falhou ({r.status_code})")

        # Push em tempo real (SSE) para os alunos conectados ao pacote: destrava na
        # hora, sem depender do polling. Mesmo canal do facilitador (classCourseId).
        # gate: "risks"->"riscos", "perceptions"->"percepcoes" (nomes que o pagetreat
        # espera). Best-effort — se o Scorm/Redis falhar, o fallback do pacote cobre.
        try:
            rt_gate = "riscos" if gate == "risks" else "percepcoes"
            await c.post(
                f"{settings.scorm_lrs_url.rstrip('/')}/realtime/class/{ccid}/release",
                json={"gate": rt_gate, "released": True},
                headers={"X-Release-Token": settings.scorm_realtime_release_token},
            )
        except Exception:
            pass

    field = "released_dimensions" if gate == "risks" else "released"
    await pool().execute(
        f"UPDATE video_room_openpbl_class SET {field}=true WHERE room_id=$1", room_id)
    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


#: Os critérios mudam com o template do Encontro, não durante uma plenária.
#: Buscá-los a cada abertura do menu de contexto seria uma chamada ao elearn
#: por clique direito do facilitador.
_criterios_cache: tuple[float, list] | None = None
_CRITERIOS_TTL = 300.0


@router.get("/{room_id}/openpbl/criterios")
async def listar_criterios(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Os nomes dos critérios de desempenho, para o menu de avaliação.

    Proxy do elearn, e não chamada direta do navegador: o token do elearn não
    pode chegar ao browser — mesmo motivo de `/api/salas/*` existir no
    CustomerApp.

    A ORDEM é o contrato: o índice de um critério aqui é o `destaque` que volta
    em `/avaliar`. Reordenar a lista no caminho trocaria os eixos sem erro
    nenhum.
    """
    await _require_host(user)
    global _criterios_cache
    agora = time.monotonic()
    if _criterios_cache and agora - _criterios_cache[0] < _CRITERIOS_TTL:
        return {"criterios": _criterios_cache[1]}
    if not settings.openpbl_rise_token:
        return {"criterios": []}
    try:
        async with cliente_http(timeout=15) as c:
            r = await c.get(
                f"{settings.openpbl_rise_url.rstrip('/')}/desempenho/criterios",
                headers={"Authorization": f"Bearer {settings.openpbl_rise_token}"})
        lista = (r.json() or {}).get("criterios") or [] if r.status_code == 200 else []
    except Exception:
        # Sem nomes o menu ainda avalia — só não oferece destaque por critério.
        # Derrubar o menu inteiro por causa do rótulo seria perder a nota.
        lista = []
    _criterios_cache = (agora, lista)
    return {"criterios": lista}


@router.post("/{room_id}/openpbl/avaliar")
async def avaliar_desempenho(room_id: str, body: AvaliacaoDesempenho,
                             user: CurrentUser = Depends(get_current_user)):
    """A nota de participação do aluno na plenária, dada durante a sessão.

    ## Para onde ela vai, e por que não é a integração de sempre

    Vai para o ELEARN (Rise), e não para `openpbl_integration_url`. Aquela é a
    API legada (ContentBuilder, PerformanceEvaluation); o pacote de desempenho
    novo e a conta da planilha vivem no Rise. Mandar para o lugar errado não
    daria erro — a nota simplesmente não apareceria para o aluno, que é o pior
    tipo de falha que esta rota pode ter.

    ## O que esta rota NÃO faz

    Não calcula nada. A regra do destaque (um 4 vale 4 só no critério
    apontado), os pesos e a normalização 0–10 ficam todos no Rise, derivados na
    LEITURA. Aqui só se registra o que o facilitador disse.

    Também não deriva o `dimensionsId`: manda o `activity_id` e deixa o Rise
    resolver. Uma segunda cópia daquela regra concordaria hoje e divergiria na
    primeira correção — e o sintoma seria a nota sumir, sem erro nenhum.

    ## Só o host, e só sobre quem está na sala

    `_require_host` porque é nota sobre terceiro. E o e-mail do avaliado é
    resolvido contra `video_room_participants`, não aceito do navegador: do
    contrário bastaria o token do facilitador para escrever nota sobre
    qualquer e-mail do mundo.
    """
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    if body.nota not in (1, 2, 3, 4):
        raise HTTPException(400, "nota deve ser 1, 2, 3 ou 4")
    if not settings.openpbl_rise_token:
        raise HTTPException(503, "Integração com o elearn não configurada (token ausente)")

    alvo = await pool().fetchrow(
        "SELECT email, display_name FROM video_room_participants "
        "WHERE room_id=$1 AND user_id=$2", room_id, body.identity)
    email = ((alvo["email"] if alvo else "") or "").strip().lower()
    if not email:
        # 404 e não 400: o pedido estava bem formado; quem não existe é o alvo.
        # Acontece de verdade quando o aluno entrou como convidado sem e-mail —
        # e aí a nota não teria onde cair.
        raise HTTPException(404, "participante sem e-mail nesta sala")

    corpo = {
        "activity_id": str(row["activity_id"]),
        "avaliado": email,
        "avaliado_nome": (alvo["display_name"] or "") if alvo else "",
        "avaliador": _facilitator_base_email(row["facilitator_email"] or ""),
        "avaliador_nome": row["facilitator_name"] or "",
        "nota": body.nota,
        # Destaque só faz sentido com 4. Mandar o índice junto de uma nota 2
        # encheria o banco de destaques que a regra ignora, e um dia alguém
        # leria aquilo como se valesse.
        "destaque": body.destaque if body.nota == 4 else None,
        "class_code": str(row["class_course_id"] or ""),
    }
    base = settings.openpbl_rise_url.rstrip("/")
    try:
        async with cliente_http(timeout=20) as c:
            r = await c.post(f"{base}/desempenho/facilitador", json=corpo,
                             headers={"Authorization":
                                      f"Bearer {settings.openpbl_rise_token}"})
    except Exception as erro:  # noqa: BLE001
        raise HTTPException(502, f"não foi possível falar com o elearn: {erro}")
    if r.status_code >= 400:
        raise HTTPException(502, f"elearn recusou a nota ({r.status_code})")

    dados = r.json() if r.content else {}
    if not dados.get("ok"):
        # O elearn devolve 200 com `ok: false` quando o episódio não está
        # publicado — ver a rota lá. Aqui vira erro VISÍVEL: o facilitador
        # precisa saber que clicou e nada foi gravado, senão ele avalia a turma
        # inteira achando que registrou.
        raise HTTPException(409, dados.get("erro") or "o elearn não gravou a nota")

    return {"ok": True, "avaliado": email, "nota": body.nota,
            "destaque": corpo["destaque"],
            "dimensions_id": dados.get("dimensions_id", "")}


async def _efetivar_encerramento_do_registro(room_id: str, row, *, estrito: bool) -> None:
    """O que encerrar o registro FAZ, além de mudar a etapa.

    Extraído do endpoint porque a cadência passou a atravessar esta etapa
    sozinha. Avançar a etapa é trocar uma string; encerrar o registro é chamar
    o OpenPBL (`CloseChecking`) **e** dividir os grupos. Se a cadência só
    trocasse a string, a sala entraria no aquecimento com o registro ABERTO do
    outro lado e sem grupo nenhum formado — e nada acusaria, porque a tela
    mostraria a etapa certa.

    `estrito=True` é o botão do host: a falha vira 502 e ele vê. `estrito=False`
    é a cadência: ela loga e segue, porque a automação não pode travar a aula
    porque a integração não respondeu — o host ainda tem o botão para refazer.
    """
    base = settings.openpbl_integration_url.rstrip("/")
    try:
        async with cliente_http(timeout=20) as c:
            r = await c.post(f"{base}/api/Presentation/CloseChecking",
                             headers=_integration_headers(),
                             json={"Code": row["presentation_code"],
                                   "ActivityCourseId": row["activity_id"]})
        if r.status_code != 200:
            raise RuntimeError(f"CloseChecking devolveu {r.status_code}")
    except Exception as exc:
        if estrito:
            raise HTTPException(502, f"OpenPBL CloseChecking falhou ({exc})")
        logger.error("[cadencia] sala=%s CloseChecking falhou: %s", room_id, exc)

    await pool().execute(
        "UPDATE video_room_openpbl_class SET checking_open=false WHERE room_id=$1", room_id)

    # Quem não conectou o pacote vai para o suporte ANTES de dividir: a divisão não pode
    # contar com quem talvez não volte. Best-effort pelo mesmo motivo do que vem abaixo.
    try:
        await _abrir_suporte(room_id)
        await _iniciar_escolha_do_lider(room_id)
    except Exception:
        logger.exception("[turma] sala=%s suporte/lider falhou ao encerrar o registro", room_id)

    # Divide os alunos PRESENTES em grupos (ninguém sozinho, máx 6 grupos, máx 5
    # por grupo). Best-effort nos dois modos: o registro já foi encerrado, e
    # desfazer isso por causa da divisão seria pior.
    try:
        await _auto_group_breakouts(room_id)
    except Exception:
        logger.exception("[cadencia] sala=%s divisao de grupos falhou", room_id)


@router.post("/{room_id}/openpbl/close-registration")
async def close_registration(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Encerra o registro/presença — novos alunos não conseguem mais entrar."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")

    await _efetivar_encerramento_do_registro(room_id, row, estrito=True)

    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


@router.get("/{room_id}/openpbl/groups")
async def list_groups(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Grupos da turma com os alunos que entraram (listarGrupos, ao vivo)."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    base = settings.openpbl_integration_url.rstrip("/")
    async with cliente_http(timeout=20) as c:
        r = await c.get(f"{base}/api/ClassRoomStudent/listarGrupos/{row['class_course_id']}",
                        headers=_integration_headers())
        if r.status_code != 200:
            raise HTTPException(502, f"OpenPBL listarGrupos falhou ({r.status_code})")
        return r.json()


async def _sync_openpbl_groups(room_id: str, cls) -> int:
    """Reflete os grupos montados pela API OpenPBL (ao encerrar o registro) nos
    breakout rooms da webconf. Cada grupo do `listarGrupos` vira um breakout, e
    cada aluno é atribuído mapeando o e-mail → identity do participante da sala.
    Recria a configuração de grupos do zero. Retorna o nº de grupos criados."""
    ccid = cls["class_course_id"]
    if not ccid:
        return 0
    base = settings.openpbl_integration_url.rstrip("/")
    try:
        async with cliente_http(timeout=20) as c:
            r = await c.get(f"{base}/api/ClassRoomStudent/listarGrupos/{ccid}",
                            headers=_integration_headers())
        if r.status_code != 200:
            return 0
        payload = r.json() or {}
    except Exception:
        return 0

    # `data` costuma vir como string JSON (o pacote facilitador faz eval()).
    raw = payload.get("data") if isinstance(payload, dict) else payload
    try:
        groups = raw if isinstance(raw, list) else (json.loads(raw) if raw else [])
    except Exception:
        return 0
    groups = [g for g in groups if isinstance(g, dict) and (g.get("Alunos") or [])]
    if not groups:
        return 0

    # Mapa e-mail → (identity, nome) dos participantes atuais da sala.
    parts = await pool().fetch(
        "SELECT user_id, display_name, email FROM video_room_participants "
        "WHERE room_id=$1 AND left_at IS NULL", room_id)
    by_email = {(p["email"] or "").strip().lower(): (p["user_id"], p["display_name"] or "")
                for p in parts if p["email"]}

    room = await pool().fetchrow("SELECT * FROM video_rooms WHERE id=$1", room_id)
    if not room:
        return 0
    # Recria do zero (mesma semântica do create_breakouts). Fecha se estava aberto.
    if room["breakout_open"]:
        await hub.broadcast(room_id, "breakout-close", {"room_id": room_id})
    anteriores = await _lideres_atuais(room_id)
    await pool().execute("DELETE FROM video_breakout_groups WHERE parent_room_id=$1", room_id)
    await pool().execute(
        "UPDATE video_rooms SET breakout_open=false, breakout_ends_at=NULL, breakout_mode='manual' WHERE id=$1",
        room_id)

    for i, g in enumerate(groups):
        rn = f"{room['room_id']}__bo{i + 1}"
        gid = await pool().fetchval(
            "INSERT INTO video_breakout_groups (parent_room_id, name, room_name, position) "
            "VALUES ($1,$2,$3,$4) RETURNING id", room_id, f"Grupo {i + 1}", rn, i)
        for aluno in (g.get("Alunos") or []):
            email = (aluno.get("Email") or "").strip().lower()
            hit = by_email.get(email)
            if not hit:
                continue   # aluno do grupo não está (ainda) na sala de vídeo
            await pool().execute(
                "INSERT INTO video_breakout_assignments (parent_room_id, group_id, identity, display_name) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT (parent_room_id, identity) DO UPDATE "
                "SET group_id=EXCLUDED.group_id, display_name=EXCLUDED.display_name",
                room_id, str(gid), hit[0], (aluno.get("Name") or hit[1]))

    await _sortear_lideres(room_id, anteriores)
    await _broadcast_breakout_state(room_id)
    return len(groups)


async def _lideres_atuais(room_id: str) -> dict[str, str | None]:
    """{nome do grupo: identidade de quem lidera}, para preservar no resorteio.

    Vazio quando a coluna ainda não existe — e aí `sortear` recebe `anterior`
    nulo e sorteia, que é o comportamento certo para a primeira vez.
    """
    if not await tem_coluna("video_breakout_groups", "leader_identity"):
        return {}
    linhas = await pool().fetch(
        "SELECT name, leader_identity FROM video_breakout_groups WHERE parent_room_id=$1",
        room_id)
    return {l["name"]: l["leader_identity"] for l in linhas}


async def _sortear_lideres(room_id: str, anteriores: dict[str, str | None] | None = None) -> None:
    """Sorteia o líder de cada grupo e GRAVA.

    INERTE sem a coluna, de propósito. Publicar não aplica migration, e esta
    função é chamada de dentro da divisão de grupos — que é caminho antigo. Um
    `UndefinedColumnError` aqui levaria embora a divisão inteira, que funciona
    desde sempre, para entregar um líder que ninguém ainda pediu. Funcionalidade
    nova pode nascer inerte; não pode levar a antiga junto.
    """
    if not await tem_coluna("video_breakout_groups", "leader_identity"):
        logger.info("[sorteio] coluna leader_identity ausente; sorteio inerte "
                    "(aplicar migrations/019_group_leader.sql)")
        return

    linhas = await pool().fetch(
        "SELECT g.id, g.name, g.position, a.identity "
        "FROM video_breakout_groups g "
        "LEFT JOIN video_breakout_assignments a ON a.group_id = g.id "
        "WHERE g.parent_room_id=$1 ORDER BY g.position", room_id)

    membros: dict[str, list[str]] = {}
    ids: dict[str, str] = {}
    for r in linhas:
        nome = r["name"]
        ids[nome] = str(r["id"])
        membros.setdefault(nome, [])
        if r["identity"]:
            membros[nome].append(r["identity"])

    for nome, lider in sorteio.sortear_por_grupo(membros, anteriores).items():
        await pool().execute(
            "UPDATE video_breakout_groups SET leader_identity=$1 WHERE id=$2",
            lider, ids[nome])


async def _auto_group_breakouts(room_id: str) -> int:
    """Divide os alunos PRESENTES em grupos de vídeo: ninguém sozinho, no máximo
    6 grupos e no máximo 5 por grupo. Distribuição round-robin (equilibrada).
    Determinístico (ordem de entrada) — recria a configuração. Retorna nº de grupos."""
    # QUEM ESTÁ NA SALA É O LIVEKIT QUE SABE. A tabela não serve para isso:
    # nada fecha `left_at`, então `left_at IS NULL` quer dizer "já entrou nesta
    # sala alguma vez", para sempre (ver `_presentes`). Sem este cruzamento uma
    # sala reusada dividiria em grupos gente que foi embora no mês passado — e o
    # líder sorteado poderia ser alguém que não está aqui, que é a forma mais
    # visível de o defeito aparecer.
    #
    # A tabela continua entrando, mas só pelo que ela sabe de verdade: o nome
    # para exibir e o papel (staff, dono da sala).
    conectados = set(await _presentes(room_id))
    fora_da_divisao = await _fora_da_turma(room_id)
    parts = [
        p for p in await pool().fetch(
            "SELECT p.user_id, p.display_name FROM video_room_participants p "
            "JOIN video_rooms r ON r.id = p.room_id "
            "WHERE p.room_id=$1 AND p.is_staff=false AND p.user_id <> r.owner_id "
            "ORDER BY p.joined_at", room_id)
        if p["user_id"] in conectados and p["user_id"] not in fora_da_divisao
    ]
    n = len(parts)
    if n < 1:
        return 0
    if n == 1:
        g = 1
    else:
        # ~raiz(n) grupos: equilibra o nº de grupos com o tamanho de cada um
        # (4→2×2, 5→3+2, 6→2×3, 12→3×4, …). Para n≥4 isso já garante ninguém
        # sozinho (menor grupo = floor(n/g) ≥ 2).
        g = max(1, math.isqrt(n))
        while (n + g - 1) // g > 5 and g < 6:   # respeita o máximo de 5 por grupo
            g += 1
        g = min(g, 6)                            # e o máximo de 6 grupos

    room = await pool().fetchrow("SELECT * FROM video_rooms WHERE id=$1", room_id)
    if not room:
        return 0
    if room["breakout_open"]:
        await hub.broadcast(room_id, "breakout-close", {"room_id": room_id})

    # Quem liderava, ANTES de apagar os grupos. Chaveado pelo nome porque os ids
    # morrem aqui: recriar reemitiria líderes novos e trocaria a liderança no
    # meio do aquecimento por causa de um clique dado para outra coisa.
    anteriores = await _lideres_atuais(room_id)

    await pool().execute("DELETE FROM video_breakout_groups WHERE parent_room_id=$1", room_id)
    await pool().execute(
        "UPDATE video_rooms SET breakout_open=false, breakout_ends_at=NULL, breakout_mode='manual' WHERE id=$1",
        room_id)

    gids = []
    for i in range(g):
        rn = f"{room['room_id']}__bo{i + 1}"
        gid = await pool().fetchval(
            "INSERT INTO video_breakout_groups (parent_room_id, name, room_name, position) "
            "VALUES ($1,$2,$3,$4) RETURNING id", room_id, f"Grupo {i + 1}", rn, i)
        gids.append(str(gid))
    for idx, p in enumerate(parts):
        await pool().execute(
            "INSERT INTO video_breakout_assignments (parent_room_id, group_id, identity, display_name) "
            "VALUES ($1,$2,$3,$4) ON CONFLICT (parent_room_id, identity) DO UPDATE "
            "SET group_id=EXCLUDED.group_id, display_name=EXCLUDED.display_name",
            room_id, gids[idx % g], p["user_id"], p["display_name"] or "")

    await _sortear_lideres(room_id, anteriores)
    await _broadcast_breakout_state(room_id)
    return g


@router.post("/{room_id}/openpbl/sync-groups")
async def sync_groups(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """(Re)divide os alunos presentes em grupos (ninguém sozinho, máx 6 grupos,
    máx 5 por grupo). Determinístico — útil se entrou/saiu aluno."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    n = await _auto_group_breakouts(room_id)
    return {"ok": True, "groups": n}


def _parse_listar_grupos(raw) -> list:
    """`listarGrupos` devolve `data` como string em notação JS: `{[ {...}, {...} ]}`
    com aspas simples e \\r\\n (INVÁLIDO como JSON). Normaliza e parseia."""
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return []
    s = raw.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()                # remove o wrapper { } → resta [ ... ]
    s = s.replace("'", '"')
    try:
        data = json.loads(s)
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def _openpbl_student_ids(client: httpx.AsyncClient, base: str, ccid: str) -> dict:
    """email(lower) → (studentId, name), via listarGrupos (traz Id+Email de todos)."""
    out: dict[str, tuple[str, str]] = {}
    try:
        r = await client.get(f"{base}/api/ClassRoomStudent/listarGrupos/{ccid}",
                             headers=_integration_headers())
        if r.status_code != 200:
            return out
        payload = r.json() or {}
    except Exception:
        return out
    for g in _parse_listar_grupos(payload.get("data") if isinstance(payload, dict) else payload):
        for a in (g.get("Alunos") or []):
            email = (a.get("Email") or "").strip().lower()
            sid = a.get("Id")
            if email and sid:
                out[email] = (sid, a.get("Name") or "")
    return out


async def _student_perf(client: httpx.AsyncClient, base: str, sid: str, dims_id: str):
    """Notas individuais do aluno no Questionário de Riscos → {dimensions, grades, baseGrades}."""
    try:
        r = await client.get(f"{base}/api/PerformanceEvaluation/performance/{sid}/{dims_id}")
        if r.status_code != 200:
            return None
        d = (r.json() or {}).get("data")
        return d if isinstance(d, dict) else None
    except Exception:
        return None


_chart_cache: dict[str, tuple[float, dict]] = {}
_CHART_TTL = 4.0


@router.get("/{room_id}/openpbl/risk-chart")
async def risk_chart(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    """Radar do Questionário de Riscos agregado pelos GRUPOS DA WEBCONF (os grupos
    do pacote não batem com os nossos). Busca as respostas individuais
    (`performance/{studentId}/{dims}`) e média por grupo + contagem de quem respondeu.
    Liberado a qualquer participante (o aluno também vê o gráfico na etapa 'Mostrar Gráfico')."""
    cls = await _get_class(room_id)
    if not cls:
        return {"available": False, "reason": "class_not_started"}
    room = await pool().fetchrow("SELECT openpbl_dimensions_id FROM video_rooms WHERE id=$1", room_id)
    dims_id = ((room["openpbl_dimensions_id"] if room else None) or "").strip()
    if not dims_id:
        return {"available": False, "reason": "no_dimensions_id"}

    now = time.monotonic()
    hit = _chart_cache.get(room_id)
    if hit and (now - hit[0]) < _CHART_TTL:
        return hit[1]

    base = settings.openpbl_integration_url.rstrip("/")
    ccid = cls["class_course_id"]

    async with cliente_http(timeout=15) as c:
        email_to_sid = await _openpbl_student_ids(c, base, ccid)
        if not email_to_sid:
            return {"available": False, "reason": "no_students"}

        groups = await pool().fetch(
            "SELECT id, name FROM video_breakout_groups WHERE parent_room_id=$1 ORDER BY position", room_id)
        assigns = await pool().fetch(
            "SELECT group_id, identity FROM video_breakout_assignments WHERE parent_room_id=$1", room_id)
        parts = await pool().fetch(
            "SELECT user_id, email FROM video_room_participants WHERE room_id=$1", room_id)
        id_to_email = {p["user_id"]: (p["email"] or "").strip().lower() for p in parts}

        group_emails: dict[str, list] = {}
        for a in assigns:
            em = id_to_email.get(a["identity"])
            if em and em in email_to_sid:
                group_emails.setdefault(str(a["group_id"]), []).append(em)

        all_emails = {em for ems in group_emails.values() for em in ems} or set(email_to_sid.keys())
        sid_list = [(em, email_to_sid[em][0]) for em in all_emails]
        perfs = await asyncio.gather(*[_student_perf(c, base, sid, dims_id) for (_, sid) in sid_list])
    perf_by_email = {em: p for (em, _), p in zip(sid_list, perfs)}

    dims = base_grades = None
    for p in perfs:
        if p and p.get("dimensions"):
            dims = p["dimensions"]; base_grades = p.get("baseGrades"); break
    if not dims:
        return {"available": False, "reason": "empty"}
    D = len(dims)

    def grade(p, i):
        g = (p or {}).get("grades") or []
        return g[i] if i < len(g) and isinstance(g[i], (int, float)) else 0

    def avg_over(emails):
        s = [0.0] * D; c = [0] * D
        for em in emails:
            p = perf_by_email.get(em)
            for i in range(D):
                v = grade(p, i)
                if v > 0:
                    s[i] += v; c[i] += 1
        return [(s[i] / c[i]) if c[i] else 0 for i in range(D)]

    # quem respondeu cada dimensão (grade > 0), no total da turma
    answered = [0] * D
    # CONCLUÍDO = aluno que respondeu TODAS as dimensões (grade > 0 em todas).
    completed = 0
    for em in all_emails:
        p = perf_by_email.get(em)
        for i in range(D):
            if grade(p, i) > 0:
                answered[i] += 1
        if D and all(grade(p, i) > 0 for i in range(D)):
            completed += 1

    out_groups = [
        {"name": g["name"], "grades": avg_over(group_emails.get(str(g["id"]), [])),
         "size": len(group_emails.get(str(g["id"]), []))}
        for g in groups if group_emails.get(str(g["id"]))
    ]

    result = {"available": True, "chart": {
        "dimensions": dims,
        "baseGrades": base_grades or [],
        "classAverage": avg_over(all_emails),
        "groups": out_groups,
        "answered": answered,
        "total": len(all_emails),
        "completed": completed,          # alunos que responderam TODAS as dimensões
    }}
    _chart_cache[room_id] = (now, result)
    return result


_STAGES = (
    "session_start", "registration_open", "amplify_code", "registration_close",
    "synopsis", "groups", "plenary", "question", "situational",
    "release_risks", "show_chart", "closing", "release_feedback", "done",
)


class StageSet(BaseModel):
    stage: str


@router.post("/{room_id}/openpbl/cadencia")
async def definir_modo(room_id: str, body: ModoDaCadencia,
                       user: CurrentUser = Depends(get_current_user)):
    """Liga/desliga o facilitador automático. Só o host.

    Desligar é o freio de mão: quando a cadência vai mal no meio de uma aula, o
    host assume e os comandos que ele sempre teve voltam a ser os únicos que
    mexem na etapa. Por isso o modo manual tem precedência dentro da própria
    regra (ver `cadencia.decidir`) e não só aqui.

    LIGAR marca a hora de início da etapa corrente. Sem isso a etapa estaria
    correndo desde sempre e a sala abriria um voto no mesmo segundo em que a
    automação fosse ligada -- surpreendendo justamente quem acabou de confiar
    nela.
    """
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    # Banco sem a migration 018: a chave não tem onde gravar. 503 e não 500 --
    # a causa é conhecida e o recado diz o que fazer, em vez de deixar o host
    # clicando num interruptor que falha sem explicar por quê.
    if "auto_mode" not in row.keys():
        raise HTTPException(
            503, "cadência indisponível: migration 018 não aplicada neste banco")
    await pool().execute(
        "UPDATE video_room_openpbl_class "
        "SET auto_mode=$2, stage_started_at=$3, vote_ends_at=NULL, vote_stage=NULL, "
        "    votes='{}'::jsonb WHERE room_id=$1",
        room_id, bool(body.auto),
        datetime.now(timezone.utc) if body.auto else None)
    row = await _get_class(room_id)
    estado = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", estado)
    logger.info("[cadencia] sala=%s modo=%s", room_id, "auto" if body.auto else "manual")
    return estado


@router.post("/{room_id}/openpbl/voto")
async def votar(room_id: str, body: VotoDaTurma,
                user: CurrentUser = Depends(get_current_user)):
    """O voto de um aluno em "pode seguir?".

    Não exige host: quem vota é a turma. O voto é gravado pela IDENTIDADE de
    quem chama, nunca por um campo do corpo -- do contrário um aluno votaria
    pelos colegas e decidiria o ritmo da aula sozinho.

    Votar fora de uma janela aberta não é erro: é uma corrida normal (o aluno
    clicou no instante em que a janela fechou). Responde o estado sem gravar,
    em vez de um 4xx que a tela teria de tratar.
    """
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    if "vote_ends_at" not in row.keys() or not row["vote_ends_at"]:
        return _row_to_state(row)
    if datetime.now(timezone.utc) >= row["vote_ends_at"]:
        return _row_to_state(row)

    # `jsonb_set` e não ler-modificar-gravar: dois alunos clicando no mesmo
    # instante se sobrescreveriam, e o voto perdido seria invisível.
    await pool().execute(
        "UPDATE video_room_openpbl_class "
        "SET votes = jsonb_set(COALESCE(votes, '{}'::jsonb), ARRAY[$2], $3::jsonb, true) "
        "WHERE room_id=$1",
        room_id, user.id, "true" if body.sim else "false")
    row = await _get_class(room_id)
    estado = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", estado)
    return estado


@router.post("/{room_id}/openpbl/stage")
async def set_stage(room_id: str, body: StageSet, user: CurrentUser = Depends(get_current_user)):
    """Cursor da etapa do facilitador (botão verde ▶). Persiste + sincroniza."""
    await _require_host(user)
    stage = (body.stage or "").strip()
    if stage not in _STAGES:
        raise HTTPException(400, f"stage inválido: {stage}")
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    # MARCA O INÍCIO e descarta voto em curso. Sem isso, o host avançando à mão
    # deixaria a etapa nova com a hora da anterior -- e a cadência abriria um
    # voto imediatamente sobre algo que acabou de começar.
    #
    # As migrations deste repositório são aplicadas À MÃO, então o código pode
    # chegar ao servidor antes do schema. Este botão é ANTERIOR à cadência: se
    # ele escrevesse as colunas novas sem conferir, um deploy sem a 018 tiraria
    # do host o único controle que ele sempre teve. Avançar a etapa não depende
    # da cadência, e aqui não passa a depender.
    await _ao_mudar_de_etapa(room_id, row, row["stage"], stage, automatico=False)
    if "auto_mode" in row.keys():
        await pool().execute(
            "UPDATE video_room_openpbl_class "
            "SET stage=$2, stage_started_at=$3, vote_ends_at=NULL, vote_stage=NULL, "
            "    votes='{}'::jsonb WHERE room_id=$1",
            room_id, stage, datetime.now(timezone.utc))
    else:
        await pool().execute(
            "UPDATE video_room_openpbl_class SET stage=$2 WHERE room_id=$1",
            room_id, stage)
    # O freio de mão também é comunicação: quando o host avança à mão, a turma
    # vê uma etapa mudar sem o voto que a cadência faria. Sem registrar, o
    # histórico teria um buraco exatamente nos momentos em que alguém assumiu o
    # controle -- que são os que mais interessam a quem supervisiona.
    await _registrar_comunicacao(room_id, ("etapa_manual", {"stage": stage}))

    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


@router.get("/{room_id}/openpbl/comunicacoes")
async def listar_comunicacoes(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    """O histórico do encontro, em ordem. Para TODO MUNDO, não só o host.

    `optional_user`, e não `_require_host`: quem chegou atrasado é justamente
    quem mais precisa ler o que já foi dito, e o aluno não tem outra forma de
    saber. É também o que torna o facilitador automático auditável durante a
    própria aula, em vez de só depois, no log.

    Devolve lista vazia enquanto a tabela não existe — a tela some, não quebra.
    """
    if not await tem_tabela("video_room_comunicacoes"):
        return {"comunicacoes": []}
    linhas = await pool().fetch(
        "SELECT at, tipo, texto, meta FROM video_room_comunicacoes "
        "WHERE room_id=$1 ORDER BY at", room_id)
    return {"comunicacoes": [
        {
            "at": l["at"].isoformat(),
            "tipo": l["tipo"],
            "texto": l["texto"] or "",
            "meta": (json.loads(l["meta"]) if isinstance(l["meta"], str) else (l["meta"] or {})),
        }
        for l in linhas
    ]}


@router.get("/{room_id}/openpbl/transcricao")
async def listar_transcricao(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """A transcrição do encontro, em ordem, com quem falou.

    SÓ PARA QUEM DIRIGE, ao contrário do histórico das comunicações. A diferença
    é deliberada e não é sobre sigilo: o histórico é um registro de atos ("a
    turma aprovou: seguindo para Plenária"), enquanto isto é a fala das pessoas
    passada por um reconhecedor que erra. Pôr na tela do aluno o que o colega
    "disse" -- com o erro do ASR embutido -- cria uma discussão que não é a da
    aula, e acontece justamente no meio dela.

    Quem supervisiona precisa ver, porque o item do MVP que isto atende é
    "primeiras execuções com supervisão": a transcrição é o que permite revisar
    um encontro que rodou sem facilitador humano.

    Devolve lista vazia enquanto a tabela não existe — publicar não aplica
    migration, e a tela some em vez de quebrar.
    """
    await _require_host(user)
    if not await tem_tabela("video_room_transcricao"):
        return {"transcricao": []}
    linhas = await pool().fetch(
        "SELECT identity, nome, inicio, fim, texto, stage, motor "
        "FROM video_room_transcricao WHERE room_id=$1 ORDER BY inicio", room_id)
    return {"transcricao": [
        {
            "identity": l["identity"],
            "nome": l["nome"] or "",
            "inicio": l["inicio"].isoformat(),
            "fim": l["fim"].isoformat(),
            "texto": l["texto"],
            "stage": l["stage"] or "",
            "motor": l["motor"] or "",
        }
        for l in linhas
    ]}


@router.post("/{room_id}/openpbl/voz")
async def preparar_voz(room_id: str, user: CurrentUser = Depends(get_current_user)):
    """Sintetiza a voz dos textos fixos desta sala, e diz o que fez.

    A síntese normalmente acontece sozinha quando a SALA É CRIADA, em segundo
    plano. Esta rota existe por dois motivos que o aquecimento automático não
    cobre:

    · **conferir**: é a única forma de saber se o segredo e o CoreService estão
      certos sem criar uma sala e esperar o log — `{"pedidos": 0, "ja_tinha":
      20}` prova a ponta a ponta que a voz existe;
    · **consertar**: salas criadas ANTES desta versão, ou criadas enquanto o
      CoreService estava fora, não têm áudio nenhum e não seriam aquecidas por
      nada.

    Síncrona, ao contrário do aquecimento: quem chamou está esperando o número.
    Idempotente — o que já existe não é pedido de novo.
    """
    await _require_host(user)
    linha = await pool().fetchrow("SELECT roteiro FROM video_rooms WHERE id=$1", room_id)
    if not linha:
        raise HTTPException(404, "sala não encontrada")
    bruto = linha["roteiro"]
    roteiro = json.loads(bruto) if isinstance(bruto, str) else bruto
    if not roteiro:
        return {"desligado": 0, "pedidos": 0, "prontos": 0, "falhas": 0, "ja_tinha": 0,
                "detalhe": "sala sem roteiro: não há texto fixo para falar"}
    return await voz_porta.preparar(roteiro)


# ── roster: status dos alunos p/ as bordas dos tiles ──────────────────────
# Verde = dentro do pacote; vermelho = fora; badge = registrou presença na
# sessão (Presentation/Students). Todo cliente da sala faz polling, então o
# resultado é cacheado por sala (1 varredura LRS/attendance a cada ~8s).
_roster_cache: dict[str, tuple[float, dict]] = {}
_ROSTER_TTL = 8.0
# Status "grudento" (sticky) por sala. O verde/vermelho ao redor da webcam deve mudar
# só com um sinal REAL (eventos do pacote → verde; package_exited → vermelho). Sem isto,
# uma falha transitória do LRS ou da API de presença invertia a resposta e a borda
# piscava. Guardamos o último status conhecido de cada aluno e a última lista de
# registrados: quando uma chamada falha nesta rodada, mantemos o que já sabíamos.
_roster_sticky: dict[str, dict[str, bool]] = {}      # room_id -> {email: in_package}
_roster_registered: dict[str, set[str]] = {}         # room_id -> {emails registrados}


@router.get("/{room_id}/openpbl/roster")
async def class_roster(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    now = time.monotonic()
    hit = _roster_cache.get(room_id)
    if hit and (now - hit[0]) < _ROSTER_TTL:
        return hit[1]

    room = await pool().fetchrow(
        "SELECT created_at, owner_id, roteiro, risk_dimensions FROM video_rooms WHERE id=$1", room_id)
    if not room:
        raise HTTPException(404, "room not found")
    cls = await _get_class(room_id)
    parts = await pool().fetch(
        "SELECT user_id, display_name, email, is_staff FROM video_room_participants "
        "WHERE room_id=$1 AND left_at IS NULL", room_id)

    since_iso = room["created_at"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    lrs = settings.scorm_lrs_url.rstrip("/")

    # Presença registrada na sessão (lista do Presentation/Students). Se a chamada
    # falhar NESTA rodada, mantemos a última lista conhecida em vez de zerar — assim
    # a badge de registrado e o fallback do status não somem por um hiccup de rede.
    registered_emails: set[str] = set()
    reg_ok = False
    if cls and settings.openpbl_integration_apikey:
        try:
            async with cliente_http(timeout=10) as c:
                r = await c.get(
                    f"{settings.openpbl_integration_url.rstrip('/')}/api/Presentation/Students/{cls['presentation_code']}",
                    headers={"Accept": "application/json", "apikey": settings.openpbl_integration_apikey})
                if r.status_code == 200:
                    reg_ok = True
                    for s in ((r.json() or {}).get("data") or []):
                        if s.get("email"):
                            registered_emails.add(s["email"].strip().lower())
        except Exception:
            pass
    if reg_ok:
        _roster_registered[room_id] = registered_emails
    else:
        registered_emails = _roster_registered.get(room_id, registered_emails)

    async def fetch_events_by_student(emails_list: list[str]) -> dict:
        """Eventos da turma INTEIRA numa única chamada ao LRS.

        Antes isto era 1 request por aluno disparado em paralelo (asyncio.gather). Numa
        aula grande, isso abria N conexões simultâneas no Scorm, esgotava o pool e
        derrubava o serviço (incidente 2026-07-24). Agora: 1 request para a turma toda.
        Em falha devolve {} → cada aluno vira None (sem sinal) e a resolução grudenta
        abaixo mantém o último status — mesmo comportamento de antes.
        """
        if not emails_list:
            return {}
        try:
            async with cliente_http(timeout=15) as c:
                r = await c.get(f"{lrs}/interaction-events/by-students",
                                params={"studentEmails": ",".join(emails_list),
                                        "limitPerStudent": 60})
            return (r.json() or {}).get("data") or {}
        except Exception:
            return {}

    def in_package(evs) -> bool | None:
        """True/False pelo LRS; None = sem eventos na sessão (LRS pode atrasar)."""
        sess = sorted([e for e in (evs or []) if (e.get("createdAt") or "") >= since_iso],
                      key=lambda x: x.get("createdAt") or "", reverse=True)
        if not sess:
            return None
        if sess[0].get("eventType") == "package_exited":
            return False
        return any(e.get("eventType") in ("package_opened", "activity_accessed",
                                          "authenticated", "quiz_answered", "lesson_score",
                                          "package_completed") for e in sess)

    emails = {(p["email"] or "").strip().lower(): None for p in parts
              if p["email"] and not p["is_staff"] and p["user_id"] != room["owner_id"]}
    by_student = await fetch_events_by_student(list(emails.keys()))
    flags = [in_package(by_student.get(e)) for e in emails]
    # Resolução grudenta: `flag` só é True/False quando o LRS deu um sinal DEFINITIVO
    # (eventos do pacote / package_exited). Quando é None (LRS falhou ou ainda sem
    # eventos) NÃO invertemos o status — mantemos o último conhecido; e só no 1º contato
    # (sem histórico) o registro de presença vale como evidência de pacote aberto.
    prev = _roster_sticky.get(room_id, {})

    def _resolve(email: str, flag) -> bool:
        if flag is not None:
            return flag                       # sinal real do LRS → manda
        if email in prev:
            return prev[email]                # sem sinal: mantém o último status (anti-piscar)
        return email in registered_emails     # 1º contato: registrado ⇒ presume no pacote

    in_pkg = {e: _resolve(e, f) for e, f in zip(emails.keys(), flags)}
    _roster_sticky[room_id] = in_pkg          # store limitado aos participantes atuais
    identidade_do_email = {(p["email"] or "").strip().lower(): p["user_id"] for p in parts if p["email"]}
    situacao = await _sincronizar_suporte(
        room_id, cls, {identidade_do_email[e]: v for e, v in in_pkg.items() if e in identidade_do_email})
    respostas_esperadas = _respostas_de_risco_esperadas(room)
    nao_fizeram = set(_json_da_coluna(cls, "riscos_nf", [])) if cls else set()

    # Quem está conectado AGORA, segundo o LiveKit. A tabela não sabe: ver
    # `_presentes` -- `left_at` nunca fecha, então ela lista quem já entrou
    # nesta sala algum dia. A LISTA de alunos segue inteira, porque a tela a
    # consome como tabela de consulta por identidade (`byId[s.identity]`) e uma
    # entrada a mais ali é inerte; é para CONTAR que a diferença importa.
    # Pelo NOME no LiveKit, não pelo uuid -- ver `_nome_no_livekit`. É daqui que
    # sai `progresso.alunos`, o "de N" do cartão de voto: com o uuid ele dizia
    # "0 de 0 alunos responderam" numa sala com gente, e depois "1 de 0".
    na_sala = set(await list_participant_identities(await _nome_no_livekit(room_id)))
    situacao = await _acolher_quem_chegou_sem_pacote(
        room_id, cls, in_pkg, identidade_do_email, na_sala, situacao)

    students = []
    for p in parts:
        email = (p["email"] or "").strip().lower()
        is_staff = bool(p["is_staff"]) or p["user_id"] == room["owner_id"]
        students.append({
            "identity": p["user_id"],
            "name": p["display_name"] or p["user_id"],
            "is_staff": is_staff,
            "na_sala": p["user_id"] in na_sala,
            "in_package": (in_pkg.get(email, False) if not is_staff else None),
            "suporte": situacao.get(p["user_id"]),
            "nao_fez_riscos": p["user_id"] in nao_fizeram,
            "concluiu_riscos": (
                bool(email and not is_staff and (
                    respostas_de_risco(by_student.get(email), since_iso) >= respostas_esperadas
                    if respostas_esperadas else
                    respondeu(by_student.get(email), since_iso, e_resposta_de_risco)))),
            "registered": (email in registered_emails) if (email and not is_staff) else False,
            # PROGRESSO DAS RESPOSTAS, derivado dos MESMOS eventos que já foram
            # buscados acima. Uma consulta a mais por aluno, numa sala com 30,
            # seriam 30 chamadas ao LRS a cada 8 segundos.
            #
            # Serve a quem conduz: com a cadência decidindo sozinha, é por aqui
            # que um humano vê se faz sentido assumir o manual antes de a sala
            # avançar com metade da turma pela metade.
            "respondeu_riscos": (
                respondeu(by_student.get(email), since_iso, e_resposta_de_risco)
                if (email and not is_staff) else None),
            "avaliou_pares": (
                respondeu(by_student.get(email), since_iso, e_avaliacao_de_pares)
                if (email and not is_staff) else None),
        })

    out = {
        "code": cls["presentation_code"] if cls else None,
        "activity_id": cls["activity_id"] if cls else None,
        "facilitator_email": cls["facilitator_email"] if cls else None,
        "facilitator_name": cls["facilitator_name"] if cls else None,
        "checking_open": cls["checking_open"] if cls else None,
        "code_hidden": cls["code_hidden"] if cls else False,
        "students": students,
        # O RESUMO, pronto. A tela poderia contar, mas então cada cliente
        # contaria do seu jeito -- e "12 de 30" na tela do host precisa ser o
        # mesmo número que a cadência enxerga.
        #
        # Por isso NUMERADOR E DENOMINADOR são sobre quem está na sala agora, a
        # mesma turma que a cadência apura. Contar pelo `left_at` punha aqui
        # todo mundo que já entrou nesta sala algum dia: "3 de 47" numa turma de
        # 12, que é um número plausível e errado -- o pior tipo.
        "progresso": {
            "riscos": sum(1 for e in students if e.get("respondeu_riscos") and e["na_sala"]),
            "pares": sum(1 for e in students if e.get("avaliou_pares") and e["na_sala"]
                         and e["suporte"] in (None, "resolvido")),
            "alunos": sum(1 for e in students if not e["is_staff"] and e["na_sala"]),
            # Os 90% dos riscos: quem está na sala, sem ouvintes nem quem está no suporte.
            "riscos_concluidos": sum(1 for e in students if e["concluiu_riscos"] and e["na_sala"]
                                     and e["suporte"] in (None, "resolvido")),
            "elegiveis": sum(1 for e in students if not e["is_staff"] and e["na_sala"]
                             and e["suporte"] in (None, "resolvido")),
        },
    }
    _roster_cache[room_id] = (now, out)
    await _avaliar_prazo_dos_riscos(room_id, cls, out["progresso"])
    return out


# ── Turma: suporte, ouvintes, líder geral, perguntas e prazo dos riscos ─────────
#: Janelas da escolha do líder.
JANELA_DOS_VOLUNTARIOS = timedelta(seconds=60)
JANELA_DA_VOTACAO = timedelta(seconds=30)
#: Queda breve de conexão não troca o líder.
TOLERANCIA_DO_LIDER = timedelta(seconds=30)
#: Fração dos elegíveis que precisa concluir os riscos para abrir o prazo final.
FRACAO_DOS_RISCOS = 0.9
PRAZO_DOS_RISCOS = timedelta(minutes=5)
DURACAO_DOS_GRUPOS_NO_AUTOMATICO = 900


async def _tem_turma(room_id: str) -> bool:
    return await tem_tabela("video_room_suporte")


async def _fora_da_turma(room_id: str) -> set[str]:
    """Quem não entra na divisão, nem na eleição, nem nos 90%."""
    if not await _tem_turma(room_id):
        return set()
    linhas = await pool().fetch(
        "SELECT identity FROM video_room_suporte WHERE room_id=$1 AND status IN ('suporte','ouvinte')",
        room_id)
    return {l["identity"] for l in linhas}


async def _estado_do_suporte(room_id: str) -> list[dict]:
    if not await _tem_turma(room_id):
        return []
    linhas = await pool().fetch(
        "SELECT identity, display_name, status, pediu_ajuda_em FROM video_room_suporte "
        "WHERE room_id=$1 ORDER BY entrou_em", room_id)
    return [{"identity": l["identity"], "name": l["display_name"], "status": l["status"],
             "pediu_ajuda": l["pediu_ajuda_em"].isoformat() if l["pediu_ajuda_em"] else None}
            for l in linhas]


async def _avisar_suporte(room_id: str) -> None:
    await hub.broadcast(room_id, "suporte-state", {"membros": await _estado_do_suporte(room_id)})


async def _abrir_suporte(room_id: str) -> None:
    """Ao encerrar o registro: quem está na sala sem o pacote vai para a sala de suporte.
    Aluno sem e-mail fica de fora: sem e-mail não há como saber se o pacote conectou, e
    mandá-lo para o suporte seria prendê-lo lá por uma falta que não é dele."""
    if not await _tem_turma(room_id):
        return
    _roster_cache.pop(room_id, None)
    roster = await class_roster(room_id, None)
    emails = {l["user_id"]: l["email"] for l in await pool().fetch(
        "SELECT user_id, email FROM video_room_participants WHERE room_id=$1", room_id)}
    alunos = [s for s in roster["students"]
              if not s["is_staff"] and s["na_sala"] and emails.get(s["identity"])]
    # Ninguém com o pacote numa turma de dois ou mais é falta de sinal, não um problema de
    # cada aluno. Com o LRS fora do ar, isto esvaziaria a sala no meio da aula.
    if len(alunos) >= 2 and not any(s["in_package"] for s in alunos):
        logger.warning("[turma] sala=%s nenhum aluno com pacote: suporte automático não aberto", room_id)
        return
    for s in alunos:
        if s["in_package"]:
            continue
        await pool().execute(
            "INSERT INTO video_room_suporte (room_id, identity, display_name) VALUES ($1,$2,$3) "
            "ON CONFLICT (room_id, identity) DO NOTHING", room_id, s["identity"], s["name"])
    await _avisar_suporte(room_id)


async def _sincronizar_suporte(room_id: str, cls, no_pacote: dict[str, bool]) -> dict[str, str]:
    """Checagem automática: conectou o pacote, sai do suporte. O ouvinte volta a participar
    na plenária: antes dela, entraria num grupo já em andamento."""
    if not cls or not await _tem_turma(room_id):
        return {}
    mudou = False
    plenaria_em_diante = cadencia.ORDEM.index("plenary") <= (
        cadencia.ORDEM.index(cls["stage"]) if cls["stage"] in cadencia.ORDEM else -1)
    linhas = await pool().fetch(
        "SELECT identity, status FROM video_room_suporte WHERE room_id=$1", room_id)
    situacao = {l["identity"]: l["status"] for l in linhas}
    for identidade, status in list(situacao.items()):
        if not no_pacote.get(identidade):
            continue
        if status == "suporte":
            situacao[identidade] = "resolvido"
            await pool().execute(
                "UPDATE video_room_suporte SET status='resolvido', resolvido_em=now(), pediu_ajuda_em=NULL "
                "WHERE room_id=$1 AND identity=$2", room_id, identidade)
            mudou = True
        elif status == "ouvinte" and plenaria_em_diante:
            situacao[identidade] = "resolvido"
            await pool().execute(
                "UPDATE video_room_suporte SET status='resolvido', resolvido_em=now() "
                "WHERE room_id=$1 AND identity=$2", room_id, identidade)
            mudou = True
    if mudou:
        await _avisar_suporte(room_id)
    return situacao


async def _acolher_quem_chegou_sem_pacote(room_id: str, cls, no_pacote: dict[str, bool],
                                         identidade_do_email: dict[str, str], na_sala: set[str],
                                         situacao: dict[str, str]) -> dict[str, str]:
    """Quem chega depois de o registro encerrar, sem o pacote: antes da divisão vai para o
    suporte; depois dela, é ouvinte. Quem já esteve num grupo não entra aqui: sair do
    pacote no meio da aula (celular bloqueado) não tira ninguém da turma."""
    if not cls or "lider_fase" not in cls or not cls["lider_fase"] or not any(no_pacote.values()):
        return situacao
    if not await _tem_turma(room_id):
        return situacao
    sem_pacote = [identidade_do_email[e] for e, tem in no_pacote.items()
                  if not tem and e in identidade_do_email
                  and identidade_do_email[e] in na_sala and identidade_do_email[e] not in situacao]
    if not sem_pacote:
        return situacao
    ordem = cadencia.ORDEM
    depois_da_divisao = cls["stage"] in ordem and ordem.index(cls["stage"]) >= ordem.index("groups")
    if depois_da_divisao:
        ja_em_grupo = {l["identity"] for l in await pool().fetch(
            "SELECT identity FROM video_breakout_assignments WHERE parent_room_id=$1", room_id)}
        sem_pacote = [i for i in sem_pacote if i not in ja_em_grupo]
    nomes = {l["user_id"]: l["display_name"] for l in await pool().fetch(
        "SELECT user_id, display_name FROM video_room_participants WHERE room_id=$1", room_id)}
    status = "ouvinte" if depois_da_divisao else "suporte"
    for identidade in sem_pacote:
        await pool().execute(
            "INSERT INTO video_room_suporte (room_id, identity, display_name, status) VALUES ($1,$2,$3,$4) "
            "ON CONFLICT (room_id, identity) DO NOTHING",
            room_id, identidade, nomes.get(identidade) or "", status)
        situacao[identidade] = status
    if sem_pacote:
        await _avisar_suporte(room_id)
    return situacao


async def _dividir_grupos(room_id: str, duracao: int) -> dict:
    """O limite do suporte é aqui: quem não resolveu vira ouvinte, e o resto é dividido."""
    if await _tem_turma(room_id):
        await pool().execute(
            "UPDATE video_room_suporte SET status='ouvinte', pediu_ajuda_em=NULL "
            "WHERE room_id=$1 AND status='suporte'", room_id)
        await _avisar_suporte(room_id)
    await _auto_group_breakouts(room_id)
    return await abrir_grupos(room_id, duracao)


async def _ao_mudar_de_etapa(room_id: str, row, antes: str, depois: str, *, automatico: bool) -> None:
    """O que a troca de etapa FAZ, além de mudar a etapa. Falha aqui não pode travar a aula."""
    ordem = cadencia.ORDEM
    avancou = antes in ordem and depois in ordem and ordem.index(depois) > ordem.index(antes)
    try:
        if automatico and depois == "groups":
            await _dividir_grupos(room_id, encontro.atuais()["duracoes"].get("groups") or DURACAO_DOS_GRUPOS_NO_AUTOMATICO)
        if automatico and antes == "groups":
            await fechar_grupos(room_id)
        if automatico and depois == "release_risks":
            await _liberar_questionario(room_id, row, "risks")
        if automatico and depois == "release_feedback":
            await _liberar_questionario(room_id, row, "perceptions")
        if "riscos_nf" in row:
            if depois == "release_risks":
                await pool().execute(
                    "UPDATE video_room_openpbl_class SET riscos_prazo=NULL, riscos_nf='[]'::jsonb "
                    "WHERE room_id=$1", room_id)
            if antes == "release_risks" and avancou:
                await _registrar_quem_nao_fez(room_id)
            if depois == "question" and antes == "plenary":
                await pool().execute(
                    "UPDATE video_room_openpbl_class SET questao_atual=0 WHERE room_id=$1", room_id)
    except Exception:
        logger.exception("[turma] sala=%s efeito de %s -> %s falhou", room_id, antes, depois)


def _respostas_de_risco_esperadas(room) -> int:
    """Cada risco é avaliado duas vezes: probabilidade e impacto. Zero = não se sabe."""
    roteiro = room["roteiro"]
    if isinstance(roteiro, str):
        roteiro = json.loads(roteiro or "null")
    riscos = [r for r in ((roteiro or {}).get("campos") or {}).get("riscos") or [] if r]
    if not riscos:
        dimensoes = room["risk_dimensions"]
        riscos = json.loads(dimensoes) if isinstance(dimensoes, str) else (dimensoes or [])
    return 2 * len(riscos)


async def _avaliar_prazo_dos_riscos(room_id: str, cls, progresso: dict) -> None:
    if not cls or "riscos_prazo" not in cls or cls["stage"] != "release_risks" or cls["riscos_prazo"]:
        return
    if progresso["elegiveis"] and progresso["riscos_concluidos"] / progresso["elegiveis"] >= FRACAO_DOS_RISCOS:
        await pool().execute(
            "UPDATE video_room_openpbl_class SET riscos_prazo=$2 WHERE room_id=$1 AND riscos_prazo IS NULL",
            room_id, datetime.now(timezone.utc) + PRAZO_DOS_RISCOS)
        await hub.broadcast(room_id, "openpbl-class", _row_to_state(await _get_class(room_id)))


async def _registrar_quem_nao_fez(room_id: str) -> None:
    """NF = não respondeu nada. Quem respondeu pela metade não entra: o pacote grava cada
    resposta na hora, então o que ele fez já está salvo."""
    _roster_cache.pop(room_id, None)
    roster = await class_roster(room_id, None)
    nf = [s["identity"] for s in roster["students"]
          if not s["is_staff"] and s["suporte"] in (None, "resolvido")
          and (s["na_sala"] or s["registered"]) and not s["respondeu_riscos"]]
    await pool().execute(
        "UPDATE video_room_openpbl_class SET riscos_nf=$2::jsonb WHERE room_id=$1", room_id, json.dumps(nf))
    _roster_cache.pop(room_id, None)


async def _total_de_questoes(room_id: str) -> int:
    roteiro = await pool().fetchval("SELECT roteiro FROM video_rooms WHERE id=$1", room_id)
    if isinstance(roteiro, str):
        roteiro = json.loads(roteiro or "null")
    return len([q for q in ((roteiro or {}).get("campos") or {}).get("questoesPlenaria") or [] if q])


async def _mudar_de_questao(room_id: str, indice: int) -> dict:
    await pool().execute(
        "UPDATE video_room_openpbl_class SET questao_atual=$2, stage_started_at=$3, vote_ends_at=NULL, "
        "vote_stage=NULL, votes='{}'::jsonb WHERE room_id=$1", room_id, indice, datetime.now(timezone.utc))
    estado = _row_to_state(await _get_class(room_id))
    await hub.broadcast(room_id, "openpbl-class", estado)
    return estado


async def _iniciar_escolha_do_lider(room_id: str) -> None:
    row = await _get_class(room_id)
    if not row or "lider_fase" not in row or row["lider_fase"]:
        return
    await pool().execute(
        "UPDATE video_room_openpbl_class SET lider_fase='voluntarios', lider_fase_ate=$2 "
        "WHERE room_id=$1 AND lider_fase IS NULL", room_id, datetime.now(timezone.utc) + JANELA_DOS_VOLUNTARIOS)


async def _elegiveis(room_id: str) -> list[str]:
    fora = await _fora_da_turma(room_id)
    return [i for i in await _presentes(room_id) if i not in fora]


async def _definir_lider(room_id: str, identidade: str, fase_de: str) -> None:
    await pool().execute(
        "UPDATE video_room_openpbl_class SET lider_fase='definido', lider_fase_ate=NULL, lider_identity=$2, "
        "lider_ausente_desde=NULL WHERE room_id=$1 AND lider_fase=$3", room_id, identidade, fase_de)


async def _abrir_votacao(room_id: str, candidatos: list[str], fase_de: str) -> None:
    await pool().execute(
        "UPDATE video_room_openpbl_class SET lider_fase='votacao', lider_fase_ate=$2, lider_candidatos=$3::jsonb, "
        "lider_votos='{}'::jsonb, lider_identity=NULL, lider_ausente_desde=NULL WHERE room_id=$1 AND lider_fase=$4",
        room_id, datetime.now(timezone.utc) + JANELA_DA_VOTACAO, json.dumps(candidatos), fase_de)


#: Última verificação de presença do líder por sala: ela custa uma chamada ao LiveKit, e
#: isto roda no polling de todo mundo.
_lider_checado: dict[str, float] = {}


async def _aplicar_lider(room_id: str, row):
    """Como a cadência, a escolha do líder é avaliada na leitura: sobrevive a reinício de
    processo e a duas réplicas, e os `WHERE lider_fase=` garantem que só uma decide."""
    if not row or "lider_fase" not in row or not row["lider_fase"]:
        return row
    fase, agora = row["lider_fase"], datetime.now(timezone.utc)
    if fase in ("voluntarios", "votacao") and row["lider_fase_ate"] and agora >= row["lider_fase_ate"]:
        elegiveis = await _elegiveis(room_id)
        if not elegiveis:
            # Sala vazia não escolhe líder: espera alguém voltar.
            await pool().execute(
                "UPDATE video_room_openpbl_class SET lider_fase_ate=$2 WHERE room_id=$1",
                room_id, agora + JANELA_DA_VOTACAO)
        elif fase == "voluntarios":
            definido, candidatos = regra_do_lider.resultado_dos_voluntarios(
                _json_da_coluna(row, "lider_voluntarios", []), elegiveis)
            if definido:
                await _definir_lider(room_id, definido, fase)
            else:
                await _abrir_votacao(room_id, candidatos, fase)
        else:
            candidatos = [c for c in _json_da_coluna(row, "lider_candidatos", []) if c in elegiveis] or elegiveis
            escolhido = regra_do_lider.vencedor(_json_da_coluna(row, "lider_votos", {}), candidatos)
            await _definir_lider(room_id, escolhido, fase)
    elif fase == "definido" and time.monotonic() - _lider_checado.get(room_id, 0) >= 10:
        _lider_checado[room_id] = time.monotonic()
        # Com os grupos abertos a sala principal fica vazia: isso não é o líder ter caído.
        aberto = await pool().fetchval("SELECT breakout_open FROM video_rooms WHERE id=$1", room_id)
        if aberto:
            return row
        elegiveis = await _elegiveis(room_id)
        ausente = row["lider_ausente_desde"]
        if row["lider_identity"] in elegiveis:
            if ausente:
                await pool().execute(
                    "UPDATE video_room_openpbl_class SET lider_ausente_desde=NULL WHERE room_id=$1", room_id)
            return row
        if not ausente:
            await pool().execute(
                "UPDATE video_room_openpbl_class SET lider_ausente_desde=$2 WHERE room_id=$1", room_id, agora)
            return row
        if agora - ausente < TOLERANCIA_DO_LIDER or not elegiveis:
            return row
        novo = regra_do_lider.substituto(
            _json_da_coluna(row, "lider_votos", {}), row["lider_identity"], elegiveis)
        if novo:
            await _definir_lider(room_id, novo, fase)
        else:
            await _abrir_votacao(room_id, elegiveis, fase)
    else:
        return row
    nova = await _get_class(room_id)
    if nova["lider_fase"] != fase or nova["lider_identity"] != row["lider_identity"]:
        await hub.broadcast(room_id, "openpbl-class", _row_to_state(nova))
    return nova


class VotoDoLider(BaseModel):
    candidato: str


@router.post("/{room_id}/openpbl/lider/voluntario")
async def voluntariar(room_id: str, user: CurrentUser = Depends(get_current_user)):
    row = await _get_class(room_id)
    if not row or row["lider_fase"] != "voluntarios":
        raise HTTPException(409, "a janela de voluntários não está aberta")
    await pool().execute(
        "UPDATE video_room_openpbl_class SET lider_voluntarios=lider_voluntarios || to_jsonb($2::text) "
        "WHERE room_id=$1 AND NOT lider_voluntarios ? $2", room_id, user.id)
    estado = _row_to_state(await _get_class(room_id))
    await hub.broadcast(room_id, "openpbl-class", estado)
    return estado


@router.post("/{room_id}/openpbl/lider/voto")
async def votar_no_lider(room_id: str, body: VotoDoLider, user: CurrentUser = Depends(get_current_user)):
    row = await _get_class(room_id)
    if not row or row["lider_fase"] != "votacao":
        raise HTTPException(409, "não há votação de líder aberta")
    if user.id in await _fora_da_turma(room_id):
        raise HTTPException(403, "ouvinte não vota")
    await pool().execute(
        "UPDATE video_room_openpbl_class SET lider_votos=lider_votos || jsonb_build_object($2::text, $3::text) "
        "WHERE room_id=$1", room_id, user.id, body.candidato)
    estado = _row_to_state(await _get_class(room_id))
    await hub.broadcast(room_id, "openpbl-class", estado)
    return estado


class PassoDaQuestao(BaseModel):
    delta: int = 1


@router.post("/{room_id}/openpbl/questao")
async def mudar_de_questao(room_id: str, body: PassoDaQuestao, user: CurrentUser = Depends(get_current_user)):
    """Próxima pergunta da plenária: só para o líder geral e para quem conduz."""
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    if not user.is_staff and user.id != row["lider_identity"]:
        raise HTTPException(403, "só o líder pode seguir para a próxima pergunta")
    if row["stage"] != "question":
        raise HTTPException(409, "a plenária não está nas perguntas")
    total = await _total_de_questoes(room_id)
    indice = max(0, row["questao_atual"] + (1 if body.delta > 0 else -1))
    if body.delta > 0 and indice >= total:
        # Depois da última pergunta, a plenária termina, para o líder como para o facilitador.
        await _ao_mudar_de_etapa(room_id, row, "question", "situational", automatico=False)
        await pool().execute(
            "UPDATE video_room_openpbl_class SET stage='situational', stage_started_at=$2, vote_ends_at=NULL, "
            "vote_stage=NULL, votes='{}'::jsonb WHERE room_id=$1", room_id, datetime.now(timezone.utc))
        estado = _row_to_state(await _get_class(room_id))
        await hub.broadcast(room_id, "openpbl-class", estado)
        return estado
    return await _mudar_de_questao(room_id, indice)


class DivisaoDosGrupos(BaseModel):
    duration_seconds: int = 600


@router.post("/{room_id}/openpbl/dividir-grupos")
async def dividir_grupos(room_id: str, body: DivisaoDosGrupos, user: CurrentUser = Depends(get_current_user)):
    await _require_host(user)
    return await _dividir_grupos(room_id, body.duration_seconds)


@router.get("/{room_id}/openpbl/suporte")
async def ver_suporte(room_id: str, user: CurrentUser | None = Depends(optional_user)):
    return {"membros": await _estado_do_suporte(room_id)}


class TokenDoSuporte(BaseModel):
    identity: str
    display_name: str | None = None


@router.post("/{room_id}/openpbl/suporte/token")
async def token_do_suporte(room_id: str, body: TokenDoSuporte, user: CurrentUser | None = Depends(optional_user)):
    """A sala de suporte é uma sala LiveKit própria. Quem conduz entra quando quiser; o
    aluno, só enquanto estiver no suporte."""
    e_host = bool(user and user.is_staff)
    if not e_host:
        presente = await pool().fetchval(
            "SELECT 1 FROM video_room_suporte WHERE room_id=$1 AND identity=$2 AND status='suporte'",
            room_id, body.identity)
        if not presente:
            raise HTTPException(403, "fora da sala de suporte")
    nome = await _nome_no_livekit(room_id)
    token = create_token(
        room_name=f"{nome}__suporte", identity=body.identity,
        display_name=body.display_name or (user.name if user else "Participante"),
        is_admin=e_host, allow_screen_share=True,
    )
    return {"token": token, "livekit_url": settings.livekit_url, "group_name": "Sala de suporte"}


@router.post("/{room_id}/openpbl/suporte/ajuda")
async def pedir_ajuda(room_id: str, user: CurrentUser = Depends(get_current_user)):
    await pool().execute(
        "UPDATE video_room_suporte SET pediu_ajuda_em=now() WHERE room_id=$1 AND identity=$2",
        room_id, user.id)
    await _avisar_suporte(room_id)
    return {"ok": True}


class CodeVisibility(BaseModel):
    hidden: bool


@router.post("/{room_id}/openpbl/code-visibility")
async def set_code_visibility(room_id: str, body: CodeVisibility, user: CurrentUser = Depends(get_current_user)):
    """Facilitador oculta/reexibe o card do class-code para todos."""
    await _require_host(user)
    row = await _get_class(room_id)
    if not row:
        raise HTTPException(404, "aula OpenPBL não iniciada nesta sala")
    await pool().execute(
        "UPDATE video_room_openpbl_class SET code_hidden=$2 WHERE room_id=$1", room_id, body.hidden)
    _roster_cache.pop(room_id, None)   # invalida o cache p/ refletir na hora
    row = await _get_class(room_id)
    state = _row_to_state(row)
    await hub.broadcast(room_id, "openpbl-class", state)
    return state


# ── chat do facilitador (proxy do painel do professor) ────────────────────
@router.get("/{room_id}/openpbl/chat/conversations")
async def chat_conversations(room_id: str, user: CurrentUser = Depends(get_current_user)):
    await _require_host(user)
    async with cliente_http(timeout=20, auth=_chat_auth()) as c:
        r = await c.get(f"{settings.openpbl_chat_url.rstrip('/')}/api/conversations")
        if r.status_code != 200:
            raise HTTPException(502, f"chat OpenPBL falhou ({r.status_code})")
        return r.json()


@router.get("/{room_id}/openpbl/chat/conversations/{conv_id}/messages")
async def chat_messages(room_id: str, conv_id: str, user: CurrentUser = Depends(get_current_user)):
    await _require_host(user)
    async with cliente_http(timeout=20, auth=_chat_auth()) as c:
        r = await c.get(f"{settings.openpbl_chat_url.rstrip('/')}/api/conversations/{conv_id}/messages")
        if r.status_code != 200:
            raise HTTPException(502, f"chat OpenPBL falhou ({r.status_code})")
        return r.json()


@router.post("/{room_id}/openpbl/chat/conversations/{conv_id}/reply")
async def chat_reply(room_id: str, conv_id: str, body: ChatReply, user: CurrentUser = Depends(get_current_user)):
    await _require_host(user)
    text = (body.content or "").strip()
    if not text:
        raise HTTPException(400, "mensagem vazia")
    async with cliente_http(timeout=20, auth=_chat_auth()) as c:
        r = await c.post(
            f"{settings.openpbl_chat_url.rstrip('/')}/api/conversations/{conv_id}/reply",
            json={"content": text})
        if r.status_code != 200:
            raise HTTPException(502, f"chat OpenPBL reply falhou ({r.status_code})")
        return r.json()

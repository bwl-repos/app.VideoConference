# -*- coding: utf-8 -*-
"""A tela de configuração do encontro: etapas, temporizadores, textos e voz.

Vive sob `/api/admin/encontro` por uma razão operacional, e não estética: o
cookie de sessão do admin é gravado com `path=/api/admin` (ver `admin_auth`).
Uma rota fora desse caminho simplesmente não recebe o cookie, e a tela daria
401 sem nada de errado no login.

## O que cada rota existe para resolver

| rota | existe porque |
|---|---|
| `GET /` | a tela precisa do catálogo DE ETAPAS junto da configuração — senão ela teria de guardar a sua própria cópia da ordem do encontro |
| `PUT /` | gravar, e devolver o que FICOU valendo (a poda é silenciosa de propósito; ver `encontro.normalizar`) |
| `GET /vozes` | o acervo de vozes é da conta do ElevenLabs e muda; uma lista escrita aqui esconderia a voz criada ontem |
| `POST /previa` | ouvir ANTES de salvar. Trocar a voz de todos os encontros às cegas é a decisão que ninguém deveria ter de tomar |
| `POST /aquecer` | depois de trocar a voz, pagar a síntese AGORA em vez de empurrá-la para a primeira sala criada depois |

## A prévia não é um sintetizador de texto livre

Ela aceita um texto curto e devolve mp3, e isso é, por construção, uma forma de
gastar a conta de voz de outro serviço. Três travas: exige sessão de admin, tem
teto de caracteres, e o áudio é gravado no bucket sob a MESMA chave que a sala
usaria — então ouvir a prévia de um parágrafo do roteiro já aquece o encontro em
vez de ser um gasto perdido.
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..admin_auth import require_admin
from ..config import settings
from ..db import tem_tabela
from ..services import cadencia, encontro, voz, voz_porta
from ..services.recording_service import s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/encontro", tags=["admin:encontro"])

#: Teto do texto da prévia. O maior parágrafo fixo do roteiro tem ~240
#: caracteres; 1.200 é o mesmo teto que o CoreService aplica por chamada.
TETO_DA_PREVIA = 1200


#: Teto de falas num ensaio. A etapa mais longa do roteiro tem 4 blocos e 9
#: parágrafos; 40 deixa folga larga para quem acrescentar texto, sem permitir
#: que a rota vire um sintetizador em lote.
TETO_DE_FALAS = 40


class Previa(BaseModel):
    texto: str = Field(..., min_length=1, max_length=TETO_DA_PREVIA)
    provedor: str = "polly"
    voz: str = ""
    motor: str = ""


class FalaDoEnsaio(BaseModel):
    texto: str = Field(..., min_length=1, max_length=TETO_DA_PREVIA)
    pausa_ms: int = 0


class Ensaio(BaseModel):
    #: Só para o log e para a resposta: quem decide o que se ouve são as falas.
    etapa: str = ""
    #: O que está NA TELA de quem configura, salvo ou não. É o ponto do ensaio:
    #: ajustar uma palavra e a pausa e ouvir o resultado antes de gravar.
    falas: list[FalaDoEnsaio] = Field(default_factory=list, max_length=TETO_DE_FALAS)


@router.get("")
async def ler(_admin: dict = Depends(require_admin)):
    """Tudo que a tela de configuração precisa, numa requisição.

    Numa só porque as partes não são independentes: a duração pertence à etapa,
    a etapa aponta para a seção, a seção tem os textos e os LUGARES do roteiro.
    Em quatro requisições a tela montaria esse cruzamento no cliente — isto é,
    manteria uma cópia da ordem do encontro, que é exatamente o defeito que já
    custou caro aqui.
    """
    config = await encontro.carregar(forcar=True)
    return {
        "config": config,
        "etapas": encontro.catalogo_para_tela(config),
        # As seções com título e os CAMPOS do roteiro (os lugares, não o
        # conteúdo): é o que a tela mostra como "Questão 1, 2, 3".
        "secoes": [
            {"key": s["key"], "titulo": s["titulo"], "campos": s["campos"]}
            for s in encontro.SECOES_BASE
        ],
        "limites": {
            "duracao": [encontro.MIN_DURACAO, encontro.MAX_DURACAO],
            "pausa": [encontro.MIN_PAUSA, encontro.MAX_PAUSA],
            "janela": [encontro.MIN_JANELA, encontro.MAX_JANELA],
            "tolerancia": [encontro.MIN_TOLERANCIA, encontro.MAX_TOLERANCIA],
        },
        "base": encontro.base(),
        # O estado do mundo, para a tela não prometer o que não vai acontecer:
        # sem a tabela não há onde gravar, e sem o CoreService não há voz.
        "persistente": await _tem_tabela(),
        "voz_configurada": voz_porta.configurado(),
        "avanca_sozinha": sorted(cadencia.AVANCA_SOZINHA),
    }


@router.put("")
async def gravar(corpo: dict, admin: dict = Depends(require_admin)):
    """Grava a configuração. Devolve o que ficou valendo, não o que chegou."""
    try:
        config = await encontro.salvar(corpo, por=str(admin.get("email") or ""))
    except RuntimeError as exc:
        # 409, e não 500: o pedido estava certo e o banco é que está atrás do
        # código (publicar não aplica migration). A tela diz o que falta em vez
        # de parecer um erro do formulário.
        raise HTTPException(409, str(exc)) from exc
    logger.info("[encontro] template salvo por %s", admin.get("email"))
    return {"config": config, "etapas": encontro.catalogo_para_tela(config)}


@router.get("/vozes")
async def listar_vozes(_admin: dict = Depends(require_admin)):
    """O catálogo de vozes, perguntado ao CoreService.

    Daqui não se fala com o ElevenLabs: a chave dele vive no CoreService, que é
    quem sintetiza. Dar uma segunda chave a este serviço só para listar vozes
    seria um segredo a mais para guardar pelo resto da vida.

    Falha devolve lista vazia com o motivo, e não erro: a tela ainda tem de
    poder configurar os temporizadores e os textos quando a voz está fora do ar.
    """
    base = (settings.voz_core_url or "").strip().rstrip("/")
    token = (settings.voz_core_token or "").strip()
    if not base or not token:
        return {"provedores": [], "erro": "VOZ_CORE_URL/VOZ_CORE_TOKEN ausentes neste serviço"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as cliente:
            r = await cliente.get(f"{base}/api/voz/vozes", headers={"X-Voz-Token": token})
        if r.status_code != 200:
            return {"provedores": [], "erro": f"o CoreService respondeu {r.status_code}"}
        return r.json()
    except Exception as exc:   # noqa: BLE001
        logger.warning("[encontro] catalogo de vozes indisponivel: %s", exc)
        return {"provedores": [], "erro": f"não consegui falar com o CoreService: {exc}"}


@router.post("/previa")
async def previa(corpo: Previa, _admin: dict = Depends(require_admin)):
    """O mp3 de um texto na voz escolhida, para ouvir antes de salvar.

    Grava no bucket sob a chave do perfil pedido — a MESMA que a sala usaria —,
    então a prévia aquece o encontro em vez de ser um gasto perdido. E se o
    objeto já existir, não custa nada: devolve o que está lá.
    """
    if not voz_porta.configurado():
        raise HTTPException(503, "voz não configurada neste serviço (VOZ_CORE_URL/VOZ_CORE_TOKEN)")
    pedido = encontro.pedido_de_voz({"voz": {
        "provedor": corpo.provedor, "voz": corpo.voz, "motor": corpo.motor}})
    perfil = encontro.perfil_da_voz({"voz": {
        "provedor": corpo.provedor, "voz": corpo.voz, "motor": corpo.motor}})
    alvo = voz.chave(corpo.texto, perfil)
    try:
        if voz_porta.tem(alvo):
            obj = s3_client().get_object(Bucket=settings.s3_bucket, Key=alvo)
            return Response(content=obj["Body"].read(), media_type="audio/mpeg",
                            headers={"X-Voz-Cache": "hit"})
    except Exception:   # noqa: BLE001
        pass            # objeto ausente é o caso NORMAL aqui
    try:
        mp3 = await voz_porta.sintetizar(voz.normalizar(corpo.texto), pedido)
    except Exception as exc:   # noqa: BLE001
        raise HTTPException(502, str(exc)) from exc
    try:
        voz_porta.guardar(alvo, mp3)
    except Exception:   # noqa: BLE001
        logger.warning("[encontro] previa sintetizada mas nao guardada: %s", alvo)
    return Response(content=mp3, media_type="audio/mpeg", headers={"X-Voz-Cache": "miss"})


@router.post("/ensaio")
async def ensaio(corpo: Ensaio, _admin: dict = Depends(require_admin)):
    """As falas de uma etapa, na ordem, prontas para tocar.

    É o ENSAIO da etapa: quem configura ouve a sequência inteira, com as pausas,
    como a turma vai ouvir. Ajustar o ritmo de uma leitura sem ouvi-la é
    adivinhar — e o erro só apareceria com a turma na sala.

    O que esta rota NÃO faz é sintetizar de um jeito próprio: ela pede o MESMO
    objeto que a sala pediria — mesma chave (`voz.chave(texto, perfil)`), mesmo
    perfil de voz, mesmo bucket. Uma segunda implementação de síntese aqui faria
    o ensaio soar diferente da aula, que é o único jeito de este recurso ser
    pior que não existir.

    Efeito colateral deliberado: o que for sintetizado para o ensaio fica no
    bucket e serve a sala depois. Ensaiar adianta o aquecimento.
    """
    falas = [f for f in corpo.falas if f.texto.strip()]
    if not falas:
        return {"falas": [], "voz": encontro.atuais()["voz"], "desligado": 0}
    if not voz_porta.configurado():
        # Sem voz configurada o ensaio ainda serve para LER a etapa na ordem —
        # devolve as falas sem URL em vez de 503. A tela mostra o texto e diz
        # que não há áudio, que é o mesmo que a sala faz.
        return {"falas": [{"texto": f.texto, "pausa_ms": f.pausa_ms, "url": ""}
                          for f in falas],
                "voz": encontro.atuais()["voz"], "desligado": 1}

    contas = await voz_porta.garantir_textos([f.texto for f in falas])
    config = await encontro.carregar()
    perfil = encontro.perfil_da_voz(config)
    saida = []
    for f in falas:
        try:
            url = voz_porta.assinar(voz.chave(voz.normalizar(f.texto), perfil))
        except Exception:   # noqa: BLE001
            url = ""        # voz indisponível não pode quebrar o ensaio
        saida.append({"texto": f.texto, "pausa_ms": f.pausa_ms, "url": url})
    logger.info("[encontro] ensaio da etapa %s: %s falas %s",
                corpo.etapa or "?", len(saida), contas)
    return {"falas": saida, "voz": config["voz"], **contas}


@router.post("/aquecer")
async def aquecer(_admin: dict = Depends(require_admin)):
    """Sintetiza TODO o texto fixo configurado, na voz corrente.

    É o botão para usar depois de trocar a voz: sem ele, a conta da síntese cai
    na próxima sala criada — e a criação de sala não espera pela voz, então a
    primeira aula depois da troca é a que corre o risco de abrir sem áudio.

    Idempotente: o que já existe no bucket não é pedido de novo. Os números
    devolvidos (`pedidos`, `prontos`, `falhas`, `ja_tinha`) são a única forma de
    conferir que a voz está funcionando sem criar sala.
    """
    config = await encontro.carregar(forcar=True)
    textos: list[str] = []
    for secao in config["secoes"]:
        for bloco in secao["blocos"]:
            textos.extend(bloco["paragrafos"])
    contas = await voz_porta.garantir_textos(textos)
    return {"textos": len(textos), "voz": config["voz"], **contas}


async def _tem_tabela() -> bool:
    try:
        return await tem_tabela(encontro.TABELA)
    except Exception:   # noqa: BLE001
        return False

"""As portas do mundo real da voz do encontro: o bucket desta aplicação e o
CoreService que sintetiza.

Separado de `services/voz.py` de propósito: lá vive a decisão (qual é a chave de
um texto, o que pedir, como alinhar o áudio com o parágrafo), e a decisão tem de
ser exercitável sem AWS, sem rede e sem Polly. Aqui vive o que só funciona em
produção, e por isso aqui não se decide nada.
"""
from __future__ import annotations

import logging

import httpx
from botocore.exceptions import ClientError

from ..config import settings
from . import encontro, voz
from .recording_service import presigned_url, s3_client

logger = logging.getLogger(__name__)

#: Teto da espera pelo CoreService. O Polly generativo leva ~1 a 3 segundos num
#: parágrafo de instrução, e a borda do Amplify corta em 28 — esperar mais que
#: isso é esperar por uma resposta que não vem mais.
TIMEOUT_S = 30.0

#: Quanto dura a URL que a sala recebe. Seis horas, como o banner de fundo e o
#: vídeo do saguão: é o que cobre um encontro com folga sem virar link
#: permanente. Uma aba aberta além disso recarrega a sala.
VALIDADE_S = 6 * 3600


def configurado() -> bool:
    """Há como pedir voz? Sem isto a sala mostra o texto e segue."""
    return bool((settings.voz_core_url or "").strip() and (settings.voz_core_token or "").strip())


def assinar(chave: str) -> str:
    """URL assinada de um objeto de voz, para o `<audio>` tocar."""
    return presigned_url(chave, expires=VALIDADE_S)


def tem(chave: str) -> bool:
    """O áudio deste texto já está no bucket?

    Ausente devolve False; QUALQUER outro erro sobe. Tratar "credencial sem
    permissão" como ausência faria a sala pedir e pagar a mesma síntese em toda
    criação de sala, para sempre, sem nada no log dizendo por quê.
    """
    try:
        s3_client().head_object(Bucket=settings.s3_bucket, Key=chave)
        return True
    except ClientError as exc:
        codigo = str(exc.response.get("Error", {}).get("Code", ""))
        if codigo in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def guardar(chave: str, mp3: bytes) -> None:
    s3_client().put_object(
        Bucket=settings.s3_bucket, Key=chave, Body=mp3, ContentType="audio/mpeg"
    )


async def sintetizar(texto: str, pedido: dict | None = None) -> bytes:
    """Pede ao CoreService o mp3 de um parágrafo, na voz configurada.

    O corpo da resposta É o áudio. O erro traz o código HTTP e um trecho do
    corpo porque os dois modos de falha interessantes são indistinguíveis sem
    eles: 401 é segredo divergente, 503 é motor sem permissão do lado de lá.

    `pedido` são provedor e voz (`encontro.pedido_de_voz`). Omitido, o
    CoreService usa o padrão dele — que é a Camila generativa de sempre, e é o
    que mantém este caminho funcionando contra um CoreService antigo, que ainda
    não conhece os campos novos.
    """
    base = (settings.voz_core_url or "").strip().rstrip("/")
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as cliente:
        r = await cliente.post(
            f"{base}/api/voz/sintetizar",
            json={"texto": texto, **(pedido or {})},
            headers={"X-Voz-Token": (settings.voz_core_token or "").strip()},
        )
    if r.status_code != 200:
        raise RuntimeError(f"CoreService respondeu {r.status_code}: {r.text[:200]}")
    logger.info("[voz] sintetizada pelo core (cache=%s)", r.headers.get("X-Voz-Cache", "?"))
    return r.content


async def garantir_textos(textos: list[str], escolha: dict | None = None) -> dict[str, int]:
    """Sintetiza o que falta destes textos, na voz pedida (ou na configurada).

    Separado de `preparar` porque há dois chamadores com origens diferentes: a
    criação da sala (que parte de um roteiro) e o painel admin, que acabou de
    trocar a voz e quer pagar a síntese AGORA — senão a conta cai na primeira
    sala criada depois, que é justamente quem não devia esperar.

    `escolha` é uma configuração com a chave `voz`, para o painel pedir a voz
    que está NA TELA, ainda não salva. Sem ela vale a salva — que é o que a
    criação de sala precisa, porque a sala toca a voz do encontro, não a de
    quem está mexendo no painel.

    O PERFIL E O PEDIDO SAEM DO MESMO LUGAR, e é a linha que sustenta tudo:
    o perfil é o ENDEREÇO do mp3 e o pedido é o que o CoreService vai gerar.
    Desencontrá-los grava o áudio de uma voz no endereço de outra — e aí o
    erro não se conserta trocando a configuração de volta, porque o objeto
    errado fica no bucket, com a chave certa, para sempre.
    """
    if not configurado():
        logger.info("[voz] VOZ_CORE_URL/VOZ_CORE_TOKEN ausentes: encontro sem audio")
        return {"desligado": 1}
    if not textos:
        return {"pedidos": 0, "prontos": 0, "falhas": 0, "ja_tinha": 0}
    config = escolha or await encontro.carregar()
    pedido = encontro.pedido_de_voz(config)
    contas = await voz.garantir(
        textos, tem=tem,
        sintetizar=lambda t: sintetizar(t, pedido),
        guardar=guardar,
        perfil=encontro.perfil_da_voz(config),
    )
    logger.info("[voz] %s textos (%s): %s", len(textos), pedido.get("voz"), contas)
    return contas


async def preparar(roteiro) -> dict[str, int]:
    """Garante a voz de todos os blocos fixos de um roteiro.

    Chamada quando a sala é CRIADA, e não quando ela é aberta: a criação
    acontece dias antes da aula, e a abertura acontece com os alunos esperando.
    Idempotente — depois da primeira sala, só confere que já existe.
    """
    return await garantir_textos(voz.textos_do_roteiro(roteiro))

"""A sala FALA o encontro, em vez de só mostrá-lo.

É o item "texto + áudio" da facilitação autônoma: o que o facilitador humano
lia em voz alta passa a ser tocado pela própria sala. São duas fontes:

- o texto FIXO das seções ("aponte o smartphone para o QR Code..."), igual em
  todo episódio, falado quando a etapa abre;
- os campos que VARIAM por episódio (sinopse, questões, riscos), falados no
  momento em que cada card é revelado — não antes, senão a sala entregaria a
  resposta da pergunta que o facilitador ainda não fez.

As duas usam o MESMO mecanismo, e é por isso que a segunda não custou desenho
nenhum: a chave do mp3 é o hash do texto, e texto é texto.

## Quem sintetiza não é este serviço

O Polly, a credencial dele e a escolha de voz vivem no CoreService, que produz
o audiodrama das temporadas. A credencial de AWS desta aplicação é
estritamente S3 num bucket só — alargá-la até o Polly criaria uma segunda
implementação de síntese e daria permissão de voz a uma chave que hoje só
escreve gravação. Então aqui se PEDE o mp3 (`POST /api/voz/sintetizar`, com
segredo próprio) e se guarda no bucket DESTA aplicação.

Guardar a cópia local não é zelo: o que a sala precisa é de uma URL que
funcione na hora da aula, e só quem é dono do bucket pode assinar uma nova a
cada carga. Um link assinado vindo do CoreService duraria seis horas, e a sala
é criada semanas antes do encontro — é a mesma razão pela qual `bannerFundo`
guarda a chave, e não a URL.

## A chave é o hash do texto, e é isso que torna tudo idempotente

Os blocos fixos são IGUAIS em todo episódio: são texto do `schema.ts`, não
conteúdo de curador. Um pacote publicado por mês pediria a mesma síntese por
anos. Com a chave saindo do texto:

- a primeira sala paga o Polly, as seguintes não pedem nada;
- mudar uma palavra no roteiro gera uma chave nova — o áudio velho não é
  servido com o texto novo, que é o defeito realmente perigoso aqui (a sala
  dizendo uma coisa e a tela mostrando outra);
- e nada precisa ser gravado no banco: a chave se RECALCULA do texto a cada
  carga da sala. Por isso este item não tem migration.

## O que acontece quando dá errado

Nada audível, e tudo visível no log. Sem `VOZ_CORE_URL`/`VOZ_CORE_TOKEN`
configurados, sem o CoreService no ar ou sem o objeto no bucket, a sala mostra
o texto e segue — a URL assinada de um objeto ausente responde 404 e o
`<audio>` do navegador desiste em silêncio. Um encontro sem voz é um encontro;
um encontro travado esperando o Polly não é.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)

#: Versão da voz. Entra no hash, então BUMPAR INVALIDA TODO O CACHE.
#:
#: Existe porque a voz é escolhida do outro lado (CoreService): se ela mudar
#: lá, os objetos já gravados aqui continuariam sendo servidos com a voz antiga
#: para sempre, e ninguém ligaria o sintoma à mudança. Trocar este número faz a
#: próxima sala pedir tudo de novo.
VERSAO = "1"

#: Prefixo dos objetos no bucket de gravações. Separado para a limpeza de
#: gravação (que apaga por idade) nunca levar a voz junto: a gravação de uma
#: aula envelhece, a instrução do encontro não.
PREFIXO = "voz"


def normalizar(texto: str) -> str:
    """O texto como entra no hash: sem espaço de sobra, quebra virando espaço.

    Sem isto, reindentar o parágrafo no `schema.ts` geraria chave nova e uma
    síntese paga para produzir um áudio idêntico ao que já existe.
    """
    return re.sub(r"\s+", " ", (texto or "").strip())


def chave(texto: str) -> str:
    """Onde o áudio deste texto mora. Função do texto, e de mais nada."""
    digest = hashlib.sha256(f"{VERSAO}|{normalizar(texto)}".encode("utf-8")).hexdigest()
    return f"{PREFIXO}/{digest}.mp3"


#: Campos do roteiro que NÃO viram voz.
#:
#: `bannerFundo` guarda uma chave de bucket, não prosa: mandá-la ao Polly
#: pagaria para o encontro ouvir "banners barra 3f2a ponto png". É o único
#: campo de imagem do `schema.ts`; os demais são texto escrito para ser lido.
#:
#: O que se FALA de fato é decisão da tela, que já decide o que mostrar. Aqui
#: só se garante que o áudio exista — sintetizar um campo que a sala nunca toca
#: custa centavos uma vez; faltar o áudio de um que ela toca é um encontro mudo
#: no meio.
CAMPOS_SEM_VOZ: frozenset[str] = frozenset({"bannerFundo"})


def textos_dos_campos(roteiro: Any) -> list[str]:
    """O conteúdo que VARIA por episódio: sinopse, questões, riscos.

    Aceita string ou lista de strings, que é o formato que o roteiro guarda
    (`_sanitize_roteiro`, no CoreService, descarta qualquer outra coisa).
    """
    if not isinstance(roteiro, dict):
        return []
    campos = roteiro.get("campos")
    if not isinstance(campos, dict):
        return []
    fora: list[str] = []
    for nome, valor in campos.items():
        if nome in CAMPOS_SEM_VOZ:
            continue
        itens = valor if isinstance(valor, list) else [valor]
        for item in itens:
            limpo = normalizar(str(item or ""))
            if limpo:
                fora.append(limpo)
    return fora


def textos_do_roteiro(roteiro: Any) -> list[str]:
    """Tudo que a sala pode precisar falar: texto fixo E campo do episódio.

    Sem repetir — é o que o aquecimento pede ao sintetizador, e cada pedido é
    uma chamada paga.
    """
    vistos: set[str] = set()
    fora: list[str] = []
    for texto in paragrafos_do_roteiro(roteiro) + textos_dos_campos(roteiro):
        if texto not in vistos:
            vistos.add(texto)
            fora.append(texto)
    return fora


def paragrafos_do_roteiro(roteiro: Any) -> list[str]:
    """Todos os parágrafos fixos do roteiro, na ordem, SEM repetir.

    Sem repetir porque o mesmo aviso aparece em mais de uma seção, e pedir duas
    vezes o mesmo texto pagaria o Polly duas vezes pelo mesmo mp3.
    """
    if not isinstance(roteiro, dict):
        return []
    vistos: set[str] = set()
    fora: list[str] = []
    for secao in roteiro.get("secoes") or []:
        if not isinstance(secao, dict):
            continue
        for bloco in secao.get("blocosFixos") or []:
            if not isinstance(bloco, dict):
                continue
            for paragrafo in bloco.get("paragrafos") or []:
                limpo = normalizar(str(paragrafo or ""))
                if limpo and limpo not in vistos:
                    vistos.add(limpo)
                    fora.append(limpo)
    return fora


def com_audios(roteiro: Any, assinar: Callable[[str], str]) -> Any:
    """Acrescenta a cada bloco fixo um `audios` ALINHADO com `paragrafos`.

    O alinhamento é o contrato: `audios[i]` é a voz de `paragrafos[i]`. Um
    parágrafo vazio (o formulário permite) entra como string vazia em vez de
    ser descartado — descartar deslocaria os índices e a sala falaria o
    parágrafo errado, sem erro nenhum na tela.

    `assinar` entra de fora para esta função ser exercitável sem AWS.
    """
    if not isinstance(roteiro, dict):
        return roteiro
    for secao in roteiro.get("secoes") or []:
        if not isinstance(secao, dict):
            continue
        for bloco in secao.get("blocosFixos") or []:
            if not isinstance(bloco, dict):
                continue
            paragrafos = bloco.get("paragrafos")
            if not isinstance(paragrafos, list):
                continue
            audios: list[str] = []
            for paragrafo in paragrafos:
                limpo = normalizar(str(paragrafo or ""))
                if not limpo:
                    audios.append("")
                    continue
                try:
                    audios.append(assinar(chave(limpo)))
                except Exception:   # noqa: BLE001
                    audios.append("")   # voz indisponível não pode quebrar a sala
            bloco["audios"] = audios

    # E a voz dos campos que variam por episódio, num mapa IRMÃO de `campos`.
    #
    # Irmão, e não dentro de `campos`: a tela lê `campos` para exibir, e enfiar
    # URL no meio dos valores faria a sinopse aparecer escrita como link. A
    # forma acompanha a do valor — texto vira texto, lista vira lista do mesmo
    # tamanho, com vazio onde o item é vazio (mesmo alinhamento dos parágrafos).
    campos = roteiro.get("campos")
    if isinstance(campos, dict):
        vozes: dict[str, Any] = {}
        for nome, valor in campos.items():
            if nome in CAMPOS_SEM_VOZ:
                continue
            if isinstance(valor, list):
                vozes[nome] = [_assinar_texto(item, assinar) for item in valor]
            else:
                url = _assinar_texto(valor, assinar)
                if url:
                    vozes[nome] = url
        if vozes:
            roteiro["audiosDosCampos"] = vozes
    return roteiro


def _assinar_texto(valor: Any, assinar: Callable[[str], str]) -> str:
    """A URL da voz de um texto, ou vazio — nunca uma exceção."""
    limpo = normalizar(str(valor or ""))
    if not limpo:
        return ""
    try:
        return assinar(chave(limpo))
    except Exception:   # noqa: BLE001
        return ""


async def garantir(
    paragrafos: Iterable[str],
    *,
    tem: Callable[[str], bool],
    sintetizar: Callable[[str], Awaitable[bytes]],
    guardar: Callable[[str, bytes], None],
) -> dict[str, int]:
    """Sintetiza o que falta, e só o que falta.

    As três portas entram de fora: é o que permite provar a decisão (pedir o
    ausente, não pedir o presente, não pedir duas vezes o mesmo texto, seguir
    depois de uma falha) sem Polly, sem bucket e sem rede.

    Uma falha num parágrafo NÃO interrompe os outros: um aviso sem voz é melhor
    que um encontro em que a voz parou no terceiro parágrafo porque o quarto
    falhou.
    """
    contas = {"pedidos": 0, "prontos": 0, "falhas": 0, "ja_tinha": 0}
    feitos: set[str] = set()
    for texto in paragrafos:
        limpo = normalizar(texto)
        if not limpo or limpo in feitos:
            continue
        feitos.add(limpo)
        alvo = chave(limpo)
        try:
            if tem(alvo):
                contas["ja_tinha"] += 1
                continue
            contas["pedidos"] += 1
            mp3 = await sintetizar(limpo)
            if not mp3:
                raise RuntimeError("o sintetizador devolveu vazio")
            guardar(alvo, mp3)
            contas["prontos"] += 1
        except Exception as exc:   # noqa: BLE001
            contas["falhas"] += 1
            logger.error("[voz] %s: %s", alvo, exc)
    return contas

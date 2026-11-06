# -*- coding: utf-8 -*-
"""O TEMPLATE do encontro: quanto dura cada etapa, o que a sala diz e com que voz.

Até aqui essas três coisas viviam em três repositórios e nenhuma delas podia ser
ajustada sem deploy:

| o quê | morava em | para mudar |
|---|---|---|
| duração de cada etapa | `services/cadencia.py` (constante) | deploy da webconf |
| texto fixo que a sala mostra e FALA | `schema.ts` do CustomerApp | deploy do CustomerApp |
| a voz que lê | `routers/voz.py` do CoreService (`VOZ = "Camila"`) | deploy do CoreService |

Este módulo é o lugar único onde elas passam a ser CONFIGURAÇÃO. O painel admin
lê e grava daqui (`routers/encontro.py`), e os três consumidores de hoje — a
cadência, o retrato da sala e a síntese de voz — passam a perguntar aqui em vez
de ler a constante.

## O que vale na hora e o que congela

**Temporizadores e voz valem na hora**, inclusive para sala já aberta: a duração
é lida a cada avaliação da cadência, e a voz entra na chave do mp3, que é
recalculada a cada carga da sala.

**Os textos congelam na criação da sala**, que é o comportamento que o
`roteiro` (migration 017) já tinha e existe por uma razão: uma edição no meio da
sessão mudaria a tela dos alunos no meio de uma leitura. `aplicar_no_roteiro` é
chamada quando a sala é CRIADA, e o que ela grava é o retrato.

## Por que o texto fixo passa a ser daqui, e não do `schema.ts`

O `schema.ts` é do CustomerApp, onde o CURADOR preenche o episódio. Os blocos
fixos nunca foram conteúdo de curador: são a instrução da plataforma ("aponte o
smartphone para o QR Code..."), igual em todo episódio, que viajava de carona no
retrato porque não havia outro caminho. Quem precisa ajustá-los é quem opera o
encontro, e é por isso que eles vêm para o lado em que a sala vive.

`SECOES_BASE` abaixo é a transcrição do que o `schema.ts` tem hoje, e é a
SEMENTE: ela só é usada enquanto ninguém salvou nada. A partir do primeiro
salvamento, o `blocosFixos` que vem no retrato do CustomerApp é SUBSTITUÍDO
(`aplicar_no_roteiro`) — duas fontes para o mesmo texto fariam a tela mostrar
uma coisa e esta tela de configuração prometer outra.

## E as pausas

Pausa é um NÚMERO ao lado do parágrafo, não silêncio sintetizado. É o que a
torna ajustável de graça: mudar de 500 ms para 2 s não refaz áudio nenhum, não
muda chave nenhuma e não custa nada ao ElevenLabs. `pausas[i]` é o silêncio
DEPOIS de `paragrafos[i]`, no mesmo alinhamento por índice que `audios[i]` já
usa — o alinhamento é o contrato (ver `services/voz.py`).

## Inerte sem a tabela

Publicar não aplica migration (ver `db.tem_tabela`). Sem a tabela
`encontro_template`, tudo aqui devolve a base — que é exatamente o
comportamento de hoje — e a tela de configuração mostra os valores em modo de
leitura dizendo o que falta. `garantir_tabela` tenta criá-la na subida, o que
dispensa a migration manual no caso normal, mas não é condição para nada
funcionar.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Any

from ..db import pool, tem_tabela
from . import cadencia

logger = logging.getLogger(__name__)

TABELA = "encontro_template"

#: Quanto a configuração carregada vale antes de ser relida.
#:
#: A cadência é avaliada no polling de TODO MUNDO que está na aula, e a duração
#: da etapa é lida em cada avaliação. Sem cache isso seria uma consulta por
#: participante por segundo para ler uma linha que muda uma vez por mês.
#:
#: Vinte segundos é o teto do atraso entre salvar no painel e a sala obedecer —
#: e `salvar` invalida na hora, então o atraso só acontece entre processos
#: diferentes (há mais de um worker).
TTL_S = 20.0


# ── O CATÁLOGO DE ETAPAS ────────────────────────────────────────────────────
#
# A ordem NÃO está escrita aqui: ela vem de `cadencia.ORDEM`, e este catálogo é
# conferido contra ela. Era o começo da história que custou caro — a lista de
# etapas em três arquivos que não se importavam, e a tela divergindo em silêncio
# (ver `provas/prova_cadencia.py`).
#
# `titulo` e `acao` são os mesmos de `STEPS` no `VideoRoom.tsx`, e `secao` é o
# mesmo mapa de `secaoDaEtapa`. Repetidos aqui porque o backend não lê o
# frontend, e amarrados por `provas/prova_template_do_encontro.py`, que falha se
# qualquer um dos três divergir.
#
# `blocos` reparte a seção da plenária entre duas etapas, como a tela faz:
#   `todos`    — a seção inteira
#   `primeiro` — só o 1º bloco (o objetivo da discussão)
#   `demais`   — do 2º em diante (a dinâmica das questões)
CATALOGO: dict[str, dict[str, Any]] = {
    "session_start":      {"titulo": "Abertura",                 "acao": "Iniciar a sessão",
                           "secao": None,          "blocos": "todos"},
    "registration_open":  {"titulo": "Registro de Presença",     "acao": "Iniciar o registro",
                           "secao": "abertura",    "blocos": "todos"},
    "amplify_code":       {"titulo": "Registro de Presença",     "acao": "Ampliar o código da sessão",
                           "secao": "abertura",    "blocos": "todos"},
    "registration_close": {"titulo": "Registro de Presença",     "acao": "Encerrar o registro",
                           "secao": "abertura",    "blocos": "todos"},
    "synopsis":           {"titulo": "Situação-problema",        "acao": "Revisitar a situação-problema",
                           "secao": "revisitando", "blocos": "todos"},
    "groups":             {"titulo": "Aquecimento",              "acao": "Divisão em grupos",
                           "secao": "aquecimento", "blocos": "todos"},
    "plenary":            {"titulo": "Discussão em Plenária",    "acao": "Discussão em plenária",
                           "secao": "plenaria",    "blocos": "primeiro"},
    "question":           {"titulo": "Discussão em Plenária",    "acao": "Questões para reflexão",
                           "secao": "plenaria",    "blocos": "demais"},
    "situational":        {"titulo": "Análise situacional",      "acao": "Análise situacional",
                           "secao": "analise",     "blocos": "todos"},
    "release_risks":      {"titulo": "Análise situacional",      "acao": "Liberar análise individual de riscos",
                           "secao": "analise",     "blocos": "todos"},
    "show_chart":         {"titulo": "Análise situacional",      "acao": "Mostrar gráfico",
                           "secao": None,          "blocos": "todos"},
    "closing":            {"titulo": "Análise situacional",      "acao": "Encerramento",
                           "secao": None,          "blocos": "todos"},
    "release_feedback":   {"titulo": "Feedback e encerramento",  "acao": "Liberar feedback de interação",
                           "secao": "feedback",    "blocos": "todos"},
    "done":               {"titulo": "Encerramento",             "acao": "Encerrar a sala",
                           "secao": "feedback",    "blocos": "todos"},
}


# ── AS SEÇÕES: TEXTO FIXO E OS LUGARES DO ROTEIRO ───────────────────────────
#
# `campos` NÃO guarda conteúdo de episódio: guarda o LUGAR dele. É o que a tela
# de configuração mostra como "Questão 1, 2, 3" — quem opera o encontro precisa
# saber onde a informação do roteiro entra, e não qual é a informação deste
# episódio (que muda a cada semana e já é editada no CustomerApp).
#
# Os campos marcados `somenteModelo` no `schema.ts` (curadoria, tarefa técnica,
# dificuldade não técnica) não estão aqui: eles existem no template do documento
# e nunca chegam à tela da videoconferência.
SECOES_BASE: list[dict[str, Any]] = [
    {
        "key": "abertura",
        "titulo": "Abertura e registro",
        "blocos": [
            {
                "titulo": "Registro de Presença",
                "lista": False,
                "paragrafos": [
                    "Aponte o smartphone para o QR Code na tela para acessar a aplicação deste encontro.",
                    "Para registrar a sua presença, digite o class code no chat de interação da aplicação.",
                ],
            },
            {
                "titulo": "Importante!",
                "lista": False,
                "paragrafos": [
                    "Caso o participante não disponha de um smartphone ou de acesso à internet, NÃO será possível a sua interação com os demais participantes.",
                    'Neste caso, somente poderá acompanhar as atividades do encontro como "participante ouvinte".',
                ],
            },
        ],
        "campos": [
            {"name": "serieTemporada", "label": "Série e temporada", "tipo": "texto"},
            {"name": "tituloEpisodio", "label": "Título do episódio", "tipo": "texto"},
            {"name": "marcaSerie", "label": "Assinatura da série", "tipo": "texto"},
            {"name": "direitos", "label": "Aviso de direitos", "tipo": "texto"},
            {"name": "bannerFundo", "label": "Banner de fundo", "tipo": "imagem"},
        ],
    },
    {
        "key": "revisitando",
        "titulo": "Revisitando a situação-problema",
        "blocos": [],
        "campos": [
            {"name": "sinopseParte1", "label": "Sinopse — card 1/2", "tipo": "textarea"},
            {"name": "sinopseParte2", "label": "Sinopse — card 2/2", "tipo": "textarea"},
        ],
    },
    {
        "key": "aquecimento",
        "titulo": "Aquecimento",
        "blocos": [
            {
                "titulo": "",
                "lista": False,
                "paragrafos": [
                    "Os participantes serão divididos em grupos de até 5 integrantes para ouvirem as propostas sugeridas por seus pares e refletirem sobre seus argumentos.",
                    "Estabeleçam uma sequência de exposições, até que todos tenham oportunidade de apresentar seus pontos de vista.",
                ],
            },
        ],
        "campos": [
            {"name": "questoesOrientadoras", "label": "Questões orientadoras", "tipo": "lista",
             "rotuloItem": "Questão", "itensPrevistos": 3},
        ],
    },
    {
        "key": "plenaria",
        "titulo": "Discussão em Plenária",
        "blocos": [
            {
                "titulo": "",
                "lista": False,
                "paragrafos": [
                    "O objetivo da discussão em plenária é a apresentação e a contra argumentação das ideias relativas à situação-problema abordada no episódio.",
                    "Os participantes do encontro devem postar-se de tal forma que, cada participante possa interagir com todos os demais.",
                ],
            },
            {
                "titulo": "",
                "lista": False,
                "paragrafos": [
                    "A dinâmica das discussões será orientada por uma sequência de questões.",
                    "Cada questão deverá ser dirigida à um participante, cuja resposta servirá de argumentação base para observações posteriores dos demais participantes.",
                ],
            },
        ],
        "campos": [
            {"name": "relembrandoEpisodio", "label": "Relembrando o episódio", "tipo": "textarea"},
            {"name": "questoesPlenaria", "label": "Questões para reflexão", "tipo": "lista",
             "rotuloItem": "Questão", "itensPrevistos": 5},
        ],
    },
    {
        "key": "analise",
        "titulo": "Análise Situacional",
        "blocos": [
            {
                "titulo": "",
                "lista": False,
                "paragrafos": [
                    "Cada participante irá sintetizar a sua análise sobre as possíveis ações diante da situação-problema abordada no episódio.",
                    "Considere os argumentos apresentados por seus pares de profissão na discussão plenária além de suas próprias reflexões.",
                ],
            },
            {
                "titulo": "",
                "lista": False,
                "paragrafos": [
                    "Os participantes deverão avaliar os principais riscos envolvidos nas possíveis ações discutidas no encontro.",
                    "Serão questionados, separadamente, os critérios de:",
                ],
            },
            {
                "titulo": "",
                "lista": True,
                "paragrafos": [
                    "Probabilidade (chances do risco avaliado ocorrer)",
                    "Impacto (consequência resultante, caso o risco avaliado ocorra)",
                ],
            },
            {
                "titulo": "",
                "lista": False,
                "paragrafos": [
                    "A seguir, os cinco principais riscos abordados na discussão em plenária que deverão ser avaliados pelos participantes.",
                ],
            },
        ],
        "campos": [
            {"name": "riscos", "label": "Principais riscos", "tipo": "lista",
             "rotuloItem": "Risco", "itensPrevistos": 5},
        ],
    },
    {
        "key": "feedback",
        "titulo": "Feedback da interação",
        "blocos": [
            {
                "titulo": "",
                "lista": False,
                "paragrafos": [
                    "Uma equipe de desempenho superior é composta por profissionais com habilidades complementares.",
                    "Portanto, saber em quais habilidades nos destacamos é uma informação chave para a busca de um desempenho profissional de excelência.",
                    "Nesta atividade, os participantes deverão compartilhar suas percepções sobre a interação com os integrantes do seu grupo.",
                ],
            },
            {
                "titulo": "Importante!",
                "lista": False,
                "paragrafos": [
                    "Este exercício não identifica ou registra opiniões isoladas.",
                ],
            },
        ],
        "campos": [],
    },
]

#: A voz de hoje, escrita como configuração.
#:
#: Camila generativa do Polly é o que o CoreService tem embutido em
#: `routers/voz.py`. Ela continua sendo o padrão: trocar o motor de todo mundo
#: por omissão seria mudar o som de todos os encontros num deploy.
VOZ_PADRAO: dict[str, Any] = {
    "provedor": "polly",
    "voz": "Camila",
    "motor": "generative",
    "rotulo": "Camila — Polly generativa (pt-BR)",
}

#: Pausa sugerida depois de cada parágrafo, em ms, quando ninguém configurou
#: nada. ZERO: é o comportamento de hoje (um `<audio>` emendado no outro), e
#: inventar um silêncio no mesmo deploy que torna a pausa configurável mudaria o
#: ritmo de todos os encontros sem ninguém ter pedido.
PAUSA_PADRAO = 0

#: Tetos da validação. Não são gosto: são o que separa "ajustar o ritmo" de
#: "quebrar o encontro". Duração zero faria a etapa vencer no instante em que
#: começa, e a sala atravessaria o encontro inteiro em um segundo.
MIN_DURACAO, MAX_DURACAO = 10, 7200          # 10 s a 2 h por etapa
MIN_PAUSA, MAX_PAUSA = 0, 30000              # até 30 s de silêncio entre falas
MIN_JANELA, MAX_JANELA = 5, 300              # a janela do voto
MIN_TOLERANCIA, MAX_TOLERANCIA = 10, 3600    # o empurrão quando o voto não passa


def base() -> dict[str, Any]:
    """A configuração de fábrica: o comportamento de hoje, escrito como dados.

    As durações e os parâmetros do voto são LIDOS de `cadencia`, não copiados:
    uma segunda tabela de durações divergiria da primeira no dia em que alguém
    ajustasse o ritmo pelo código — e a tela passaria a prometer um tempo que a
    cadência não cumpre.
    """
    return {
        "duracoes": dict(cadencia.DURACAO_DA_ETAPA),
        "janela_voto_s": int(cadencia.JANELA_DO_VOTO.total_seconds()),
        "tolerancia_s": int(cadencia.TOLERANCIA.total_seconds()),
        "limiar": float(cadencia.LIMIAR_DE_AVANCO),
        "voz": dict(VOZ_PADRAO),
        "secoes": [
            {
                "key": s["key"],
                "blocos": [
                    {
                        "titulo": b.get("titulo") or "",
                        "lista": bool(b.get("lista")),
                        "paragrafos": list(b["paragrafos"]),
                        "pausas": [PAUSA_PADRAO] * len(b["paragrafos"]),
                    }
                    for b in s["blocos"]
                ],
            }
            for s in SECOES_BASE
        ],
    }


# ── VALIDAÇÃO ───────────────────────────────────────────────────────────────

def _inteiro(valor: Any, piso: int, teto: int, padrao: int) -> int:
    try:
        n = int(float(valor))
    except (TypeError, ValueError):
        return padrao
    return max(piso, min(teto, n))


def normalizar(entrada: Any) -> dict[str, Any]:
    """O que veio da tela, podado ao que o encontro aceita.

    Poda em vez de recusar, e isto é deliberado: o painel é a única forma de
    ajustar o ritmo, e um 422 por causa de um campo mal digitado deixaria quem
    opera sem saída. O que não serve volta ao padrão, e a tela mostra o valor
    efetivo depois de salvar.

    Duas regras que não são negociáveis:

    - **etapa fora do vocabulário é descartada.** Gravar uma chave que
      `cadencia.ORDEM` não conhece criaria uma duração que ninguém lê, e a
      próxima pessoa a abrir a tela acharia que configurou algo.
    - **`pausas` tem o tamanho de `paragrafos`.** É o mesmo contrato de
      `audios[i]`: desalinhar faz a sala calar no lugar errado, sem erro nenhum.
    """
    padrao = base()
    if not isinstance(entrada, dict):
        return padrao

    duracoes: dict[str, int | None] = {}
    das_entradas = entrada.get("duracoes") if isinstance(entrada.get("duracoes"), dict) else {}
    for etapa in cadencia.ORDEM:
        bruto = das_entradas.get(etapa, padrao["duracoes"].get(etapa))
        if bruto is None or bruto == "":
            duracoes[etapa] = None      # etapa sem relógio (hoje só `done`)
            continue
        duracoes[etapa] = _inteiro(bruto, MIN_DURACAO, MAX_DURACAO,
                                   padrao["duracoes"].get(etapa) or MIN_DURACAO)

    try:
        limiar = float(entrada.get("limiar", padrao["limiar"]))
    except (TypeError, ValueError):
        limiar = padrao["limiar"]
    # 0,95 e não 1,0: com limiar 1 e comparação estrita NENHUMA sala avança,
    # nem com a turma inteira votando sim — e o sintoma seria um encontro
    # parado sem nada no log.
    limiar = max(0.0, min(0.95, limiar))

    voz_bruta = entrada.get("voz") if isinstance(entrada.get("voz"), dict) else {}
    provedor = str(voz_bruta.get("provedor") or "").strip().lower()
    if provedor not in ("polly", "elevenlabs"):
        provedor = VOZ_PADRAO["provedor"]
    voz_id = str(voz_bruta.get("voz") or "").strip() or VOZ_PADRAO["voz"]
    voz = {
        "provedor": provedor,
        "voz": voz_id,
        # O motor só existe no Polly (`generative`/`neural`); no ElevenLabs o
        # modelo é escolhido do lado de lá, por isso aqui fica vazio em vez de
        # inventar um valor que o outro serviço ignoraria.
        "motor": (str(voz_bruta.get("motor") or VOZ_PADRAO["motor"]).strip()
                  if provedor == "polly" else ""),
        "rotulo": str(voz_bruta.get("rotulo") or "").strip()[:120] or voz_id,
    }

    por_chave = {s.get("key"): s for s in (entrada.get("secoes") or [])
                 if isinstance(s, dict)}
    secoes: list[dict[str, Any]] = []
    for molde in padrao["secoes"]:
        vinda = por_chave.get(molde["key"])
        if not isinstance(vinda, dict) or not isinstance(vinda.get("blocos"), list):
            secoes.append(molde)
            continue
        blocos = []
        for b in vinda["blocos"]:
            if not isinstance(b, dict):
                continue
            paragrafos = [str(p or "").strip() for p in (b.get("paragrafos") or [])
                          if isinstance(p, (str, int, float))]
            paragrafos = [p for p in paragrafos if p]
            if not paragrafos:
                continue        # bloco vazio não é bloco: a tela desenharia uma caixa muda
            pausas_vindas = b.get("pausas") if isinstance(b.get("pausas"), list) else []
            blocos.append({
                "titulo": str(b.get("titulo") or "").strip()[:120],
                "lista": bool(b.get("lista")),
                "paragrafos": paragrafos,
                # Pelo ÍNDICE do parágrafo, e completado até o fim: é o que
                # garante `len(pausas) == len(paragrafos)` mesmo quando a tela
                # manda uma lista curta (parágrafo acrescentado no fim).
                "pausas": [_inteiro(pausas_vindas[i] if i < len(pausas_vindas) else PAUSA_PADRAO,
                                    MIN_PAUSA, MAX_PAUSA, PAUSA_PADRAO)
                           for i in range(len(paragrafos))],
            })
        secoes.append({"key": molde["key"], "blocos": blocos})

    return {
        "duracoes": duracoes,
        "janela_voto_s": _inteiro(entrada.get("janela_voto_s"), MIN_JANELA, MAX_JANELA,
                                  padrao["janela_voto_s"]),
        "tolerancia_s": _inteiro(entrada.get("tolerancia_s"), MIN_TOLERANCIA, MAX_TOLERANCIA,
                                 padrao["tolerancia_s"]),
        "limiar": limiar,
        "voz": voz,
        "secoes": secoes,
    }


# ── PERSISTÊNCIA ────────────────────────────────────────────────────────────

_CACHE: dict[str, Any] | None = None
_CACHE_EM: float = 0.0
_TEM_TABELA: bool | None = None


async def garantir_tabela() -> bool:
    """Cria a tabela se ela não existir. Chamada na subida.

    Existe porque **publicar não aplica migration** neste repositório: o
    `schema.sql` só roda com o diretório de dados vazio, e a 013 passou meses
    sem ser aplicada em produção enquanto o código já contava com ela. Uma
    tabela NOVA e vazia é o caso em que criar na subida não tem risco nenhum —
    nada a migrar, nada a perder.

    Falha não derruba a subida: sem a tabela o template é a base, que é o
    comportamento de hoje.
    """
    global _TEM_TABELA
    try:
        await pool().execute(f"""
            CREATE TABLE IF NOT EXISTS {TABELA} (
              id         INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
              dados      JSONB NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_by TEXT
            )
        """)
        _TEM_TABELA = True
        return True
    except Exception:
        logger.exception("[encontro] nao consegui garantir a tabela %s", TABELA)
        _TEM_TABELA = None
        return False


async def carregar(*, forcar: bool = False) -> dict[str, Any]:
    """A configuração corrente, completa. Nunca levanta, nunca devolve parcial.

    Completa é o ponto: quem chama não precisa saber se a linha existe, se ela
    foi salva antes de uma etapa nova aparecer no código, ou se o banco está
    sem a tabela. `normalizar` preenche o que falta com a base, então uma etapa
    acrescentada ao `ORDEM` nasce com a duração do código mesmo havendo
    configuração salva de antes.
    """
    global _CACHE, _CACHE_EM, _TEM_TABELA
    agora = time.monotonic()
    if _CACHE is not None and not forcar and agora - _CACHE_EM < TTL_S:
        return _CACHE
    dados: Any = None
    try:
        if _TEM_TABELA is None:
            _TEM_TABELA = await tem_tabela(TABELA)
        if _TEM_TABELA:
            bruto = await pool().fetchval(f"SELECT dados FROM {TABELA} WHERE id=1")
            dados = json.loads(bruto) if isinstance(bruto, str) else bruto
    except Exception:
        logger.exception("[encontro] falha ao ler %s; usando a base", TABELA)
        dados = None
    _CACHE = normalizar(dados) if dados else base()
    _CACHE_EM = agora
    return _CACHE


def atuais() -> dict[str, Any]:
    """A última configuração lida, SEM ir ao banco.

    Existe para os caminhos sincronizados — `_fim_da_etapa` monta a resposta de
    estado e não pode virar `async` só por isto. Antes da primeira leitura
    devolve a base, que é o comportamento de hoje: o pior caso é uma contagem
    na tela com a duração de fábrica por alguns segundos depois de subir.
    """
    return _CACHE if _CACHE is not None else base()


async def salvar(dados: Any, *, por: str = "") -> dict[str, Any]:
    """Grava a configuração e devolve o que de fato ficou valendo.

    Devolve o normalizado, e não o que chegou: a tela precisa mostrar o valor
    efetivo. Um limiar de 3,0 podado para 0,95 em silêncio faria quem operou
    acreditar que configurou uma coisa que não existe.
    """
    global _CACHE, _CACHE_EM
    limpo = normalizar(dados)
    if not await tem_tabela(TABELA) and not await garantir_tabela():
        raise RuntimeError(
            f"a tabela {TABELA} não existe neste banco (migration 023 não aplicada)")
    await pool().execute(
        f"INSERT INTO {TABELA} (id, dados, updated_at, updated_by) "
        f"VALUES (1, $1::jsonb, now(), $2) "
        f"ON CONFLICT (id) DO UPDATE SET dados=$1::jsonb, updated_at=now(), updated_by=$2",
        json.dumps(limpo, ensure_ascii=False), por or None)
    _CACHE, _CACHE_EM = limpo, time.monotonic()
    return limpo


# ── O QUE OS CONSUMIDORES PEDEM ─────────────────────────────────────────────

def parametros(config: dict[str, Any] | None = None) -> cadencia.Parametros:
    """A configuração como a cadência a consome.

    Converte uma vez, aqui, em vez de deixar cada chamador remontar segundos em
    `timedelta`: a regra é pura e recebe o que precisa pronto.
    """
    c = config or atuais()
    return cadencia.Parametros(
        duracoes=c["duracoes"],
        janela_voto=timedelta(seconds=c["janela_voto_s"]),
        tolerancia=timedelta(seconds=c["tolerancia_s"]),
        limiar=c["limiar"],
    )


def perfil_da_voz(config: dict[str, Any] | None = None) -> str:
    """A identidade da voz, como ela entra na CHAVE do mp3.

    Sem isto, trocar a voz no painel serviria para sempre o áudio da voz velha:
    a chave é o hash do texto, e texto igual com voz diferente daria a mesma
    chave. O sintoma seria a configuração "não funcionar" — o mais difícil de
    diagnosticar, porque nada erra.
    """
    v = (config or atuais()).get("voz") or VOZ_PADRAO
    partes = [str(v.get("provedor") or ""), str(v.get("voz") or "")]
    if v.get("motor"):
        partes.append(str(v["motor"]))
    return ":".join(p for p in partes if p)


def escolha_de_voz(bruta: Any, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Uma voz pedida de fora, validada, pronta para virar perfil e pedido.

    O painel age sobre a voz que está NA TELA, que pode não estar salva — foi
    exatamente a confusão que apareceu em produção: trocar a voz, mandar
    sintetizar e ouvir a voz antiga, porque os dois botões liam a configuração
    salva enquanto os TEXTOS vinham da tela. Metade honrando a tela e metade
    não é pior que nenhuma das duas.

    Passa pela MESMA validação da configuração salva (`normalizar`): um
    provedor inventado vindo do corpo da requisição não pode virar endereço de
    bucket, senão um pedido malformado grava áudio num lugar que nada mais
    encontra.

    Vazio devolve a configuração corrente — o padrão de quem não pediu nada.
    """
    if not isinstance(bruta, dict) or not (bruta.get("voz") or bruta.get("provedor")):
        return config or atuais()
    return {"voz": normalizar({"voz": bruta})["voz"]}


def pedido_de_voz(config: dict[str, Any] | None = None) -> dict[str, str]:
    """O que vai no corpo do `POST /api/voz/sintetizar` do CoreService."""
    v = (config or atuais()).get("voz") or VOZ_PADRAO
    pedido = {"provedor": str(v.get("provedor") or "polly"),
              "voz": str(v.get("voz") or "")}
    if v.get("motor"):
        pedido["motor"] = str(v["motor"])
    return pedido


def blocos_da_etapa(etapa: str, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Os blocos de texto fixo que esta etapa mostra e FALA.

    Mesma repartição que `blocosDaEtapa` no `VideoRoom.tsx` — a seção da
    plenária vale para duas etapas, com o 1º bloco numa e o resto na outra.
    """
    cat = CATALOGO.get(etapa)
    if not cat or not cat["secao"]:
        return []
    secao = next((s for s in (config or atuais())["secoes"] if s["key"] == cat["secao"]), None)
    if not secao:
        return []
    blocos = secao["blocos"]
    if cat["blocos"] == "primeiro":
        return blocos[:1]
    if cat["blocos"] == "demais":
        return blocos[1:]
    return blocos


def aplicar_no_roteiro(roteiro: Any, config: dict[str, Any] | None = None) -> Any:
    """Põe o texto fixo CONFIGURADO no retrato que a sala vai guardar.

    Chamada na CRIAÇÃO da sala, e é isso que faz os textos congelarem: editar o
    template depois não mexe em sala nenhuma que já exista — a mesma garantia
    que o `roteiro` do episódio tem desde a migration 017.

    Substitui `blocosFixos` da seção inteira em vez de casar bloco a bloco: o
    painel pode ter acrescentado ou removido um bloco, e um merge por índice
    deixaria sobra do texto antigo no fim da seção.

    O que NÃO se toca: `campos` e `audiosDosCampos`, que são o conteúdo do
    episódio. Aqui só entra o texto da plataforma.
    """
    if not isinstance(roteiro, dict):
        return roteiro
    c = config or atuais()
    por_chave = {s["key"]: s for s in c["secoes"]}
    for secao in roteiro.get("secoes") or []:
        if not isinstance(secao, dict):
            continue
        nova = por_chave.get(secao.get("key"))
        if nova is None:
            continue
        secao["blocosFixos"] = [
            {"titulo": b["titulo"], "lista": b["lista"],
             "paragrafos": list(b["paragrafos"]), "pausas": list(b["pausas"])}
            for b in nova["blocos"]
        ]
    return roteiro


def catalogo_para_tela(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """O catálogo como a tela de configuração o mostra, na ordem do encontro.

    Sai de `cadencia.ORDEM` (a ordem de verdade) cruzado com o catálogo, e traz
    de cada etapa: o que ela dura, se a turma vota para sair dela, qual seção do
    roteiro ela usa e quais LUGARES do roteiro aparecem nela.
    """
    c = config or atuais()
    fora: list[dict[str, Any]] = []
    for etapa in cadencia.ORDEM:
        cat = CATALOGO.get(etapa, {})
        secao = cat.get("secao")
        campos = next((s["campos"] for s in SECOES_BASE if s["key"] == secao), []) if secao else []
        fora.append({
            "id": etapa,
            "titulo": cat.get("titulo", etapa),
            "acao": cat.get("acao", ""),
            "duracao_s": c["duracoes"].get(etapa),
            # Vota quem não está na abertura e tem relógio: é a mesma condição
            # que `decidir` aplica, derivada de `AVANCA_SOZINHA` em vez de
            # escrita de novo aqui.
            "vota": etapa not in cadencia.AVANCA_SOZINHA and etapa != "done"
                    and c["duracoes"].get(etapa) is not None,
            "secao": secao,
            "secao_titulo": next((s["titulo"] for s in SECOES_BASE if s["key"] == secao), "")
                            if secao else "",
            "blocos": cat.get("blocos", "todos"),
            "textos": blocos_da_etapa(etapa, c),
            "campos": campos,
        })
    return fora

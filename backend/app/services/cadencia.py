# -*- coding: utf-8 -*-
"""A cadência do encontro: quando a sala avança de etapa sozinha.

Esta é a peça que substitui a pessoa que dizia "vamos seguir". Por isso ela é
uma função PURA, separada do banco e da sala: a regra pode ser exercitada com
relógio de mentira e uma lista de nomes, e `provas/prova_cadencia.py` roda os
casos de borda que numa aula ao vivo acontecem uma vez a cada vinte turmas.

## A regra, como o produto a define

Cada etapa tem uma duração. Quando ela se esgota, a sala NÃO avança: ela
pergunta à turma se pode prosseguir, e dá 15 segundos para responder. Avança se
a MAIORIA disser que sim. **Quem não vota tem o voto contado como "não".**

Essa última parte é deliberada e tem consequência: um aluno com a aba em
segundo plano empurra o encontro para ficar onde está. É o viés certo para um
facilitador que não é gente -- ele erra para o lado de dar mais tempo, nunca
para o lado de cortar alguém no meio.

Quando a maioria diz não (ou simplesmente não vota), a etapa ganha mais um
período e a pergunta volta depois. Não há limite de rodadas: quem tem de
desempatar um encontro que não anda é o host, assumindo o modo manual.

## Modo manual tem precedência sobre tudo

Com `auto` desligado a função devolve "nada" sempre -- nem abre voto, nem
avança. O host continua com os comandos que sempre teve. É o que permite
assumir o controle quando a automação vai mal, sem precisar de um deploy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: Quanto dura cada etapa antes de a sala perguntar se pode seguir.
#:
#: São valores de PRODUTO, não constantes técnicas: quem for ajustar o ritmo de
#: um encontro mexe aqui. Ficam todos num lugar só para que a soma seja legível
#: -- um encontro inteiro é a soma desta tabela mais o que a turma demorar a
#: votar.
#:
#: As etapas de comando do host (abrir registro, ampliar código) têm duração
#: `None`: elas dependem de uma ação humana ou externa, e um relógio correndo
#: sobre elas apenas abriria votos que ninguém entende.
DURACAO_DA_ETAPA: dict[str, int | None] = {
    "session_start":      None,   # o host inicia
    "registration_open":  None,   # espera os alunos entrarem
    "amplify_code":       None,   # ação do host
    "registration_close": None,   # ação do host
    "synopsis":           300,    # 5 min revisitando a situação-problema
    "groups":             900,    # 15 min de aquecimento em grupo
    "plenary":            300,
    "question":           420,    # 7 min por questão de reflexão
    "situational":        600,
    "release_risks":      600,    # responder o questionário de riscos
    "show_chart":         300,
    "closing":            180,
    "release_feedback":   600,    # avaliação de pares
    "done":               None,
}

#: A ordem em que a sala avança sozinha. É a mesma de `_STAGES` no router, e
#: está repetida aqui de propósito: esta função é pura e não importa o router.
#: `prova_cadencia.py` confere que as duas listas não divergiram.
ORDEM: tuple[str, ...] = (
    "session_start", "registration_open", "amplify_code", "registration_close",
    "synopsis", "groups", "plenary", "question", "situational",
    "release_risks", "show_chart", "closing", "release_feedback", "done",
)

#: Quanto tempo a turma tem para responder "pode seguir?".
JANELA_DO_VOTO = timedelta(seconds=15)

#: Quanto a etapa ganha quando o voto não passa. Mais curto que a duração
#: original: a turma já teve o período inteiro, e o que falta é um empurrão,
#: não outra rodada completa.
TOLERANCIA = timedelta(seconds=120)


@dataclass(frozen=True)
class Estado:
    """O que a sala sabe sobre a etapa corrente."""

    stage: str
    auto: bool
    #: Quando a etapa corrente começou. `None` = nunca marcado (sala antiga, ou
    #: etapa posta à mão antes de a cadência existir) — e aí não se inventa um
    #: começo: sem ele a função não abre voto nenhum.
    comecou_em: datetime | None = None
    #: Quando a janela do voto fecha. `None` = não há voto aberto.
    voto_fecha_em: datetime | None = None
    #: A etapa que estava correndo quando o voto abriu. Protege contra o host
    #: mudar a etapa à mão no meio de uma votação: o voto deixa de valer.
    voto_da_etapa: str | None = None
    #: `{identidade: True|False}`. Só de quem votou.
    votos: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Decisao:
    """O que a sala deve fazer agora.

    `acao` é uma de:
      `nada`        — seguir como está
      `abrir_voto`  — perguntar à turma se pode prosseguir
      `avancar`     — ir para `proxima`
      `estender`    — o voto não passou; a etapa ganha mais tempo
    """

    acao: str
    proxima: str | None = None
    voto_fecha_em: datetime | None = None
    #: Para o log e para a tela do host: por que esta decisão.
    porque: str = ""
    sim: int = 0
    total: int = 0


def proxima_etapa(stage: str) -> str | None:
    """A etapa seguinte, ou `None` se não há para onde ir."""
    try:
        i = ORDEM.index(stage)
    except ValueError:
        return None
    return ORDEM[i + 1] if i + 1 < len(ORDEM) else None


def apurar(votos: dict[str, bool], presentes: list[str]) -> tuple[int, int]:
    """(sins, total). Quem não votou conta como "não" — ver a docstring.

    Só os PRESENTES entram na conta: o voto de quem já saiu da sala não pode
    decidir o ritmo de quem ficou, nem para um lado nem para o outro.
    """
    presentes_unicos = list(dict.fromkeys(presentes))
    sins = sum(1 for p in presentes_unicos if votos.get(p) is True)
    return sins, len(presentes_unicos)


def maioria(sim: int, total: int) -> bool:
    """Maioria ESTRITA dos presentes.

    Empate não avança: com 2 de 4 o encontro fica. Metade da turma dizendo
    "ainda não" é motivo suficiente para esperar — e o viés para esperar é o
    desta cadência inteira.
    """
    return total > 0 and sim * 2 > total


def precisa_de_presenca(estado: Estado, agora: datetime) -> bool:
    """A decisão deste instante depende de QUEM está na sala?

    Só a apuração usa a lista de presentes, e a apuração só acontece quando uma
    janela de voto fechou sobre a etapa que ainda corre. Em todo o resto -- modo
    manual, etapa dentro do tempo, voto em andamento, etapa terminal -- a lista
    é irrelevante e `decidir` devolve o mesmo com ela ou sem ela.

    Existe para o chamador não pagar uma consulta à sala a cada leitura de
    estado: a cadência é avaliada no polling de todo mundo que está na aula.
    E vive AQUI, ao lado da regra, porque é a MESMA condição que `decidir` usa
    -- as duas afastadas divergiriam no primeiro ajuste, e o sintoma seria uma
    apuração feita sobre lista vazia, isto é, uma sala que não avança sem
    ninguém entender por quê. `provas/prova_cadencia.py` amarra as duas.
    """
    if not estado.auto:
        return False
    if estado.stage not in ORDEM or estado.stage == "done":
        return False
    if estado.voto_fecha_em is None:
        return False
    if estado.voto_da_etapa != estado.stage:
        return False
    return agora >= estado.voto_fecha_em


def decidir(estado: Estado, agora: datetime, presentes: list[str]) -> Decisao:
    """A decisão da cadência neste instante.

    Pura: nada de banco, nada de rede, nada de `datetime.now()`. O relógio
    entra por parâmetro para a prova poder adiantá-lo.
    """
    # ── MODO MANUAL TEM PRECEDÊNCIA ─────────────────────────────────────────
    # Antes de qualquer outra coisa: com a automação desligada esta função não
    # mexe em nada. É o que o host usa quando a cadência vai mal, e precisa
    # valer mesmo com um voto aberto na tela.
    if not estado.auto:
        return Decisao("nada", porque="modo manual")

    if estado.stage not in ORDEM or estado.stage == "done":
        return Decisao("nada", porque="etapa terminal ou desconhecida")

    # ── HÁ UM VOTO ABERTO? ──────────────────────────────────────────────────
    if estado.voto_fecha_em is not None:
        # O host trocou a etapa à mão enquanto se votava: o voto era sobre
        # outra pergunta e não vale mais.
        if estado.voto_da_etapa != estado.stage:
            return Decisao("estender", porque="a etapa mudou durante o voto")
        if agora < estado.voto_fecha_em:
            return Decisao("nada", porque="voto em andamento")

        sim, total = apurar(estado.votos, presentes)
        if maioria(sim, total):
            prox = proxima_etapa(estado.stage)
            if prox is None:
                return Decisao("nada", porque="não há etapa seguinte", sim=sim, total=total)
            return Decisao("avancar", proxima=prox,
                           porque="maioria quer seguir", sim=sim, total=total)
        return Decisao("estender",
                       porque="sem maioria (quem não votou conta como não)",
                       sim=sim, total=total)

    # ── SEM VOTO: O TEMPO DA ETAPA ACABOU? ──────────────────────────────────
    duracao = DURACAO_DA_ETAPA.get(estado.stage)
    if duracao is None:
        return Decisao("nada", porque="etapa sem relógio (depende do host)")
    if estado.comecou_em is None:
        # Sem marca de início não se inventa uma: abrir voto aqui perguntaria
        # "pode seguir?" a quem acabou de chegar na etapa.
        return Decisao("nada", porque="etapa sem hora de início")
    if agora - estado.comecou_em < timedelta(seconds=duracao):
        return Decisao("nada", porque="etapa ainda no tempo")

    return Decisao("abrir_voto", voto_fecha_em=agora + JANELA_DO_VOTO,
                   porque="tempo da etapa esgotado")

# -*- coding: utf-8 -*-
"""Quem, dentre os conectados ao LiveKit, é uma PESSOA na aula.

Pura, como `cadencia`, `progresso` e `comunicacoes`. Recebe identidades e
devolve identidades.

## Por que isto existe

A sala tem participantes que não são alunos nem professores: o **gravador**
(egress, identidade `EG_…`), o **espelho do grupo** (a aba que republica o
breakout na sala principal, identidade `…__bc`) e, a partir de agora, o
**transcritor** (identidade `TR_…`).

O frontend sempre soube disso — `isEgress` e `isBroadcast` filtram a grade de
câmeras desde que o gravador existe. O backend **não sabia**, e a conta que ele
faz com a lista é a que decide o ritmo do encontro:

    sins, total = apurar(votos, presentes)      # quem não vota conta como "não"

Um gravador na lista é um "aluno" que nunca vota. Com uma pessoa na sala e a
gravação ligada, `maioria` precisa de 2 sins em 2 presentes e recebe no máximo
1: **a sala para de avançar porque está sendo gravada.** E não aparece como
erro — aparece como uma cadência preguiçosa, exatamente o sintoma que o
`8d8aaff` já corrigiu uma vez, quando a fonte de presença era a tabela.

É o mesmo defeito de novo, por outra porta: a regra estava certa, a entrada
dela mentia. Por isso o filtro vive **aqui**, com nome e prova, e não como um
`if` dentro do router.

## A identidade é o dado, não o nome

No LiveKit a faixa de áudio pertence a um participante, e o participante tem
identidade. É daí que sai "quem falou" na transcrição — sem adivinhar por voz.
Então estes prefixos têm um segundo uso: eles dizem de quem NÃO se transcreve
(o gravador republica o áudio de todos; transcrevê-lo duplicaria a aula).
"""
from __future__ import annotations

from typing import Iterable

#: Prefixo da identidade do gravador (egress do LiveKit). O LiveKit o define;
#: o frontend já o conhece (`isEgress`, em `VideoRoom.tsx`).
PREFIXO_DO_GRAVADOR = "EG_"

#: Sufixo da aba que espelha um grupo na sala principal (ver `BROADCAST_SUFFIX`
#: no `VideoRoom.tsx`). É a MESMA pessoa entrando duas vezes: contá-la duas
#: vezes no voto daria peso dobrado a quem está num breakout.
SUFIXO_DO_ESPELHO = "__bc"

#: Prefixo da identidade do transcritor (o agente que assina as faixas de áudio
#: e devolve o texto). Entra na sala como `hidden`, o que o esconde dos outros
#: participantes — mas **não** da API de servidor, que é por onde o backend
#: pergunta quem está presente. Daí a necessidade deste filtro.
PREFIXO_DO_TRANSCRITOR = "TR_"


def e_pessoa(identity: str) -> bool:
    """A identidade é de uma pessoa na aula?

    Falso para o gravador, para o transcritor e para o espelho de grupo.
    """
    if not identity:
        return False
    if identity.startswith(PREFIXO_DO_GRAVADOR):
        return False
    if identity.startswith(PREFIXO_DO_TRANSCRITOR):
        return False
    if identity.endswith(SUFIXO_DO_ESPELHO):
        return False
    return True


def so_pessoas(identidades: Iterable[str]) -> list[str]:
    """As identidades que são de pessoas, sem repetição, em ordem."""
    return sorted({i for i in identidades if e_pessoa(i)})


def identidade_do_transcritor(room_id: str) -> str:
    """A identidade com que o transcritor entra NESTA sala.

    Determinística de propósito: duas instâncias do agente apontadas para a
    mesma sala colidem na identidade, e o LiveKit derruba a conexão antiga em
    vez de deixar dois transcritores gravando a mesma fala duas vezes.
    """
    return PREFIXO_DO_TRANSCRITOR + str(room_id)[:8]

# -*- coding: utf-8 -*-
"""Quem da turma já respondeu o quê, derivado do log de interações.

Separado do router pela mesma razão de `cadencia.py`: é regra de domínio, não
de roteamento — e aqui isso tem uma consequência prática imediata. O router
importa o SDK do LiveKit em cadeia; uma prova que precisasse dele não rodaria
sem o pacote instalado, e esta lógica ficaria sem prova nenhuma.

## O que pode mentir aqui, e tudo em silêncio

- contar a resposta de OUTRA turma (o mesmo aluno, no mês passado);
- contar uma pergunta comum como se fosse do Questionário de Riscos;
- engolir um payload que não decodifica e chamar isso de "respondeu".

Nenhum aparece como erro — aparece como um número plausível, e é por esse
número que quem supervisiona decide se assume o manual antes de a sala avançar.
"""
from __future__ import annotations

import json


def respondeu(evs, desde_iso: str, teste) -> bool:
    """O aluno fez algo nesta SESSÃO que satisfaz `teste`?

    `desde_iso` corta o histórico: um aluno que respondeu o questionário na
    turma do mês passado não pode aparecer como pronto hoje.
    """
    for e in evs or []:
        if (e.get("createdAt") or "") < desde_iso:
            continue
        if teste(e):
            return True
    return False


def e_resposta_de_risco(e) -> bool:
    """Resposta do Questionário de Riscos.

    A marca é `isDimension` no payload — é ela que o pacote usa para separar
    uma resposta de dimensão de uma pergunta comum (ver `pagetreat.js`). O
    payload chega como texto JSON; um que não decodifique não é resposta de
    risco, e não se adivinha.
    """
    if e.get("eventType") != "quiz_answered":
        return False
    bruto = e.get("payload")
    if isinstance(bruto, str):
        try:
            bruto = json.loads(bruto)
        except ValueError:
            return False
    return bool((bruto or {}).get("isDimension"))


def e_avaliacao_de_pares(e) -> bool:
    return e.get("eventType") == "peer_evaluation_submitted"

# -*- coding: utf-8 -*-
"""Quem lidera a turma: a regra, sem banco e sem rede.

Separado do router pela mesma razão de `cadencia.py`: é regra de domínio, e assim
`provas/prova_lider.py` a exercita sem o SDK do LiveKit nem Postgres.

## A regra

1. Janela de voluntários. Um só voluntário é o líder, sem votação.
2. Mais de um voluntário: a turma vota entre eles. Nenhum: vota em qualquer presente.
3. Se o líder cair, assume o mais votado depois dele, desde que tenha um mínimo de
   apoio. Sem isso, nova votação: colocar alguém que quase ninguém escolheu é pior que
   parar 30 segundos.
"""
from __future__ import annotations

import random
from typing import Callable

#: Fração dos votos que o substituto precisa ter para assumir sem nova votação.
MINIMO_DO_SUBSTITUTO = 0.2


def ranking(votos: dict[str, str], candidatos: list[str] | None = None) -> list[tuple[str, int]]:
    """Candidatos do mais ao menos votado. O desempate pelo nome mantém a ordem estável:
    a mesma apuração, lida duas vezes, não pode dar dois resultados."""
    contagem: dict[str, int] = {c: 0 for c in (candidatos or [])}
    for candidato in votos.values():
        if candidatos is None or candidato in contagem:
            contagem[candidato] = contagem.get(candidato, 0) + 1
    return sorted(contagem.items(), key=lambda par: (-par[1], par[0]))


def resultado_dos_voluntarios(voluntarios: list[str], elegiveis: list[str]) -> tuple[str | None, list[str]]:
    """(líder já definido, candidatos da votação). Voluntário que saiu não conta."""
    validos = [v for v in dict.fromkeys(voluntarios) if v in elegiveis]
    if len(validos) == 1:
        return validos[0], []
    return None, validos or list(elegiveis)


def vencedor(votos: dict[str, str], candidatos: list[str],
             sortear: Callable[[list[str]], str] = random.choice) -> str | None:
    """O mais votado entre os candidatos. Empate ou votação sem voto vão a sorteio entre
    os empatados: a turma não pode ficar sem líder porque ninguém votou."""
    if not candidatos:
        return None
    r = ranking(votos, candidatos)
    topo = r[0][1]
    return sortear([c for c, n in r if n == topo])


def substituto(votos: dict[str, str], lider_atual: str, presentes: list[str],
               minimo: float = MINIMO_DO_SUBSTITUTO) -> str | None:
    """O mais votado depois do líder, entre quem está na sala, se tiver o mínimo de apoio.
    `None` = abrir nova votação (inclusive quando o líder foi voluntário único)."""
    total = len(votos)
    if not total:
        return None
    for candidato, n in ranking(votos):
        if candidato == lider_atual or candidato not in presentes:
            continue
        return candidato if n / total >= minimo else None
    return None

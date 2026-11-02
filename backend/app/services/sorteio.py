# -*- coding: utf-8 -*-
"""Quem lidera cada grupo no aquecimento.

Pura, pela mesma razão de `cadencia.py` e `progresso.py`: a regra se exercita
com uma lista de nomes e um sorteio de mentira, e `provas/prova_sorteio.py`
roda os casos que numa aula ao vivo acontecem uma vez a cada vinte turmas.

## O sorteio é GRAVADO, e é esse o ponto

A tentação é sortear na leitura — o grupo chega, escolhe-se um. Isso daria um
líder diferente a cada consulta, e a tela consulta em POLLING: o aquecimento
mostraria um nome novo a cada poucos segundos, e ninguém entenderia que aquilo
era para ser o líder. Pior, cada aluno veria um nome diferente do do colega.

Por isso o sorteio acontece UMA vez, quando os grupos nascem, e vive numa
coluna. Esta função decide; quem chama grava.

## Resortear preserva quem já liderava

`sync-groups` recria os grupos do zero — ids novos, as mesmas pessoas. Sortear
de novo ali trocaria o líder no meio do aquecimento por causa de um clique que
o host deu para outra coisa. Então: **se quem liderava continua no grupo,
continua liderando.** Só há sorteio novo quando a pessoa não está mais lá.

É a mesma escolha de viés da cadência: na dúvida, não mexer no que a turma já
está fazendo.
"""
from __future__ import annotations

import random
from typing import Callable, Iterable, Mapping, Sequence


def sortear(
    membros: Sequence[str],
    anterior: str | None = None,
    escolher: Callable[[Sequence[str]], str] | None = None,
) -> str | None:
    """Quem lidera este grupo.

    - grupo vazio → `None`, e não um erro: um grupo pode ficar sem ninguém
      conectado entre o fim do registro e a abertura das salas;
    - `anterior` ainda entre os membros → ele continua;
    - caso contrário → sorteia entre os membros.

    `escolher` existe para a prova passar um sorteio determinístico. Em
    produção é `random.choice`, e o padrão fica AQUI em vez de no chamador —
    senão cada ponto de chamada decidiria o seu, e um deles esqueceria.
    """
    unicos = list(dict.fromkeys(m for m in membros if m))
    if not unicos:
        return None
    if anterior and anterior in unicos:
        return anterior
    return (escolher or random.choice)(unicos)


def sortear_por_grupo(
    membros_por_grupo: Mapping[str, Iterable[str]],
    anteriores: Mapping[str, str | None] | None = None,
    escolher: Callable[[Sequence[str]], str] | None = None,
) -> dict[str, str | None]:
    """O mesmo para a turma inteira, chaveado pelo NOME do grupo.

    Pelo nome, e não pelo id: `sync-groups` apaga as linhas e insere outras, com
    ids novos. Chavear por id perderia o líder anterior em toda recriação — que
    é exatamente o caso que o `anterior` existe para cobrir.
    """
    antes = anteriores or {}
    return {
        nome: sortear(list(membros), antes.get(nome), escolher)
        for nome, membros in membros_por_grupo.items()
    }

# -*- coding: utf-8 -*-
"""O que o facilitador comunicou, e quando — o histórico do encontro.

Pura, como as outras três. O que ela faz é traduzir uma decisão da cadência num
EVENTO registrável; quem grava é o router.

## Guarda o evento, não a frase

A tentação é gravar a sentença pronta ("A turma aprovou: seguindo para
Plenária"). Não dá, e a razão é concreta: **os rótulos das etapas vivem no
frontend** (`STEPS`, em `VideoRoom.tsx`), onde elas são nomeadas, renomeadas e
reordenadas. Montar a frase aqui exigiria uma segunda lista de nomes no backend
— e, nas palavras que este repositório já usa em `cadencia.py`, uma segunda
lista envelheceria calada.

Então grava-se `tipo` + `meta` (as chaves das etapas e a contagem dos votos), e a
tela compõe a frase com os rótulos que ela já tem. O DADO fica congelado; a
redação acompanha o produto, que é o certo — o histórico tem de ler igual ao
resto da tela.

`provas/prova_comunicacoes.py` confere que a tela sabe renderizar TODO tipo que
daqui pode sair. É essa afirmação que impede as duas pontas de divergirem.

## Por que não basta o log

`logger.info("[cadencia] ...")` já existia e registra a mesma decisão. Mas log
não é histórico: ninguém numa aula abre o CloudWatch, o aluno que chegou
atrasado não tem como saber o que já foi dito, e quem supervisiona precisa ver a
automação agindo enquanto ela age. Por isso isto vai para o banco e para a tela.
"""
from __future__ import annotations

#: Os tipos que podem ser emitidos. A tela tem de saber renderizar todos.
#:
#: Ficam listados aqui, e não só implícitos nos `if`s do router, para a prova
#: poder percorrê-los — uma lista que ninguém consegue enumerar não dá para
#: conferir contra a outra ponta.
TIPOS: tuple[str, ...] = (
    "voto_aberto",    # a etapa venceu e a turma foi consultada
    "avancou",        # a maioria aprovou; a sala seguiu
    "estendeu",       # não passou; a etapa ganhou mais tempo
    "etapa_manual",   # o host pôs a etapa à mão (freio de mão)
    "recado",         # o host falou com a turma ou com um grupo
)

#: Decisão da cadência → tipo do evento. `nada` não vira comunicação nenhuma:
#: "a sala seguiu como estava" não é algo que alguém precise ler.
_DE_ACAO: dict[str, str] = {
    "abrir_voto": "voto_aberto",
    "avancar": "avancou",
    "estender": "estendeu",
}


def da_decisao(stage: str, acao: str, proxima: str | None,
               sim: int, total: int) -> tuple[str, dict] | None:
    """O evento correspondente a uma decisão da cadência, ou `None`.

    Recebe os campos da `Decisao` soltos, e não o objeto: assim esta função não
    importa `cadencia`, e a prova não precisa construir um dataclass para
    exercitar a tradução.
    """
    tipo = _DE_ACAO.get(acao)
    if not tipo:
        return None
    meta: dict = {"stage": stage}
    if proxima:
        meta["proxima"] = proxima
    # A contagem só existe quando houve apuração. Gravar `0/0` num voto que
    # acabou de abrir afirmaria que ninguém aprovou -- e ninguém foi perguntado
    # ainda.
    if acao in ("avancar", "estender"):
        meta["sim"] = int(sim)
        meta["total"] = int(total)
    return tipo, meta

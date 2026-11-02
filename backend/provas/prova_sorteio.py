# -*- coding: utf-8 -*-
"""Quem lidera cada grupo — e por que a escolha é gravada.

    python -B provas/prova_sorteio.py

## O que isto protege

O sorteio parece a coisa mais simples da facilitação, e tem dois jeitos de dar
errado em silêncio:

1. **Sortear na leitura.** A tela consulta em polling. Sorteando a cada consulta,
   o líder muda a cada poucos segundos e cada aluno vê um nome diferente do do
   colega — ninguém entende que aquilo era para ser liderança. Por isso a escolha
   acontece uma vez e vive numa coluna.
2. **Resortear ao recriar os grupos.** `sync-groups` apaga e reinsere, com ids
   novos. Sortear de novo ali troca o líder no meio do aquecimento por causa de
   um clique que o host deu para outra coisa.

E dois que derrubariam o que já funcionava:

3. sortear entre quem **não está na sala** — a tabela de participantes não fecha
   `left_at`, então ela lista quem já entrou alguma vez, para sempre;
4. pedir a coluna nova antes de a migration rodar: publicar **não aplica
   migration**, e a divisão de grupos é caminho antigo. Um erro ali levaria a
   divisão inteira junto, para entregar um líder que ninguém ainda pediu.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

#: Do SERVIÇO, não do router: o router importa o SDK do LiveKit em cadeia.
from app.services.sorteio import sortear, sortear_por_grupo  # noqa: E402

falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-58s %s" % ("ok" if cond else "FALHA", oque, porque))


def ler(caminho: str) -> str:
    return io.open(RAIZ / caminho, encoding="utf-8").read()


def corpo(fonte: str, assinatura: str) -> str:
    """O texto de UMA função, para a afirmação não passar por causa de outra."""
    i = fonte.index(assinatura)
    resto = fonte[i + len(assinatura):]
    fim = len(resto)
    for marca in ("\nasync def ", "\ndef ", "\n@router.", "\nclass "):
        j = resto.find(marca)
        if j != -1:
            fim = min(fim, j)
    return assinatura + resto[:fim]


def so_codigo(texto: str) -> str:
    """Sem as linhas de comentário.

    A primeira versão desta prova reprovou por culpa dela mesma: a afirmação
    "não usa `left_at IS NULL`" casava com o COMENTÁRIO que explica por que a
    função não o usa. Afirmar sobre o arquivo inteiro deixa a prova confundir a
    explicação de uma ausência com a ausência.
    """
    return "\n".join(l for l in texto.splitlines() if not l.strip().startswith("#"))


#: Sorteio determinístico: sempre o primeiro da lista. Com ele, "sorteou" e
#: "manteve" deixam de se confundir — se a função devolvesse sempre o primeiro
#: por acidente, o caso do líder anterior (que NÃO é o primeiro) reprovaria.
primeiro = lambda xs: xs[0]  # noqa: E731

print("Sorteio do líder do grupo")
print()
print("1) a escolha sai de DENTRO do grupo")
print()

conferir(sortear([], escolher=primeiro) is None,
         "grupo vazio não tem líder, e não estoura",
         "entre fechar o registro e abrir as salas isso acontece")
conferir(sortear(["ana"], escolher=primeiro) == "ana",
         "grupo de um: é ela")
conferir(sortear(["ana", "bia", "caio"], escolher=primeiro) in ("ana", "bia", "caio"),
         "o sorteado é sempre um dos membros")
conferir(sortear(["ana", "ana", "bia"], escolher=lambda xs: xs[1]) == "bia",
         "nome repetido não conta duas vezes",
         "o mesmo aluno com duas linhas dobraria a chance dele")
conferir(sortear(["", None, "bia"], escolher=primeiro) == "bia",  # type: ignore[list-item]
         "identidade vazia é descartada, não sorteada")

print()
print("2) resortear PRESERVA quem já liderava")
print()

conferir(sortear(["ana", "bia", "caio"], anterior="caio", escolher=primeiro) == "caio",
         "líder anterior ainda no grupo continua líder",
         "e repare: `primeiro` devolveria 'ana' se houvesse sorteio")
conferir(sortear(["ana", "bia"], anterior="caio", escolher=primeiro) == "ana",
         "líder que SAIU do grupo dá lugar a um sorteio novo")
conferir(sortear([], anterior="caio", escolher=primeiro) is None,
         "e grupo que esvaziou não guarda líder fantasma")

print()
print("3) a turma inteira, chaveada pelo NOME do grupo")
print()

membros = {"Grupo 1": ["ana", "bia"], "Grupo 2": ["caio", "davi"]}
r = sortear_por_grupo(membros, {"Grupo 2": "davi"}, escolher=primeiro)
conferir(r == {"Grupo 1": "ana", "Grupo 2": "davi"},
         "cada grupo tem o seu, e o anterior do Grupo 2 foi mantido")
conferir(sortear_por_grupo({"Grupo 1": []}, escolher=primeiro) == {"Grupo 1": None},
         "grupo sem ninguém volta com líder nulo")

vazio = sortear_por_grupo(membros, None, escolher=primeiro)
conferir(vazio == {"Grupo 1": "ana", "Grupo 2": "caio"},
         "sem anteriores, sorteia todos",
         "é o caso da primeira divisão da turma")

print()
print("4) a escolha é GRAVADA, não recalculada na leitura")
print()

ROUTER = ler("app/routers/openpbl_class.py")
BREAK = ler("app/routers/breakouts.py")

conferir("UPDATE video_breakout_groups SET leader_identity" in ROUTER,
         "o sorteio grava numa coluna")
conferir("sortear_por_grupo" not in BREAK and "sortear(" not in BREAK,
         "e a montagem do estado dos grupos NÃO sorteia",
         "sortear ali daria um líder novo a cada poll")

estado = corpo(BREAK, "async def _state(room) -> dict:")
conferir("leader_identity" in estado and "leader_name" in estado,
         "o estado só LÊ a escolha, e devolve identidade e nome")

print()
print("5) sorteia entre quem está na sala AGORA")
print()

divisao = corpo(ROUTER, "async def _auto_group_breakouts(room_id: str) -> int:")
conferir("left_at IS NULL" not in so_codigo(divisao),
         "a divisão de grupos não usa `left_at IS NULL`",
         "a coluna nunca é fechada: 321 linhas em produção, nenhuma")
conferir("_presentes(room_id)" in divisao,
         "ela cruza com quem o LiveKit diz estar conectado")
conferir("_sortear_lideres" in divisao,
         "e sorteia depois de montar os grupos")

sync = corpo(ROUTER, "async def _sync_openpbl_groups(room_id: str, cls) -> int:")
conferir("_sortear_lideres" in sync and "_lideres_atuais" in sync,
         "o caminho do sync-groups também sorteia, preservando o anterior",
         "senão o resorteio trocaria o líder no meio do aquecimento")

print()
print("6) sem a migration, o sorteio fica INERTE — e só ele")
print()

sorteia = corpo(ROUTER, "async def _sortear_lideres(room_id: str, anteriores: dict[str, str | None] | None = None) -> None:")
pos_guarda = sorteia.find('tem_coluna("video_breakout_groups", "leader_identity")')
pos_update = sorteia.find("UPDATE video_breakout_groups SET leader_identity")
conferir(pos_guarda != -1, "o sorteio pergunta se a coluna existe")
conferir(pos_guarda != -1 and pos_update != -1 and pos_guarda < pos_update,
         "ANTES de escrever nela",
         "foi assim que a 018 derrubou o botão do host no meio da aula")
conferir('tem_coluna("video_breakout_groups", "leader_identity")' in estado,
         "e a leitura do estado dos grupos também se protege",
         "pedir coluna ausente ali apagaria os grupos da tela")

print()
print("7) a tela mostra o líder, e só quando existe")
print()

FRONT = (RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx").read_text(encoding="utf-8")
conferir("leaderName" in FRONT and "leader_name" in FRONT,
         "o líder chega à tela")
conferir("{leaderName ? <>" in FRONT,
         "CONTROLE: sem líder, o banner não afirma liderança nenhuma",
         "grupo vazio e servidor sem a 019 caem aqui")
conferir('g.leader_name ? ` • líder: ${g.leader_name}` : ""' in FRONT,
         "e o seletor de grupos idem")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

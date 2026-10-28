# -*- coding: utf-8 -*-
"""Quantos da turma já responderam — e de onde esse número sai.

    python -B provas/prova_progresso.py

## O que isto protege

Com um facilitador humano, "todo mundo terminou?" era uma pergunta em voz alta.
Com a cadência decidindo sozinha, este número é o único sinal de que a sala está
prestes a avançar com metade da turma pela metade.

Os jeitos de ele mentir, todos silenciosos:

- contar a resposta de OUTRA turma (o mesmo aluno, no mês passado);
- contar uma pergunta comum como se fosse do Questionário de Riscos;
- contar o facilitador como aluno, inflando o denominador;
- engolir um payload que não decodifica e chamar isso de "respondeu".

Nenhum deles aparece como erro: aparece como um número plausível.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

#: Do SERVIÇO, não do router: o router importa o SDK do LiveKit em cadeia, e
#: uma prova que dependesse dele não rodaria sem o pacote instalado -- esta
#: lógica ficaria sem prova nenhuma.
from app.services.progresso import (  # noqa: E402
    e_avaliacao_de_pares, e_resposta_de_risco, respondeu,
)

DESDE = "2026-10-28T13:00:00"
falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-58s %s" % ("ok" if cond else "FALHA", oque, porque))


def ev(tipo="quiz_answered", quando="2026-10-28T14:00:00", payload=None):
    e = {"eventType": tipo, "createdAt": quando}
    if payload is not None:
        e["payload"] = payload if isinstance(payload, str) else json.dumps(payload)
    return e


print("Progresso das respostas")
print()
print("1) risco é `isDimension`, e nada mais")
print()

conferir(e_resposta_de_risco(ev(payload={"isDimension": True})) is True,
         "quiz com `isDimension` é resposta de risco")
conferir(e_resposta_de_risco(ev(payload={"isDimension": False})) is False,
         "quiz comum NÃO é", "é a marca que o pacote usa para separar os dois")
conferir(e_resposta_de_risco(ev(payload={})) is False,
         "sem a marca, não conta")
conferir(e_resposta_de_risco(ev(tipo="package_opened", payload={"isDimension": True})) is False,
         "CONTROLE: e abrir o pacote não é responder",
         "o tipo do evento também precisa casar")

#: Payload chega como TEXTO. Um que não decodifique não é resposta de risco --
#: e adivinhar aqui inflaria o número justamente quando o dado está ruim.
conferir(e_resposta_de_risco(ev(payload="{isto nao e json")) is False,
         "payload corrompido não vira 'respondeu'")
conferir(e_resposta_de_risco(ev(payload='{"isDimension": true}')) is True,
         "CONTROLE: mas payload em TEXTO válido conta",
         "é assim que ele chega do LRS")

print()
print("2) a sessão corta o histórico")
print()

#: O mesmo aluno pode ter respondido numa turma anterior. Contar aquilo faria
#: a sala começar com todo mundo "pronto".
antigo = [ev(quando="2026-09-01T10:00:00", payload={"isDimension": True})]
conferir(respondeu(antigo, DESDE, e_resposta_de_risco) is False,
         "resposta de outra turma não conta",
         "senão a sala nasceria com a turma inteira pronta")
agora = [ev(quando="2026-10-28T14:00:00", payload={"isDimension": True})]
conferir(respondeu(agora, DESDE, e_resposta_de_risco) is True,
         "CONTROLE: a desta sessão conta")
conferir(respondeu(antigo + agora, DESDE, e_resposta_de_risco) is True,
         "e uma antiga não apaga uma nova")

print()
print("3) avaliação de pares")
print()

conferir(e_avaliacao_de_pares(ev(tipo="peer_evaluation_submitted")) is True,
         "`peer_evaluation_submitted` é avaliação de pares")
conferir(e_avaliacao_de_pares(ev(tipo="quiz_answered")) is False,
         "CONTROLE: e um quiz não é")

print()
print("4) os extremos não explodem")
print()

conferir(respondeu(None, DESDE, e_resposta_de_risco) is False,
         "aluno sem eventos (LRS atrasou) não é 'respondeu'",
         "ausência de dado não é evidência de resposta")
conferir(respondeu([], DESDE, e_resposta_de_risco) is False, "lista vazia idem")
conferir(respondeu([{"eventType": "quiz_answered"}], DESDE, e_resposta_de_risco) is False,
         "evento sem data cai fora da sessão",
         "sem saber QUANDO, não se pode afirmar que foi hoje")

print()
print("5) o roster entrega o resumo pronto, e o host não conta")
print()

ROUTER = (RAIZ / "app/routers/openpbl_class.py").read_text(encoding="utf-8")
conferir('"progresso": {' in ROUTER,
         "o roster devolve o resumo",
         "cada cliente contando do seu jeito daria números diferentes")
conferir('if not e["is_staff"] and e["na_sala"]' in ROUTER,
         "o denominador exclui o facilitador E quem não está na sala",
         "contar o host faria a turma parecer sempre incompleta")

#: `na_sala` não é detalhe: `left_at` nunca fecha no banco desta aplicação
#: (medido: 321 linhas, nenhuma fechada), então contar por ele punha aqui todo
#: mundo que já entrou nesta sala algum dia -- "3 de 47" numa turma de 12. Um
#: número plausível e errado, que é o pior tipo. `prova_cadencia.py` seção 14
#: cuida da outra metade: a cadência apurando sobre a mesma lista.
conferir("left_at" not in ROUTER[ROUTER.index('"progresso": {'):],
         "e não pelo `left_at`, que nunca fecha",
         "a tela e a cadência têm de ver a mesma turma")
conferir("respondeu(by_student.get(email), since_iso," in ROUTER,
         "derivado dos MESMOS eventos já buscados",
         "uma consulta por aluno seriam 30 chamadas ao LRS a cada 8s")

FRONT = (RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx").read_text(encoding="utf-8")
conferir("<ProgressoDasRespostas" in FRONT, "e a tela o RENDERIZA")
conferir('pblStage === "release_risks"' in FRONT and 'pblStage === "release_feedback"' in FRONT,
         "nas duas etapas em que a turma responde algo",
         "fora delas o número não significa nada")
conferir("if (!total) return null" in FRONT,
         "CONTROLE: turma vazia não desenha barra nenhuma",
         "`0 de 0` afirmaria algo sobre uma turma que não existe")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

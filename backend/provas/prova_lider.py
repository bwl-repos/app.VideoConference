# -*- coding: utf-8 -*-
"""Prova das regras do líder geral e do prazo dos riscos.

    python -I -B prova_lider.py
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "app" / "services"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def carregar(nome):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / f"{nome}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nome] = mod
    spec.loader.exec_module(mod)
    return mod


lider = carregar("lider")
cadencia = carregar("cadencia")
progresso = carregar("progresso")
falhas = 0


def conferir(ok, texto):
    global falhas
    print(("ok    " if ok else "FALHA ") + texto)
    falhas += 0 if ok else 1


# ── Voluntários ─────────────────────────────────────────────────
conferir(lider.resultado_dos_voluntarios(["a"], ["a", "b"]) == ("a", []),
         "um voluntário vira líder sem votação")
conferir(lider.resultado_dos_voluntarios(["a", "b"], ["a", "b", "c"]) == (None, ["a", "b"]),
         "dois voluntários: votação só entre eles")
conferir(lider.resultado_dos_voluntarios([], ["a", "b"]) == (None, ["a", "b"]),
         "sem voluntário: votação entre todos os presentes")
conferir(lider.resultado_dos_voluntarios(["x"], ["a", "b"]) == (None, ["a", "b"]),
         "voluntário que saiu da sala não vira líder")

# ── Votação ─────────────────────────────────────────────────────
conferir(lider.vencedor({"1": "a", "2": "a", "3": "b"}, ["a", "b"]) == "a", "vence o mais votado")
conferir(lider.vencedor({"1": "z"}, ["a", "b"], sortear=min) == "a",
         "voto em quem não é candidato não conta")
conferir(lider.vencedor({"1": "a", "2": "b"}, ["a", "b", "c"], sortear=max) == "b",
         "empate vai a sorteio só entre os empatados")
conferir(lider.vencedor({}, ["a", "b"], sortear=min) == "a", "sem nenhum voto, sorteia: a turma não fica sem líder")
conferir(lider.vencedor({}, []) is None, "sem candidato, não há líder")

# ── Substituto ──────────────────────────────────────────────────
votos = {"1": "a", "2": "a", "3": "a", "4": "b", "5": "c"}   # b e c têm 20% cada
conferir(lider.substituto(votos, "a", ["b", "c"]) == "b", "assume o 2º mais votado com 20%")
conferir(lider.substituto(votos, "a", ["c"]) == "c", "2º fora da sala: passa para o seguinte presente")
fraco = {str(i): "a" for i in range(9)} | {"9": "b"}          # b tem 10%
conferir(lider.substituto(fraco, "a", ["b"]) is None, "abaixo de 20%: nova votação")
conferir(lider.substituto({}, "a", ["b"]) is None, "voluntário único (sem votos): nova votação")
conferir(lider.substituto({"1": "a"}, "a", ["b"]) is None, "só o líder teve voto: nova votação")

# ── Prazo dos riscos e etapas que avançam sozinhas ──────────────
T0 = datetime(2026, 11, 6, tzinfo=timezone.utc)
base = dict(auto=True, comecou_em=T0)
d = cadencia.decidir(cadencia.Estado(stage="release_risks", prazo=T0 + timedelta(minutes=5), **base),
                     T0 + timedelta(minutes=4), [])
conferir(d.acao == "nada", "antes do prazo, os riscos continuam")
d = cadencia.decidir(cadencia.Estado(stage="release_risks", prazo=T0 + timedelta(minutes=5), **base),
                     T0 + timedelta(minutes=5), [])
conferir(d.acao == "avancar" and d.proxima == "show_chart", "no prazo, avança sem votar")
d = cadencia.decidir(cadencia.Estado(stage="release_risks", **base), T0 + timedelta(minutes=10), [])
conferir(d.acao == "avancar", "sem 90%, fecha no limite de 10 min, para a sala não travar")
d = cadencia.decidir(cadencia.Estado(stage="release_risks", auto=False, comecou_em=T0, prazo=T0), T0 + timedelta(hours=1), [])
conferir(d.acao == "nada", "modo manual tem precedência sobre o prazo")
d = cadencia.decidir(cadencia.Estado(stage="groups", **base), T0 + timedelta(minutes=15), [])
conferir(d.acao == "avancar" and d.proxima == "plenary",
         "grupos avançam sem votar: a sala principal fica vazia e um voto nunca passaria")
d = cadencia.decidir(cadencia.Estado(stage="release_feedback", **base), T0 + timedelta(minutes=10), [])
conferir(d.acao == "avancar", "a avaliação dos colegas fecha no limite, sem voto: a turma está no pacote")
d = cadencia.decidir(cadencia.Estado(stage="synopsis", **base), T0 + timedelta(minutes=6), [])
conferir(d.acao == "abrir_voto", "as demais etapas continuam votando")

# ── Concluir os riscos ──────────────────────────────────────────
DESDE = "2026-11-06T00:00:00"
def ev(q, quando="2026-11-06T10:00:00", dim=True, tipo="quiz_answered"):
    return {"eventType": tipo, "createdAt": quando, "payload": {"isDimension": dim, "question": q}}
evs = [ev(1), ev(2), ev(2), ev(3, dim=False), ev(4, quando="2026-10-01T10:00:00"), ev(5, tipo="outro")]
conferir(progresso.respostas_de_risco(evs, DESDE) == 2,
         "conta perguntas distintas, só de risco e só desta sessão")
conferir(progresso.respostas_de_risco([{"eventType": "quiz_answered", "createdAt": "2026-11-06T10:00:00", "payload": "{quebrado"}], DESDE) == 0,
         "payload que não decodifica não conta")

print("\nfalhas:", falhas)
sys.exit(1 if falhas else 0)

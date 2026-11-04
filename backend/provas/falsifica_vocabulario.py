# -*- coding: utf-8 -*-
"""As conferências novas da prova_cadencia realmente medem alguma coisa?

    python -B provas/falsifica_vocabulario.py

Uma prova verde só vale se ficar vermelha quando o defeito volta. Este arquivo
reintroduz, um de cada vez, exatamente o defeito que estava em produção em
04/11/2026 — e exige que a prova FALHE em cada caso.

Os arquivos são alterados no disco e **restaurados no `finally`**, inclusive se
a prova estourar. Nada é deixado modificado.
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
PROVA = RAIZ / "provas/prova_cadencia.py"
FRONT = RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx"

#: (rótulo, arquivo, trecho original, trecho estragado)
#:
#: Cada estrago é a forma REAL do defeito, não uma mutilação qualquer: é o
#: estado em que o código/schema estava quando a sala não começava.
ESTRAGOS = [
    ("a espera volta a 1 minuto",
     RAIZ / "app/services/cadencia.py",
     '"session_start":      600,',
     '"session_start":       60,'),

    ("o DEFAULT do schema volta a 'presentation'",
     RAIZ / "app/schema.sql",
     "stage TEXT NOT NULL DEFAULT 'session_start'",
     "stage TEXT NOT NULL DEFAULT 'presentation'"),

    ("a cadencia deixa de detectar etapa desconhecida",
     RAIZ / "app/routers/openpbl_class.py",
     "if estado.stage not in cadencia.DURACAO_DA_ETAPA:",
     "if False and estado.stage not in cadencia.DURACAO_DA_ETAPA:"),

    ("o frontend volta a trocar a etapa em silencio",
     FRONT,
     "const etapaDesconhecida",
     "const etapaTrocadaCalada"),

    ("a camera do facilitador volta a aparecer no automatico",
     FRONT,
     "apenasFixada={!!pblClass?.auto_mode}",
     "apenasFixada={false}"),

    # O defeito mais silencioso dos seis: sem o intervalo, o GET /openpbl só
    # acontece quando alguém entra na sala, e a cadência nunca mais é avaliada.
    # Não gera erro nenhum -- a sala simplesmente para.
    ("a cadencia deixa de ser chamada periodicamente",
     FRONT,
     "const iv = setInterval(load, 10000);\n    const off = sdk.subscribe(roomId, (event, payload) => {",
     "const off = sdk.subscribe(roomId, (event, payload) => {"),
]


def prova_passa() -> bool:
    r = subprocess.run([sys.executable, "-B", str(PROVA)], cwd=str(RAIZ),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode == 0


print("sanidade: a prova passa com a arvore intacta?")
if not prova_passa():
    raise SystemExit("[ERRO] a prova ja falha ANTES de qualquer estrago; "
                     "conserte a arvore antes de falsificar.")
print("   sim\n")

falhas = 0
for rotulo, arquivo, de, para in ESTRAGOS:
    original = io.open(arquivo, encoding="utf-8").read()
    if de not in original:
        print(f"   NAO MEDIDO  {rotulo}")
        print(f"               trecho ausente em {arquivo.name}: {de!r}")
        falhas += 1
        continue
    try:
        io.open(arquivo, "w", encoding="utf-8", newline="\n").write(
            original.replace(de, para, 1))
        pegou = not prova_passa()
    finally:
        io.open(arquivo, "w", encoding="utf-8", newline="\n").write(original)
    print(f"   {'ok   ' if pegou else 'PASSOU'}      {rotulo}")
    if not pegou:
        print("               a prova ficou VERDE com o defeito de volta")
    falhas += not pegou

print(f"\nestragos nao detectados: {falhas}")
raise SystemExit(1 if falhas else 0)

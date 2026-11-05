# -*- coding: utf-8 -*-
"""A prova da cadencia mede as TRES copias da lista de etapas?

    python -B provas/falsifica_cadencia.py

A ordem do encontro esta escrita em tres lugares: `ORDEM` (cadencia, pura),
`_STAGES` (router) e `STEPS` (tela). Nenhum deles importa o outro, e divergir
NAO da erro: a sala entra numa etapa que a tela nao reconhece, a tela cai para
"Abertura" e o facilitador ve o encontro no lugar errado -- foi exatamente o
que aconteceu com `amplify_code` em 05/11/2026, em producao.

Os arquivos sao alterados no disco e restaurados no `finally`, inclusive se a
prova estourar. Nada fica modificado.
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
PROVA = RAIZ / "provas/prova_cadencia.py"

CADENCIA = RAIZ / "app/services/cadencia.py"
ROUTER = RAIZ / "app/routers/openpbl_class.py"
FRONT = RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx"

#: (rotulo, arquivo, trecho original, trecho estragado)
ESTRAGOS = [
    # O defeito REAL: a tela sem a etapa que o backend conhece.
    ("a tela volta a nao conhecer `amplify_code`",
     FRONT,
     '  { id: "amplify_code",       action: "Ampliar o código da sessão",           head: "Registro de Presença" },\n',
     ""),

    # O SEGUNDO defeito da mesma etapa: a tela conhece, o botao nao executa.
    ("o sequenciador do host volta a nao ter `case` para a etapa",
     FRONT,
     '        case "amplify_code":\n',
     '        case "amplify_code_que_ninguem_usa":\n'),

    # O TERCEIRO: a ancora por posicao fica apontando para a etapa errada.
    ("o class code volta a ser liberado uma etapa depois",
     FRONT,
     'stepIndex(pblStage) >= stepIndex("amplify_code")',
     'stepIndex(pblStage) >= stepIndex("registration_close")'),

    ("a tela ganha uma etapa que a cadencia nao tem",
     FRONT,
     '  { id: "done",               action: "Encerrar a sala",                      head: "Encerramento" },',
     '  { id: "done",               action: "Encerrar a sala",                      head: "Encerramento" },\n'
     '  { id: "pos_encontro",       action: "Pos-encontro",                         head: "Encerramento" },'),

    ("a tela troca a ORDEM de duas etapas",
     FRONT,
     '  { id: "synopsis",           action: "Revisitar a situação-problema",        head: "Situação-problema" },\n'
     '  { id: "groups",             action: "Divisão em grupos",                    head: "Aquecimento" },',
     '  { id: "groups",             action: "Divisão em grupos",                    head: "Aquecimento" },\n'
     '  { id: "synopsis",           action: "Revisitar a situação-problema",        head: "Situação-problema" },'),

    ("o router perde uma etapa que a cadencia tem",
     ROUTER,
     '"amplify_code", "registration_close",',
     '"registration_close",'),

    ("uma etapa da ordem fica sem duracao declarada",
     CADENCIA,
     '    "closing":            180,\n',
     ""),
]


def prova_passa() -> bool:
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(PROVA)], cwd=str(RAIZ),
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
    if original.count(de) > 1:
        print(f"   AMBIGUO     {rotulo}")
        print(f"               {original.count(de)} ocorrencias em {arquivo.name}")
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

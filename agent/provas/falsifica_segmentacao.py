# -*- coding: utf-8 -*-
"""A prova da segmentação mede alguma coisa?

    python -B provas/falsifica_segmentacao.py

Verde só vale se ficar vermelho quando o defeito volta. Cada estrago aqui é a
forma PLAUSÍVEL do erro — o que alguém escreveria de boa-fé —, não uma
mutilação qualquer: `>` em vez de `>=`, o reset esquecido, o `in` em vez do
`==`. São os que não dão erro: dão transcrição plausível e errada.

O arquivo é alterado no disco e restaurado no `finally`. Nada fica modificado.
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
PROVA = RAIZ / "provas/prova_segmentacao.py"
REGRA = RAIZ / "segmentacao.py"

#: (rótulo, trecho original, trecho estragado)
ESTRAGOS = [
    ("silencio passa a abrir fala (alucinacao em sala calada)",
     "            if not tem_voz:\n                return None",
     "            if False:\n                return None"),

    ("qualquer pausa corta (a frase vira duas linhas)",
     "if self.ms_de_silencio >= self.silencio_que_fecha_ms:",
     "if self.ms_de_silencio > 0:"),

    ("nenhuma pausa corta (o texto so aparece no fim da aula)",
     "if self.ms_de_silencio >= self.silencio_que_fecha_ms:",
     "if self.ms_de_silencio >= 10 ** 9:"),

    ("o silencio do fim entra no audio (onde o modelo inventa)",
     "            ms_uteis=self.ms_ate_ultima_voz,",
     "            ms_uteis=self.ms_no_buffer,"),

    ("sem teto de duracao (quem apresenta nao e transcrito)",
     "        if self.ms_no_buffer >= self.fala_maxima_ms:\n            return self._fechar(\"teto\")",
     "        if False:\n            return self._fechar(\"teto\")"),

    ("tosse e 'uhum' passam a valer uma chamada ao reconhecedor",
     "            vale=self.ms_de_voz >= self.fala_minima_ms,",
     "            vale=True,"),

    ("o estado nao volta ao zero (a fala seguinte soma na anterior)",
     "        self.aberta = False\n        self.ms_no_buffer = 0\n        self.ms_ate_ultima_voz = 0\n        self.ms_de_voz = 0\n        self.ms_de_silencio = 0\n        return corte",
     "        self.aberta = False\n        return corte"),

    ("quem desconecta perde a ultima frase",
     "        if not self.aberta:\n            return None\n        return self._fechar(\"saiu\")",
     "        return None"),

    ("fechar o que nao abriu inventa uma fala vazia",
     "        if not self.aberta:\n            return None\n        return self._fechar(\"saiu\")",
     "        return self._fechar(\"saiu\")"),

    # O mais sutil: filtrar por 'contem' em vez de texto inteiro. Parece mais
    # seguro -- pega "ah, obrigado pela atencao mesmo" -- e apaga a fala REAL de
    # quem comeca agradecendo o professor.
    ("o filtro de ruido passa a ser por 'contem'",
     "    return limpo not in RUIDO_CONHECIDO",
     "    return not any(r in limpo for r in RUIDO_CONHECIDO)"),

    ("texto vazio passa a ser gravado",
     "    if not limpo:\n        return False",
     "    if False:\n        return False"),

    ("os limiares ficam incoerentes (minima acima do silencio)",
     "FALA_MINIMA_MS = 400",
     "FALA_MINIMA_MS = 4_000"),

    ("a regra passa a depender de rede",
     "from dataclasses import dataclass",
     "import httpx\nfrom dataclasses import dataclass"),
]


def prova_passa() -> bool:
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(PROVA)], cwd=str(RAIZ),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode == 0


print("sanidade: a prova passa com a arvore intacta?")
if not prova_passa():
    raise SystemExit("[ERRO] a prova ja falha ANTES de qualquer estrago.")
print("   sim\n")

falhas = 0
for rotulo, de, para in ESTRAGOS:
    original = io.open(REGRA, encoding="utf-8").read()
    if de not in original:
        print(f"   NAO MEDIDO  {rotulo}")
        print(f"               trecho ausente: {de!r}")
        falhas += 1
        continue
    try:
        io.open(REGRA, "w", encoding="utf-8", newline="\n").write(
            original.replace(de, para, 1))
        pegou = not prova_passa()
    finally:
        io.open(REGRA, "w", encoding="utf-8", newline="\n").write(original)
    print(f"   {'ok   ' if pegou else 'PASSOU'}      {rotulo}")
    if not pegou:
        print("               a prova ficou VERDE com o defeito de volta")
    falhas += not pegou

print(f"\nestragos nao detectados: {falhas}")
raise SystemExit(1 if falhas else 0)

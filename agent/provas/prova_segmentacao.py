# -*- coding: utf-8 -*-
"""Onde uma fala começa e termina — a única decisão do transcritor.

    python -B provas/prova_segmentacao.py

Roda sem áudio, sem GPU, sem rede e sem dependência nenhuma: é o que a
separação de `segmentacao.py` compra. Os casos abaixo são os que, numa aula de
verdade, aparecem uma vez a cada vinte turmas — e dois deles não dariam erro
nenhum, só uma transcrição plausível e errada:

- **alucinação em silêncio**: o Whisper devolve "Obrigado pela atenção" quando
  recebe uma sala calada. Uma frase inventada na boca de um aluno é pior que
  linha faltando, porque quem lê depois não tem como saber que é falsa.
- **fala cortada ao meio**: quem respira no meio da frase vira duas linhas, e o
  registro do encontro deixa de ler como alguém falando.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from segmentacao import (  # noqa: E402
    FALA_MAXIMA_MS,
    FALA_MINIMA_MS,
    LIMIAR_DE_VOZ,
    SILENCIO_QUE_FECHA_MS,
    Fatiador,
    vale_gravar,
)

falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-56s %s" % ("ok" if cond else "FALHA", oque, porque))


VOZ = LIMIAR_DE_VOZ * 3        # bem acima do limiar
MUDO = LIMIAR_DE_VOZ / 10      # bem abaixo
QUADRO = 20                    # ms por quadro, como o LiveKit entrega


def alimentar(f: Fatiador, energia: float, ms: int):
    """Vários quadros de `QUADRO` ms. Devolve o primeiro corte que aparecer."""
    corte = None
    for _ in range(max(1, ms // QUADRO)):
        c = f.alimentar(energia, QUADRO)
        if c is not None and corte is None:
            corte = c
    return corte


print("Segmentação da fala")
print()
print("1) silêncio não abre fala")
print()

f = Fatiador()
conferir(alimentar(f, MUDO, 5_000) is None,
         "5 s de sala calada não produzem corte nenhum",
         "o reconhecedor nem é chamado — é ele que alucina em silêncio")
conferir(not f.aberta and f.ms_no_buffer == 0,
         "e nada é acumulado",
         "o silêncio anterior à primeira palavra não interessa a ninguém")

print()
print("2) a voz abre, a pausa curta NÃO corta")
print()

f = Fatiador()
conferir(alimentar(f, VOZ, 600) is None and f.aberta,
         "voz abre a fala e ela fica aberta")

curta = SILENCIO_QUE_FECHA_MS // 2
conferir(alimentar(f, MUDO, curta) is None,
         f"pausa de {curta} ms não corta",
         "quem respira no meio da frase não vira duas linhas")
conferir(alimentar(f, VOZ, 600) is None and f.aberta,
         "e a fala continua a mesma depois da pausa")

print()
print("3) a pausa longa corta, e o silêncio do fim fica fora do áudio")
print()

corte = alimentar(f, MUDO, SILENCIO_QUE_FECHA_MS + QUADRO)
conferir(corte is not None and corte.motivo == "pausa",
         "pausa longa fecha a fala",
         "é o que faz o texto aparecer enquanto a aula acontece")
assert corte is not None
conferir(corte.ms_uteis < corte.ms_no_buffer,
         "o trecho útil é MENOR que o acumulado",
         "o rabo de silêncio é justamente onde o modelo inventa")
conferir(corte.ms_uteis >= 1_200 and corte.ms_de_voz >= 1_200,
         "e carrega a voz inteira, as duas partes",
         "ms_uteis vai até a última voz, pausa interna incluída")
conferir(not f.aberta and f.ms_no_buffer == 0 and f.ms_de_voz == 0,
         "o fatiador volta ao zero depois do corte",
         "sobra de estado somaria a fala seguinte na anterior")

print()
print("4) quem fala sem pausar ainda aparece — em pedaços")
print()

f = Fatiador()
corte = alimentar(f, VOZ, FALA_MAXIMA_MS + QUADRO)
conferir(corte is not None and corte.motivo == "teto",
         f"corta no teto de {FALA_MAXIMA_MS // 1000} s mesmo sem pausa",
         "sem isto a tela fica vazia durante a apresentação do aluno")
assert corte is not None
conferir(corte.ms_uteis == corte.ms_no_buffer,
         "e aí não há silêncio a descartar")

print()
print("5) tosse e 'uhum' não valem uma chamada ao reconhecedor")
print()

f = Fatiador()
alimentar(f, VOZ, FALA_MINIMA_MS - 2 * QUADRO)
corte = alimentar(f, MUDO, SILENCIO_QUE_FECHA_MS + QUADRO)
conferir(corte is not None and not corte.vale,
         f"menos de {FALA_MINIMA_MS} ms de voz é descartado",
         "o reconhecedor custa, e sobre ruído ele inventa")

f = Fatiador()
alimentar(f, VOZ, FALA_MINIMA_MS + 4 * QUADRO)
corte = alimentar(f, MUDO, SILENCIO_QUE_FECHA_MS + QUADRO)
conferir(corte is not None and corte.vale,
         "e logo acima do mínimo vale",
         "o limiar não pode engolir resposta curta de verdade")

print()
print("6) quem desconecta não perde a última frase")
print()

f = Fatiador()
alimentar(f, VOZ, 1_000)
corte = f.fechar_agora()
conferir(corte is not None and corte.motivo == "saiu" and corte.vale,
         "sair da sala fecha o que estava aberto",
         "costuma ser a resposta que ninguém mais ouviu")
conferir(Fatiador().fechar_agora() is None,
         "e fechar o que não abriu não inventa fala",
         "senão cada participante que entra e sai geraria uma linha vazia")

print()
print("7) o texto que o reconhecedor devolve é fala de verdade?")
print()

conferir(not vale_gravar(""), "texto vazio não grava")
conferir(not vale_gravar("   "), "só espaço não grava")
conferir(not vale_gravar("Obrigado pela atenção"),
         "a frase-fantasma do Whisper não grava",
         "é o que ele escreve quando recebe silêncio")
conferir(not vale_gravar("Legendas pela comunidade Amara.org"),
         "nem a legenda de YouTube que ele aprendeu")
conferir(vale_gravar("Obrigado professor, eu acho que o risco é operacional"),
         "mas a fala REAL que começa igual grava",
         "a comparação é por texto inteiro, nunca por 'contém'")
conferir(vale_gravar("não"),
         "e uma resposta de uma palavra grava",
         "'não' é a resposta mais importante da sala")

print()
print("8) os limiares são coerentes entre si")
print()

conferir(0 < LIMIAR_DE_VOZ < 1, "limiar de voz é RMS normalizado (0..1)")
conferir(FALA_MINIMA_MS < SILENCIO_QUE_FECHA_MS < FALA_MAXIMA_MS,
         "mínima < silêncio que fecha < teto",
         "fora dessa ordem o fatiador corta antes de haver o que cortar")

FONTE = io.open(RAIZ / "segmentacao.py", encoding="utf-8").read()
for proibido in ("import httpx", "import numpy", "from livekit"):
    conferir(proibido not in FONTE,
             f"a regra não importa `{proibido.split()[-1]}`",
             "é o que mantém esta prova rodando sem áudio e sem rede")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

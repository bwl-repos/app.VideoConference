# -*- coding: utf-8 -*-
"""A prova do encontro configuravel mede o que diz medir?

    python -B provas/falsifica_template_do_encontro.py

Cada estrago abaixo e um defeito REAL que esta familia de mudancas permite, e
quase nenhum deles da erro em lugar nenhum:

- a tela configura um ritmo e a sala segue no antigo;
- o catalogo diverge de `STEPS` e o painel promete uma acao que o ▶ nao faz;
- a pausa desalinha do paragrafo e a sala cala no lugar errado;
- a voz muda e o audio da voz anterior continua sendo servido;
- o texto e aplicado na LEITURA e troca a instrucao no meio de uma aula.

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
PROVA = RAIZ / "provas/prova_template_do_encontro.py"

ENCONTRO = RAIZ / "app/services/encontro.py"
CADENCIA = RAIZ / "app/services/cadencia.py"
ROTA = RAIZ / "app/routers/encontro.py"
ROOMS = RAIZ / "app/routers/rooms.py"
FRONT = RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx"
SDK = RAIZ.parent / "frontend/src/lib/video-rooms-sdk.ts"

#: (rotulo, arquivo, trecho original, trecho estragado)
ESTRAGOS = [
    # ── 1. A BASE DEIXA DE SER O COMPORTAMENTO DE HOJE ──────────────────────
    ("a base ganha uma tabela de duracoes propria",
     ENCONTRO,
     '        "duracoes": dict(cadencia.DURACAO_DA_ETAPA),',
     '        "duracoes": {e: 300 for e in cadencia.ORDEM},'),

    ("o limiar de fabrica muda sem ninguem pedir",
     ENCONTRO,
     '        "limiar": float(cadencia.LIMIAR_DE_AVANCO),',
     '        "limiar": 0.66,'),

    ("`decidir` passa a EXIGIR parametros (quebra todo chamador antigo)",
     CADENCIA,
     "            params: Parametros = PADRAO) -> Decisao:",
     "            params: Parametros) -> Decisao:"),

    # ── 2. O CATALOGO DIVERGE DAS OUTRAS COPIAS ─────────────────────────────
    ("o catalogo perde uma etapa que a cadencia tem",
     ENCONTRO,
     '    "amplify_code":       {"titulo": "Registro de Presença",     "acao": "Ampliar o código da sessão",\n'
     '                           "secao": "abertura",    "blocos": "todos"},\n',
     ""),

    ("o catalogo anuncia uma acao que o ▶ nao executa",
     ENCONTRO,
     '"acao": "Mostrar gráfico"',
     '"acao": "Exibir o grafico de riscos"'),

    ("a secao de uma etapa diverge do mapa da tela",
     ENCONTRO,
     '    "groups":             {"titulo": "Aquecimento",              "acao": "Divisão em grupos",\n'
     '                           "secao": "aquecimento", "blocos": "todos"},',
     '    "groups":             {"titulo": "Aquecimento",              "acao": "Divisão em grupos",\n'
     '                           "secao": "plenaria",    "blocos": "todos"},'),

    ("a plenaria passa a falar a secao inteira (e a repetir na etapa seguinte)",
     ENCONTRO,
     '"secao": "plenaria",    "blocos": "primeiro"},',
     '"secao": "plenaria",    "blocos": "todos"},'),

    ("uma etapa aponta para uma secao que nao existe",
     ENCONTRO,
     '"secao": "feedback",    "blocos": "todos"},\n'
     '    "done":',
     '"secao": "encerramento", "blocos": "todos"},\n'
     '    "done":'),

    ("quem vota passa a ser uma lista escrita na mao",
     ENCONTRO,
     '            "vota": etapa not in cadencia.AVANCA_SOZINHA and etapa != "done"\n'
     '                    and c["duracoes"].get(etapa) is not None,',
     '            "vota": etapa not in ("session_start", "registration_open"),'),

    # ── 3. A PAUSA DESALINHA DO PARAGRAFO ───────────────────────────────────
    ("as pausas deixam de ser completadas pelo indice do paragrafo",
     ENCONTRO,
     '                "pausas": [_inteiro(pausas_vindas[i] if i < len(pausas_vindas) else PAUSA_PADRAO,\n'
     '                                    MIN_PAUSA, MAX_PAUSA, PAUSA_PADRAO)\n'
     '                           for i in range(len(paragrafos))],',
     '                "pausas": [_inteiro(p, MIN_PAUSA, MAX_PAUSA, PAUSA_PADRAO)\n'
     '                           for p in pausas_vindas],'),

    ("paragrafo em branco e descartado DEPOIS de casar com a pausa",
     ENCONTRO,
     '            paragrafos = [p for p in paragrafos if p]\n',
     ''),

    ("o player deixa de carregar a pausa junto da fala",
     FRONT,
     '    .flatMap((b) => (b.audios ?? []).map((url, i) => (url ? comPausa(url, b.pausas?.[i]) : "")))',
     '    .flatMap((b) => b.audios ?? [])'),

    ("o temporizador da pausa sobrevive a troca de etapa",
     FRONT,
     "      if (espera !== undefined) window.clearTimeout(espera);\n",
     ""),

    ("um 404 passa a esperar a pausa de uma fala que nao aconteceu",
     FRONT,
     "      const ms = honrarPausa ? pausaDoItem(lista[i]) : 0;",
     "      const ms = pausaDoItem(lista[i]);"),

    ("o SDK deixa de declarar a pausa",
     SDK,
     "  pausas?: number[];\n",
     ""),

    # ── 4. A VOZ ────────────────────────────────────────────────────────────
    ("o perfil deixa de distinguir as vozes",
     ENCONTRO,
     '    partes = [str(v.get("provedor") or ""), str(v.get("voz") or "")]',
     '    partes = [str(v.get("provedor") or "")]'),

    ("a voz de fabrica deixa de ser a de hoje",
     ENCONTRO,
     '    "voz": "Camila",\n    "motor": "generative",',
     '    "voz": "Thiago",\n    "motor": "neural",'),

    ("o motor viaja para o ElevenLabs, que o ignora",
     ENCONTRO,
     '        "motor": (str(voz_bruta.get("motor") or VOZ_PADRAO["motor"]).strip()\n'
     '                  if provedor == "polly" else ""),',
     '        "motor": str(voz_bruta.get("motor") or VOZ_PADRAO["motor"]).strip(),'),

    ("o pedido ao CoreService deixa de dizer qual voz",
     ENCONTRO,
     '    pedido = {"provedor": str(v.get("provedor") or "polly"),\n'
     '              "voz": str(v.get("voz") or "")}',
     '    pedido = {"provedor": str(v.get("provedor") or "polly")}'),

    ("a leitura da sala volta a assinar sem o perfil da voz",
     ROOMS,
     "        return _voz.com_audios(roteiro, _voz_porta.assinar,\n"
     "                               _encontro.perfil_da_voz())",
     "        return _voz.com_audios(roteiro, _voz_porta.assinar)"),

    # ── 5. A VALIDACAO DEIXA PASSAR O QUE QUEBRA O ENCONTRO ─────────────────
    ("duracao zero passa (a etapa vence no instante em que comeca)",
     ENCONTRO,
     "MIN_DURACAO, MAX_DURACAO = 10, 7200",
     "MIN_DURACAO, MAX_DURACAO = 0, 7200"),

    ("limiar 1,0 passa (nenhuma sala avanca, nunca)",
     ENCONTRO,
     "    limiar = max(0.0, min(0.95, limiar))",
     "    limiar = max(0.0, min(1.0, limiar))"),

    ("etapa fora do vocabulario e gravada",
     ENCONTRO,
     "    for etapa in cadencia.ORDEM:\n"
     "        bruto = das_entradas.get(etapa, padrao[\"duracoes\"].get(etapa))",
     "    for etapa in list(cadencia.ORDEM) + list(das_entradas):\n"
     "        bruto = das_entradas.get(etapa, padrao[\"duracoes\"].get(etapa))"),

    ("campo mal digitado passa a derrubar o formulario",
     ENCONTRO,
     "    except (TypeError, ValueError):\n        return padrao\n    return max(piso, min(teto, n))",
     "    except (TypeError, ValueError):\n        raise\n    return max(piso, min(teto, n))"),

    # ── 6. O TEXTO DEIXA DE CONGELAR ────────────────────────────────────────
    ("o template passa a ser casado bloco a bloco (sobra o texto antigo)",
     ENCONTRO,
     '        secao["blocosFixos"] = [\n'
     '            {"titulo": b["titulo"], "lista": b["lista"],\n'
     '             "paragrafos": list(b["paragrafos"]), "pausas": list(b["pausas"])}\n'
     '            for b in nova["blocos"]\n'
     '        ]',
     '        for i, b in enumerate(nova["blocos"]):\n'
     '            if i < len(secao["blocosFixos"]):\n'
     '                secao["blocosFixos"][i] = {\n'
     '                    "titulo": b["titulo"], "lista": b["lista"],\n'
     '                    "paragrafos": list(b["paragrafos"]), "pausas": list(b["pausas"])}\n'
     '            else:\n'
     '                secao["blocosFixos"].append(dict(b))'),

    ("a pausa configurada nao viaja no retrato da sala",
     ENCONTRO,
     '             "paragrafos": list(b["paragrafos"]), "pausas": list(b["pausas"])}',
     '             "paragrafos": list(b["paragrafos"])}'),

    ("o template deixa de ser aplicado na criacao da sala",
     ROOMS,
     "    if body.roteiro:\n"
     "        body.roteiro = _encontro.aplicar_no_roteiro(\n"
     "            body.roteiro, await _encontro.carregar())\n",
     ""),

    ("a secao que o template nao conhece e apagada",
     ENCONTRO,
     "        nova = por_chave.get(secao.get(\"key\"))\n        if nova is None:\n            continue",
     "        nova = por_chave.get(secao.get(\"key\")) or {\"blocos\": []}",),

    ("o conteudo do episodio passa a ser sobrescrito",
     ENCONTRO,
     '    por_chave = {s["key"]: s for s in c["secoes"]}\n',
     '    por_chave = {s["key"]: s for s in c["secoes"]}\n'
     '    roteiro["campos"] = {}\n'),

    # ── 7. QUEM PODE CONFIGURAR ─────────────────────────────────────────────
    ("a previa da voz fica aberta a quem tiver a URL",
     ROTA,
     "async def previa(corpo: Previa, _admin: dict = Depends(require_admin)):",
     "async def previa(corpo: Previa):"),

    ("as rotas saem de /api/admin (e o cookie deixa de chegar)",
     ROTA,
     'router = APIRouter(prefix="/api/admin/encontro", tags=["admin:encontro"])',
     'router = APIRouter(prefix="/api/encontro", tags=["admin:encontro"])'),
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

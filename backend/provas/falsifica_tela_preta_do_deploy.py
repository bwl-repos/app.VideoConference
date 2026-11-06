# -*- coding: utf-8 -*-
"""A prova da tela preta mede o que diz medir?

    python -B provas/falsifica_tela_preta_do_deploy.py

Todo estrago aqui devolve o defeito de 06/11/2026: o navegador com o
`index.html` de antes do deploy pede um arquivo que nao existe mais, recebe
HTML com status 200, o `import()` falha e a tela fica PRETA -- sem erro na
tela e sem erro no log do servidor.

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
PROVA = RAIZ / "provas/prova_tela_preta_do_deploy.py"

CADDY = RAIZ.parent / "infra/deploy/app/Caddyfile"
MAIN = RAIZ.parent / "frontend/src/main.tsx"

#: (rotulo, arquivo, trecho original, trecho estragado)
ESTRAGOS = [
    # ── O DEFEITO REAL, do jeito que ele existia ────────────────────────────
    ("o chunk que sumiu volta a responder o index.html com 200",
     CADDY,
     "\thandle /assets/* {\n"
     '\t\theader Cache-Control "public, max-age=31536000, immutable"\n'
     "\t\tfile_server\n"
     "\t}\n",
     ""),

    ("ou o /assets ganha o fallback de SPA de volta",
     CADDY,
     "\thandle /assets/* {\n"
     '\t\theader Cache-Control "public, max-age=31536000, immutable"\n'
     "\t\tfile_server\n",
     "\thandle /assets/* {\n"
     '\t\theader Cache-Control "public, max-age=31536000, immutable"\n'
     "\t\ttry_files {path} /index.html\n"
     "\t\tfile_server\n"),

    ("o index volta a nao dizer nada sobre cache",
     CADDY,
     '\t\theader Cache-Control "no-cache"\n\t\ttry_files',
     "\t\ttry_files"),

    ("o arquivo com hash perde o cache longo (baixado a cada carga)",
     CADDY,
     '\t\theader Cache-Control "public, max-age=31536000, immutable"\n',
     ""),

    # ── O CONTROLE: o Caddyfile continua servindo o que ja servia ───────────
    ("o proxy do backend some do Caddyfile",
     CADDY,
     "\t\treverse_proxy backend:8000\n",
     "\t\trespond 503\n"),

    ("as rotas da SPA param de cair no index (abrir /admin vira 404)",
     CADDY,
     "\t\ttry_files {path} /index.html\n",
     ""),

    ("a raiz do estatico some",
     CADDY,
     "\troot * /srv\n",
     ""),

    # ── O CLIENTE DEIXA DE SE RECUPERAR ─────────────────────────────────────
    ("o entry deixa de escutar a falha de carregamento",
     MAIN,
     'window.addEventListener("vite:preloadError" as any, (e: Event) => {',
     "const naoEscutaMais = ((e: Event) => {"),

    ("a recarga perde a guarda (e vira laco infinito)",
     MAIN,
     "    if (sessionStorage.getItem(MARCA_DE_RECARGA)) return false;\n"
     '    sessionStorage.setItem(MARCA_DE_RECARGA, "1");\n'
     "    return true;",
     "    return true;"),

    ("sem sessionStorage ela passa a recarregar assim mesmo",
     MAIN,
     "  } catch {\n"
     "    // Sem `sessionStorage` (aba anônima com armazenamento bloqueado) não há\n"
     "    // como lembrar que já tentamos, e recarregar viraria laço. Mostra o aviso.\n"
     "    return false;\n"
     "  }",
     "  } catch {\n"
     "    return true;\n"
     "  }"),

    ("esgotada a recarga, a tela volta a ficar preta",
     MAIN,
     "  if (podeRecarregar()) window.location.reload();\n"
     "  else avisarQueFaltaRecarregar();",
     "  if (podeRecarregar()) window.location.reload();"),

    ("o aviso perde o botao que limpa a marca (recarrega para o mesmo aviso)",
     MAIN,
     "    try { sessionStorage.removeItem(MARCA_DE_RECARGA); } catch { /* sem storage */ }\n",
     ""),

    ("o aviso vira uma caixa vazia",
     MAIN,
     "        <div style=\"font-size:17px;font-weight:600\">Esta página está desatualizada</div>",
     '        <div style="font-size:17px;font-weight:600"></div>'),

    # ── E A PROSA NAO PODE SUSTENTAR A AFIRMACAO ────────────────────────────
    #
    # O comentario do Caddyfile EXPLICA o defeito, entao cita `try_files` e
    # `index.html`. Se a prova lesse o arquivo cru, apagar a configuracao e
    # deixar so o comentario a manteria VERDE. Este estrago e o que prova que
    # ela tira o comentario antes de afirmar.
    ("a configuracao vira comentario (so a prosa sobra)",
     CADDY,
     "\thandle {\n"
     '\t\theader Cache-Control "no-cache"\n'
     "\t\ttry_files {path} /index.html\n"
     "\t\tfile_server\n"
     "\t}\n",
     "\t# handle {\n"
     '\t#\theader Cache-Control "no-cache"\n'
     "\t#\ttry_files {path} /index.html\n"
     "\t#\tfile_server\n"
     "\t# }\n"),
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

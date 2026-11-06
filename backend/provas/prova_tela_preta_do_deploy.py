# -*- coding: utf-8 -*-
"""A tela preta de quem abre o site com a aba de antes do deploy.

    python -B provas/prova_tela_preta_do_deploy.py

## O defeito, que o servidor não vê

Toda tela do produto entra por `import()`, e o nome do arquivo carrega o hash do
conteúdo. Um deploy publica nomes novos e **apaga os antigos**. O navegador que
guardou o `index.html` de ontem pede um arquivo que não existe mais — e o
`try_files {path} /index.html` do Caddy respondia o índice no lugar: **200, com
`text/html`**, onde o navegador esperava um módulo JavaScript.

O `import()` falha, o React não monta nada, e como o `body` tem fundo escuro o
resultado é uma **tela preta**. Do lado do servidor não há erro nenhum: ele
respondeu 200 para tudo. Do lado do usuário não há mensagem nenhuma.

Aconteceu em 06/11/2026, no deploy do painel de configuração do encontro: quem
recarregou viu o login, quem não recarregou viu preto.

## O que isto protege

1. **`/assets/*` não cai no fallback de SPA.** Arquivo ausente vira **404**, que
   é a verdade — e é o que faz o `vite:preloadError` disparar no cliente.
2. **O HTML revalida sempre** (`no-cache`), e os arquivos com hash no nome são
   `immutable`. Sem cabeçalho nenhum o navegador inventa a validade e segura o
   índice velho por horas.
3. **A recarga automática é UMA.** Se o módulo continuar faltando, o problema
   não é cache, e recarregar de novo seria um laço infinito.
4. **Depois dessa recarga a tela FALA.** Preto não é uma mensagem.
5. **O proxy do `/api` continua de pé** — é o controle: mexer no Caddyfile não
   pode ter derrubado o que já funcionava.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent

falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-60s %s" % ("ok" if cond else "FALHA", oque, porque))


def ler(caminho: str) -> str:
    return io.open(RAIZ.parent / caminho, encoding="utf-8").read()


def sem_comentario_caddy(texto: str) -> str:
    """Só o que o Caddy executa.

    OBRIGATÓRIO, e não zelo: o comentário deste Caddyfile EXPLICA o defeito, e
    portanto cita `try_files` e `index.html` ao descrevê-lo. Uma afirmação feita
    sobre o arquivo cru casaria com a explicação do defeito em vez da correção —
    e ficaria verde justamente com o defeito de volta. Foi o que aconteceu na
    primeira versão desta prova.
    """
    return "\n".join(l for l in texto.splitlines() if not l.strip().startswith("#"))


def sem_comentario_ts(texto: str) -> str:
    """Idem, para o TypeScript: fora as linhas `//`.

    Só as linhas `//`, e NÃO os blocos `/* */` por regex: um `/* ... */` com
    `re.S` casa do primeiro `/*` até o primeiro `*/` que encontrar, e num
    arquivo de verdade isso atravessa código — a primeira versão desta função
    apagou a própria função que a prova mede, e a prova quebrou em vez de ficar
    verde. (Quebrar foi sorte: o mesmo erro apagando OUTRO trecho teria deixado
    uma afirmação sobre um texto vazio.)
    """
    return "\n".join(l for l in texto.splitlines()
                     if not l.strip().startswith("//"))


CADDY = sem_comentario_caddy(ler("infra/deploy/app/Caddyfile"))
MAIN = sem_comentario_ts(ler("frontend/src/main.tsx"))

print("A tela preta de quem abre o site com a aba de antes do deploy")
print()
print("1) o servidor diz a VERDADE sobre um arquivo que nao existe mais")

bloco_assets = re.search(r"handle /assets/\*\s*\{(.*?)\n\t\}", CADDY, re.S)
conferir(bloco_assets is not None,
         "`/assets/*` tem tratamento proprio no Caddyfile",
         "sem ele, o chunk que sumiu responde o index.html com status 200")
corpo_assets = bloco_assets.group(1) if bloco_assets else ""
conferir("try_files" not in corpo_assets and "file_server" in corpo_assets,
         "e NAO usa o fallback de SPA: arquivo ausente vira 404",
         "HTML onde o navegador espera um modulo = tela preta, sem erro nenhum")

print()
print("2) os cabecalhos de cache")

conferir("immutable" in corpo_assets and "max-age=31536000" in corpo_assets,
         "arquivo com hash no nome e `immutable`",
         "o nome carrega o hash do conteudo: ele nunca muda")
fallback = CADDY[CADDY.index("try_files"):]
conferir('header Cache-Control "no-cache"' in CADDY
         and CADDY.index('header Cache-Control "no-cache"') < CADDY.index("try_files"),
         "o HTML revalida sempre (`no-cache` no handle do fallback)",
         "sem cabecalho, o navegador inventa a validade e segura o index velho")

print()
print("3) o cliente se recupera, e no maximo UMA vez")

conferir('addEventListener("vite:preloadError"' in MAIN,
         "o entry escuta a falha de carregamento de modulo",
         "a defesa e no ponto de entrada, nao por rota")
telas = len(re.findall(r"lazy\(\(\) => import\(", MAIN))
conferir(telas >= 5,
         "e cobre as %d telas carregadas sob demanda de uma vez" % telas,
         "um tratamento por rota deixaria a proxima rota nova descoberta")
conferir("sessionStorage.getItem(MARCA_DE_RECARGA)" in MAIN
         and "sessionStorage.setItem(MARCA_DE_RECARGA" in MAIN,
         "a recarga e marcada antes de acontecer",
         "sem a marca, o modulo que falta de verdade vira laco infinito")
recarrega = MAIN[MAIN.index("function podeRecarregar"):]
recarrega = recarrega[:recarrega.index("function avisarQueFaltaRecarregar")]
conferir("return false" in recarrega.split("catch")[-1],
         "e sem `sessionStorage` ela NAO acontece",
         "aba anonima sem storage nao lembra a tentativa: recarregar seria laco")
conferir("else avisarQueFaltaRecarregar()" in MAIN,
         "esgotada a recarga, a tela DIZ o que houve",
         "preto nao e uma mensagem")
aviso = MAIN[MAIN.index("function avisarQueFaltaRecarregar"):]
aviso = aviso[:aviso.index("window.addEventListener")]
conferir("desatualizada" in aviso and "Recarregar" in aviso,
         "com texto em portugues e um botao de recarregar",
         "quem ve a tela nao sabe o que e um chunk")
conferir("sessionStorage.removeItem(MARCA_DE_RECARGA)" in aviso,
         "e o botao limpa a marca antes de recarregar",
         "senao o clique recarrega para o mesmo aviso, para sempre")

print()
print("4) CONTROLE: o que ja funcionava continua de pe")

conferir("reverse_proxy backend:8000" in CADDY
         and "path /api/* /ws/* /health" in CADDY,
         "o /api, o /ws e o /health continuam indo para o backend",
         "mexer no Caddyfile nao pode derrubar o que ja estava certo")
conferir("try_files {path} /index.html" in CADDY,
         "e as ROTAS da SPA continuam caindo no index",
         "sem isso, abrir /admin direto na barra de enderecos vira 404")
conferir("root * /srv" in CADDY,
         "a raiz do estatico continua declarada")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

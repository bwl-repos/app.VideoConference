# -*- coding: utf-8 -*-
"""Cria os fluxogramas do backend DENTRO de um quadro do Miro, pela API REST.

    set MIRO_TOKEN=...                       (ou --token-arquivo caminho.txt)
    python -B docs/miro_fluxograma.py --board uXjVKabc123=        # só mostra o plano
    python -B docs/miro_fluxograma.py --board uXjVKabc123= --aplicar
    python -B docs/miro_fluxograma.py --board uXjVKabc123= --limpar

## Por que um gerador, e não um desenho

A fonte é `docs/backend-mermaid.md` -- o MESMO arquivo que a página publicada
usa. Desenhar à mão no Miro criaria uma segunda versão do mecanismo, e a que
ninguém olha é justamente a que fica no quadro da reunião. Aqui, mexer no
mermaid e rodar de novo refaz o quadro.

## O token

Nunca é impresso, nunca entra em argumento de linha de comando que apareça no
histórico do shell (`--token-arquivo` lê de um arquivo; `MIRO_TOKEN` lê do
ambiente). Como obter, uma vez:

  1. developers.miro.com -> seu time de desenvolvimento -> **Create new app**
  2. em Permissions, marque **boards:read** e **boards:write**
  3. **Install app and get OAuth token** -> escolha o time -> Install & authorize
  4. copie o token para um arquivo e aponte `--token-arquivo` para ele

Se marcar "Expire user authorization token" na criação do app, o token vale 1
hora -- e essa escolha não dá para mudar depois.

## O id do quadro

Está na URL: `miro.com/app/board/<ID>/`. O app instalado precisa ter acesso ao
time onde o quadro vive.

## O que a API aceita, e o que ela NÃO aceita

- As formas de fluxograma (`flow_chart_process`, `flow_chart_decision`) só
  existem no endpoint EXPERIMENTAL de forma única,
  `POST /v2-experimental/boards/{id}/shapes`. O criador em lote
  (`/v2/boards/{id}/items/bulk`, 20 por chamada) não as aceita -- a lista de
  formas dele não tem nenhuma `flow_chart_*` fora de `predefined_process`.
  Então as formas vão UMA A UMA, de propósito.
- Conectores não existem em lote, em nenhuma hipótese.
- `fillColor` aceita só uma paleta fixa de 16 cores. Mandar um hex de fora
  (o nosso âmbar, por exemplo) é 400 -- ver `PALETA`.
- `captions` e `strokeStyle` do conector não estão no esquema público que eu
  consegui ler. Então são enviados e, se a API recusar, a chamada é repetida
  SEM eles e o rótulo perdido é listado no fim. Rótulo perdido em silêncio
  seria pior: uma seta sem rótulo quer dizer "relacionado de algum jeito".

## Rodar duas vezes duplica, e é por isso que existe o manifesto

Cada execução grava os ids criados em `docs/.miro_manifesto.json`. `--limpar`
apaga o que ESTA ferramenta criou naquele quadro, e só isso -- nada de varrer
o quadro inteiro, que pode ter trabalho de gente.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AQUI = os.path.dirname(os.path.abspath(__file__))
FONTE = os.path.join(AQUI, "backend-mermaid.md")
MANIFESTO = os.path.join(AQUI, ".miro_manifesto.json")

BASE = "https://api.miro.com"
#: As formas de fluxograma vivem no caminho experimental. O estável
#: (`/v2/.../shapes`) existe, mas a lista de formas dele não tem as de
#: fluxograma -- ver a docstring.
ROTA_FORMA = "/v2-experimental/boards/%s/shapes"
ROTA_LOTE = "/v2/boards/%s/items/bulk"
ROTA_CONECTOR = "/v2/boards/%s/connectors"
ROTA_ITEM = "/v2/boards/%s/items/%s"

#: As 16 cores que `fillColor` aceita. Qualquer outra é 400.
PALETA = {
    "cinza": "#f5f6f8", "verde_claro": "#d5f692", "verde": "#93d275",
    "turquesa": "#67c6c0", "azul": "#23bfe7", "azul_claro": "#a6ccf5",
    "anil": "#7b92ff", "amarelo": "#fff9b1", "ouro": "#f5d128",
    "laranja": "#ff9d48", "vermelho": "#f16c7f", "rosa": "#ea94bb",
    "roxo": "#b384bb", "preto": "#000000",
}

#: Como cada caixa é pintada. É uma legenda DE VERDADE: a mesma codificação
#: repetida nos sete diagramas, e por isso vale a pena existir. A ordem
#: importa -- a primeira regra que casar ganha.
#:
#: Editar aqui muda os sete quadros de uma vez.
REGRAS_DE_COR = [
    ("decisao",   None,                                                   "amarelo"),
    ("banco",     ("UPDATE", "INSERT", "UPSERT", "SELECT", "grava"),       "verde_claro"),
    ("recusa",    ("403", "404", "401", "502", "WARNING", "não avança",
                   "NÃO avança", "nada -", "nada<", "erro"),              "vermelho"),
    ("externo",   ("integration", "LiveKit", "SFU", "S3", "webhook",
                   "egress", "ContentBuilder", "LRS", "Rise", "chat."),   "roxo"),
    ("host",      ("host:", "facilitador", "participante", "aluno:"),     "laranja"),
]
COR_PADRAO = "azul_claro"
COR_CILINDRO = "cinza"

#: Geometria da grade. Generosa de propósito: quem abre o quadro vai arrastar
#: caixa, e caixa colada em caixa não dá para arrastar.
L_CAIXA, A_CAIXA = 300, 120
PASSO_RANK = 260          # entre níveis (sentido do fluxo)
PASSO_ORDEM = 360         # entre irmãos do mesmo nível
GAP_DIAGRAMA = 900        # entre um diagrama e o seguinte
ALTURA_TITULO = 120


# ── parser do subconjunto de mermaid que nós escrevemos ───────────────────────
#
# Não é um parser de mermaid: é o parser DO NOSSO mermaid. Reconhece o que os
# sete diagramas usam e recusa o resto em voz alta, em vez de adivinhar.

SETAS = ("<-->", "-.->", "-->")
RE_NO = re.compile(
    r'^(?P<id>[A-Za-z_][\w]*)\s*(?:(?P<ab>\[\(|\[|\{)(?P<rot>.*?)(?P<fe>\)\]|\]|\}))?$')


def fatiar(linha: str) -> list:
    """`A[..] -->|"x"| B[..] --> C[..]` → [nó, (seta, rótulo), nó, (seta, ""), nó].

    Varredura caractere a caractere, e não um `re.match` com uma seta: a
    primeira versão disto casava UMA seta por linha, e o resto da cadeia caía
    dentro do rótulo do segundo nó -- `RE_NO` aceitava porque o `]` final da
    linha fechava o colchete. O diagrama das etapas virou 9 caixas em vez de
    14, sem erro nenhum. É o defeito que este arquivo inteiro existe para não
    ter: um quadro plausível e errado.

    As aspas são respeitadas: um rótulo que contenha `-->` não vira seta.
    """
    partes, i, atual, aspas = [], 0, "", False
    while i < len(linha):
        c = linha[i]
        if c == '"':
            aspas = not aspas
            atual += c
            i += 1
            continue
        if not aspas:
            seta = next((s for s in SETAS if linha.startswith(s, i)), None)
            if seta:
                partes.append(atual.strip())
                atual = ""
                i += len(seta)
                while i < len(linha) and linha[i] == " ":
                    i += 1
                rotulo = ""
                if i < len(linha) and linha[i] == "|":
                    fim = linha.find("|", i + 1)
                    if fim == -1:
                        raise SystemExit("rótulo de seta sem fechar: %r" % linha)
                    rotulo = linha[i + 1:fim]
                    i = fim + 1
                partes.append((seta, rotulo))
                continue
        atual += c
        i += 1
    partes.append(atual.strip())
    return partes


def _texto(bruto: str) -> str:
    t = (bruto or "").strip()
    if t.startswith('"') and t.endswith('"'):
        t = t[1:-1]
    return t.replace("<br/>", "\n").replace("<br>", "\n").strip()


class Diagrama:
    def __init__(self, titulo: str):
        self.titulo = titulo
        self.direcao = "TD"
        self.rotulos: dict[str, str] = {}
        self.formas: dict[str, str] = {}      # id -> processo | decisao | cilindro
        self.arestas: list[tuple[str, str, str, bool]] = []   # a, b, rotulo, tracejada

    def ver_no(self, bruto: str) -> str:
        # Seta sobrando dentro de um "nó" = a fatia veio errada. Recusar alto:
        # era este silêncio que produzia o diagrama com caixas de menos.
        if any(s in bruto for s in SETAS):
            raise SystemExit("seta dentro do nó %r em %r — fatiamento errado"
                             % (bruto, self.titulo))
        m = RE_NO.match(bruto.strip())
        if not m:
            raise SystemExit("não entendi o nó %r em %r" % (bruto, self.titulo))
        nid = m.group("id")
        if m.group("ab"):
            self.rotulos[nid] = _texto(m.group("rot"))
            self.formas[nid] = {"[(": "cilindro", "{": "decisao", "[": "processo"}[m.group("ab")]
        self.rotulos.setdefault(nid, nid)
        self.formas.setdefault(nid, "processo")
        return nid


def ler_diagramas(caminho: str) -> list[Diagrama]:
    texto = io.open(caminho, encoding="utf-8").read()
    saida: list[Diagrama] = []
    titulo, dentro, linhas = "", False, []

    def fechar():
        if not linhas:
            return
        d = Diagrama(titulo or "diagrama")
        for linha in linhas:
            s = linha.strip()
            if not s or s.startswith("%%"):
                continue
            if s.startswith("flowchart"):
                d.direcao = "LR" if "LR" in s else "TD"
                continue
            # `subgraph` e `end` só agrupam visualmente no mermaid. Aqui o
            # agrupamento não é recriado: `frame` da API tem esquema que eu não
            # consegui conferir, e inventar um quadro errado é pior que não ter.
            if s.startswith(("subgraph", "end", "direction")):
                continue
            fatias = fatiar(s)
            if len(fatias) == 1:
                d.ver_no(fatias[0])
                continue
            # Cadeia: `A --> B --> C` são duas arestas, não uma.
            anterior = d.ver_no(fatias[0])
            for k in range(1, len(fatias), 2):
                seta, rotulo = fatias[k]
                atual = d.ver_no(fatias[k + 1])
                d.arestas.append((anterior, atual, _texto(rotulo), seta == "-.->"))
                anterior = atual
        saida.append(d)

    for linha in texto.splitlines():
        if linha.startswith("## "):
            titulo = linha[3:].strip()
        elif linha.strip() == "```mermaid":
            dentro, linhas = True, []
        elif linha.strip() == "```" and dentro:
            dentro = False
            fechar()
        elif dentro:
            linhas.append(linha)
    return saida


# ── layout em camadas ─────────────────────────────────────────────────────────

def posicionar(d: Diagrama) -> dict[str, tuple[float, float]]:
    """Caminho mais longo para o nível, ordem de aparição para a faixa.

    Não minimiza cruzamento: isto põe as caixas num lugar defensável e deixa o
    ajuste fino para quem abrir o quadro -- que é justamente o que se faz num
    Miro. Um layout ótimo aqui seria trabalho jogado fora no primeiro arrasto.
    """
    nos = list(dict.fromkeys(
        [n for a, b, _, _ in d.arestas for n in (a, b)] + list(d.rotulos)))
    saida_de = defaultdict(list)
    grau_entrada = {n: 0 for n in nos}
    for a, b, _, _ in d.arestas:
        saida_de[a].append(b)
        grau_entrada[b] += 1

    nivel = {n: 0 for n in nos}
    fila = deque([n for n in nos if grau_entrada[n] == 0]) or deque(nos[:1])
    visto, voltas = set(), 0
    while fila and voltas < len(nos) * 12:
        voltas += 1
        n = fila.popleft()
        visto.add(n)
        for m in saida_de[n]:
            if nivel[m] < nivel[n] + 1:
                nivel[m] = nivel[n] + 1
            # Ciclo: o nível já subiu, não se enfileira de novo para sempre.
            if m not in visto or nivel[m] <= len(nos):
                fila.append(m)
                visto.add(m)

    por_nivel = defaultdict(list)
    for n in nos:
        por_nivel[nivel[n]].append(n)

    pos = {}
    for nv, membros in sorted(por_nivel.items()):
        largura = (len(membros) - 1) * PASSO_ORDEM
        for i, n in enumerate(membros):
            desloca = i * PASSO_ORDEM - largura / 2
            if d.direcao == "LR":
                pos[n] = (nv * (PASSO_ORDEM + 60), desloca)
            else:
                pos[n] = (desloca, nv * PASSO_RANK)
    return pos


def cor_de(d: Diagrama, nid: str) -> str:
    if d.formas[nid] == "cilindro":
        return PALETA[COR_CILINDRO]
    if d.formas[nid] == "decisao":
        return PALETA["amarelo"]
    rotulo = d.rotulos[nid]
    for _, chaves, cor in REGRAS_DE_COR:
        if chaves and any(k in rotulo for k in chaves):
            return PALETA[cor]
    return PALETA[COR_PADRAO]


FORMA_MIRO = {"processo": "flow_chart_process",
              "decisao": "flow_chart_decision",
              "cilindro": "can"}


# ── cliente HTTP ──────────────────────────────────────────────────────────────

class Miro:
    def __init__(self, token: str, board: str):
        self._t = token
        self.board = board
        self.chamadas = 0

    def _pedir(self, metodo: str, rota: str, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(BASE + rota, data=dados, method=metodo)
        req.add_header("Authorization", "Bearer " + self._t)
        req.add_header("Accept", "application/json")
        if dados:
            req.add_header("Content-Type", "application/json")
        for tentativa in range(5):
            try:
                self.chamadas += 1
                with urllib.request.urlopen(req, timeout=30) as r:
                    bruto = r.read().decode("utf-8") or "{}"
                    return json.loads(bruto) if bruto.strip() else {}
            except urllib.error.HTTPError as e:
                corpo_erro = (e.read() or b"").decode("utf-8", "replace")[:400]
                # 429: a API diz quando os créditos voltam. Nível 2 = 100
                # créditos por chamada, teto de 1000 chamadas/min -- os ~130
                # itens daqui não chegam perto, mas o laço existe porque o teto
                # é por usuário E por aplicativo, e pode haver outra coisa
                # rodando com o mesmo token.
                if e.code == 429 and tentativa < 4:
                    espera = 2 ** tentativa * 3
                    print("   429: esperando %ds" % espera)
                    time.sleep(espera)
                    continue
                raise MiroErro(e.code, corpo_erro)
            except urllib.error.URLError as e:
                if tentativa < 4:
                    time.sleep(2 ** tentativa)
                    continue
                raise SystemExit("rede: %s" % e)
        raise SystemExit("desisti depois de 5 tentativas em %s" % rota)

    def forma(self, *, conteudo, forma, x, y, w, h, cor) -> str:
        r = self._pedir("POST", ROTA_FORMA % self.board, {
            "data": {"content": conteudo, "shape": forma},
            "style": {"fillColor": cor, "borderColor": "#1a1a1a",
                      "borderWidth": "1.0", "color": "#1a1a1a",
                      "fontFamily": "arial", "fontSize": "12",
                      "textAlign": "center", "textAlignVertical": "middle"},
            "position": {"x": x, "y": y, "origin": "center"},
            "geometry": {"width": w, "height": h},
        })
        return str(r.get("id"))

    def texto(self, *, conteudo, x, y, largura, tamanho="24") -> str:
        r = self._pedir("POST", ROTA_LOTE % self.board, [{
            "type": "text",
            "data": {"content": conteudo},
            "style": {"color": "#1a1a1a", "fontSize": tamanho, "textAlign": "left"},
            "position": {"x": x, "y": y, "origin": "center"},
            "geometry": {"width": largura},
        }])
        itens = r.get("data") or r.get("items") or []
        return str(itens[0]["id"]) if itens else ""

    def conector(self, a: str, b: str, rotulo: str, tracejada: bool):
        """Devolve (id, rotulo_perdido).

        `captions` e `strokeStyle` não estão no esquema público que eu consegui
        ler. Então: tenta com eles, e se a API recusar o CORPO (400), repete sem
        eles e devolve o rótulo como perdido. Fingir que a seta tem rótulo é o
        único resultado inaceitável aqui.
        """
        base = {"startItem": {"id": a, "snapTo": "auto"},
                "endItem": {"id": b, "snapTo": "auto"},
                "shape": "elbowed",
                "style": {"strokeColor": "#4a4a4a", "strokeWidth": "1.0"}}
        rico = json.loads(json.dumps(base))
        if rotulo:
            rico["captions"] = [{"content": rotulo[:200]}]
        if tracejada:
            rico["style"]["strokeStyle"] = "dashed"
        try:
            return str(self._pedir("POST", ROTA_CONECTOR % self.board, rico).get("id")), ""
        except MiroErro as e:
            if e.codigo != 400 or (not rotulo and not tracejada):
                raise
            r = self._pedir("POST", ROTA_CONECTOR % self.board, base)
            return str(r.get("id")), rotulo

    def apagar(self, item_id: str):
        """Apaga pela rota genérica e, no 400, pela experimental.

        A forma de fluxograma é assimétrica: nasce em
        `/v2-experimental/.../shapes`, e a rota genérica de item responde 400
        "Operation not supported" tanto para LER quanto para APAGAR. Medido
        contra a API: `--limpar` tirou os 14 conectores e deixou as 14 caixas
        no quadro. Sem este recuo, desfazer fica pela metade e volta a ser
        trabalho manual -- que é exatamente o que o manifesto existe para
        evitar.
        """
        try:
            self._pedir("DELETE", ROTA_ITEM % (self.board, item_id))
        except MiroErro as e:
            if e.codigo != 400:
                raise
            self._pedir("DELETE", (ROTA_FORMA % self.board) + "/" + item_id)


class MiroErro(Exception):
    def __init__(self, codigo: int, corpo: str):
        super().__init__("HTTP %d: %s" % (codigo, corpo))
        self.codigo = codigo
        self.corpo = corpo


# ── manifesto ─────────────────────────────────────────────────────────────────

def ler_manifesto() -> dict:
    if os.path.exists(MANIFESTO):
        return json.loads(io.open(MANIFESTO, encoding="utf-8").read() or "{}")
    return {}


def gravar_manifesto(m: dict):
    io.open(MANIFESTO, "w", encoding="utf-8", newline="\n").write(
        json.dumps(m, indent=2, ensure_ascii=False))


# ── principal ─────────────────────────────────────────────────────────────────

def token_de(args) -> str:
    if args.token_arquivo:
        t = io.open(args.token_arquivo, encoding="utf-8").read().strip()
        if not t:
            raise SystemExit("o arquivo do token está vazio: %s" % args.token_arquivo)
        return t
    t = os.environ.get("MIRO_TOKEN", "").strip()
    if not t:
        raise SystemExit(
            "falta o token. Ponha em MIRO_TOKEN ou use --token-arquivo caminho.txt\n"
            "Como obter: developers.miro.com -> Create new app -> permissões "
            "boards:read e boards:write -> Install app and get OAuth token.")
    return t


def conferir() -> int:
    """Confere o que dá para conferir sem token: parse, layout e paleta.

    Existe porque uma execução de verdade são ~250 chamadas contra um quadro
    real, e o erro que eu já cometi aqui (cadeia `A --> B --> C` colapsada numa
    caixa) não dava erro: dava um quadro plausível com caixas de menos. Isto
    roda em meio segundo e não toca na rede.
    """
    falhas = []

    def ok(cond, oque, porque=""):
        print("  %-6s %-54s %s" % ("ok" if cond else "FALHOU", oque, porque))
        if not cond:
            falhas.append(oque)

    diagramas = ler_diagramas(FONTE)
    print("\nCONFERINDO %s\n" % os.path.basename(FONTE))
    ok(len(diagramas) == 7, "sete diagramas na fonte", "achei %d" % len(diagramas))

    for i, d in enumerate(diagramas, 1):
        print("\n%d) %s" % (i, d.titulo))
        pos = posicionar(d)

        ok(set(pos) == set(d.rotulos),
           "toda caixa recebeu posição",
           "sem posição: %s" % (set(d.rotulos) - set(pos) or "nenhuma"))

        # Duas caixas no mesmo ponto = uma esconde a outra, e ninguém nota.
        vistos, colididos = {}, []
        for nid, xy in pos.items():
            chave = (round(xy[0], 1), round(xy[1], 1))
            if chave in vistos:
                colididos.append("%s=%s" % (nid, vistos[chave]))
            vistos[chave] = nid
        ok(not colididos, "nenhuma caixa empilhada sobre outra",
           ", ".join(colididos[:3]))

        orfas = [(a, b) for a, b, _, _ in d.arestas
                 if a not in d.rotulos or b not in d.rotulos]
        ok(not orfas, "toda seta liga duas caixas que existem", str(orfas[:2]))

        vazios = [n for n, r in d.rotulos.items() if not r.strip()]
        ok(not vazios, "nenhuma caixa sem texto", str(vazios))

        sujos = [n for n, r in d.rotulos.items() if any(s in r for s in SETAS)]
        ok(not sujos, "nenhum rótulo com seta dentro",
           "fatiamento errado em %s" % sujos[:2])

        fora = [cor_de(d, n) for n in d.rotulos if cor_de(d, n) not in PALETA.values()]
        ok(not fora, "toda cor está na paleta que a API aceita", str(set(fora)))

        ok(all(f in FORMA_MIRO for f in d.formas.values()),
           "toda forma tem equivalente no Miro",
           str({f for f in d.formas.values() if f not in FORMA_MIRO}))

        longos = [n for n, r in d.rotulos.items() if len(r) > 200]
        ok(not longos, "nenhum rótulo acima de 200 caracteres", str(longos))

    print()
    if falhas:
        print("FALHAS (%d):" % len(falhas))
        for f in falhas:
            print("  -", f)
        return 1
    print("o plano está consistente. O que não dá para conferir daqui: se a API")
    print("aceita `captions` e `strokeStyle` no conector — o script tem recuo")
    print("para os dois, e lista no fim o rótulo que ela recusar.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Cria os fluxogramas do backend no Miro.")
    p.add_argument("--conferir", action="store_true",
                   help="confere parse, layout e paleta sem token e sem rede")
    p.add_argument("--board", required="--conferir" not in sys.argv,
                   help="id do quadro (está na URL miro.com/app/board/<ID>/)")
    p.add_argument("--aplicar", action="store_true",
                   help="sem isto, só mostra o plano e não toca no quadro")
    p.add_argument("--limpar", action="store_true",
                   help="apaga só o que esta ferramenta criou neste quadro")
    p.add_argument("--so", type=int, metavar="N",
                   help="manda apenas o diagrama N (1 a 7), para experimentar")
    p.add_argument("--token-arquivo", help="arquivo com o token (fora do histórico)")
    args = p.parse_args()

    if args.conferir:
        return conferir()

    manifesto = ler_manifesto()

    if args.limpar:
        ids = manifesto.get(args.board, [])
        if not ids:
            print("nada registrado para este quadro — não vou varrer o quadro de alguém.")
            return 0
        if not args.aplicar:
            print("apagaria %d itens deste quadro. Rode com --aplicar." % len(ids))
            return 0
        api = Miro(token_de(args), args.board)
        sobrou = []
        for i in ids:
            try:
                api.apagar(i)
            except MiroErro as e:
                # 404 = já não existe (alguém apagou na mão). Não é erro nosso.
                if e.codigo != 404:
                    sobrou.append(i)
                    print("   não apaguei %s: %s" % (i, e))
        manifesto[args.board] = sobrou
        gravar_manifesto(manifesto)
        print("apagados: %d · restaram no manifesto: %d" % (len(ids) - len(sobrou), len(sobrou)))
        return 0

    diagramas = ler_diagramas(FONTE)
    if args.so:
        diagramas = diagramas[args.so - 1:args.so]
    if not diagramas:
        raise SystemExit("nenhum diagrama em %s" % FONTE)

    total_caixas = sum(len(d.rotulos) for d in diagramas)
    total_setas = sum(len(d.arestas) for d in diagramas)
    print("\nFonte: %s" % FONTE)
    for i, d in enumerate(diagramas, 1):
        print("  %d. %-48s %2d caixas, %2d setas, %s"
              % (i, d.titulo[:48], len(d.rotulos), len(d.arestas), d.direcao))
    print("\nTotal: %d caixas + %d conectores = %d chamadas à API"
          % (total_caixas, total_setas, total_caixas + total_setas + len(diagramas)))
    print("Nível 2 (100 créditos/chamada), teto 1000 chamadas/min — folgado.")

    if not args.aplicar:
        print("\nNada enviado. Rode de novo com --aplicar.")
        return 0

    api = Miro(token_de(args), args.board)
    criados = manifesto.setdefault(args.board, [])
    perdidos: list[str] = []
    y_base = 0.0

    # A LEGENDA. A mesma codificação de cor se repete nos sete diagramas, e é
    # isso que a torna legenda e não enfeite: sem ela, quem abre o quadro vê
    # caixas colaridas e não sabe que amarelo quer dizer decisão.
    if not args.so:
        legenda = ("Backend da VideoConference BWL · gerado de "
                   "docs/backend-mermaid.md\n\n"
                   "amarelo = decisão   ·   verde = escrita no banco   ·   "
                   "roxo = chamada a serviço externo\n"
                   "vermelho = recusa ou caminho que não avança   ·   "
                   "laranja = ação de pessoa   ·   cinza = banco / S3\n"
                   "losango = decisão   ·   cilindro = armazenamento")
        lid = api.texto(conteudo=legenda, x=0, y=-600, largura=1400, tamanho="18")
        if lid:
            criados.append(lid)

    try:
        for n, d in enumerate(diagramas, 1):
            print("\n[%d/%d] %s" % (n, len(diagramas), d.titulo))
            pos = posicionar(d)
            min_y = min(y for _, y in pos.values())
            max_y = max(y for _, y in pos.values())
            min_x = min(x for x, _ in pos.values())

            tid = api.texto(conteudo=d.titulo, x=min_x, y=y_base - ALTURA_TITULO,
                            largura=900)
            if tid:
                criados.append(tid)

            ids: dict[str, str] = {}
            for nid, (x, y) in pos.items():
                forma = d.formas[nid]
                ids[nid] = api.forma(
                    conteudo=d.rotulos[nid], forma=FORMA_MIRO[forma],
                    x=x, y=y_base + (y - min_y), w=L_CAIXA,
                    h=A_CAIXA + (20 if forma == "decisao" else 0),
                    cor=cor_de(d, nid))
                criados.append(ids[nid])
                time.sleep(0.12)
            print("   %d caixas" % len(ids))

            for a, b, rotulo, tracejada in d.arestas:
                cid, perdido = api.conector(ids[a], ids[b], rotulo, tracejada)
                criados.append(cid)
                if perdido:
                    perdidos.append("%s: %s" % (d.titulo, perdido))
                time.sleep(0.12)
            print("   %d conectores" % len(d.arestas))

            y_base += (max_y - min_y) + GAP_DIAGRAMA
    finally:
        # Grava SEMPRE, mesmo com erro no meio: sem isto, uma falha na caixa 40
        # deixaria 39 itens no quadro e nada no manifesto -- `--limpar` não
        # alcançaria, e a limpeza voltaria a ser trabalho manual.
        gravar_manifesto(manifesto)

    print("\nPronto. %d itens, %d chamadas." % (len(criados), api.chamadas))
    print("Quadro: https://miro.com/app/board/%s/" % args.board)
    if perdidos:
        print("\nRótulos que a API recusou (as setas existem, sem texto):")
        for r in perdidos:
            print("   -", r.replace("\n", " "))
    print("\nPara desfazer: --limpar --aplicar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

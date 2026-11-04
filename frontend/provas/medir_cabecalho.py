# -*- coding: utf-8 -*-
"""Mede o cabeçalho da sala e acusa sobreposição. Não é olhômetro: é retângulo.

    python -I -B medir_cabecalho.py

Carrega o `room.css` DE VERDADE num banco de prova com todos os blocos de
estado visíveis ao mesmo tempo (o pior caso), e em várias larguras:

  - compara os retângulos dois a dois e acusa qualquer interseção;
  - confere que nada escapa do cabeçalho pra cima ou pra baixo (era o risco de
    empilhar dentro de uma caixa posicionada por `top: 50%`);
  - confere que nada passa das bordas laterais.

Edge headless reaproveita o perfil quando duas execuções compartilham o mesmo
`--user-data-dir`, e aí o segundo dump sai igual ao primeiro mesmo com a página
diferente. Por isso cada render ganha um diretório próprio e descartável.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AQUI = Path(__file__).resolve().parent
BANCO = AQUI / "header"
CSS = Path(r"C:\trabalhos\BWL\VideoConferenceBWL\frontend\src\styles\room.css")
LARGURAS = [1920, 1600, 1440, 1280, 1100, 1024, 1000, 980, 900, 860, 768, 640, 500, 420, 360]

EDGE = next((p for p in [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
] if p.exists()), None)
if EDGE is None:
    raise SystemExit("[ERRO] Edge não encontrado.")

shutil.copy(CSS, BANCO / "room.css")

# Roda DENTRO da página: lê os retângulos e devolve as interseções.
SONDA = """
(() => {
  const cab = document.querySelector('.vr-header');
  const r = (e) => { const b = e.getBoundingClientRect();
                     return {x:b.x, y:b.y, w:b.width, h:b.height, b:b.bottom, rr:b.right}; };
  // Os blocos que disputam espaco: filhos do cabecalho e os itens de estado.
  // `position: fixed`/`absolute` sai do fluxo DE PROPOSITO (o cartao de voto e
  // um dialogo flutuante perto do rodape). Medir isso como se fosse item do
  // cabecalho acusaria defeito onde ha decisao.
  const alvos = [...cab.children, ...cab.querySelectorAll('.vr-header-status > *')]
      .filter(e => e.getBoundingClientRect().width > 0)
      .filter(e => !['fixed','absolute'].includes(getComputedStyle(e).position));
  const nome = (e) => e.className && e.className.toString().split(' ')[0] || e.tagName;
  const cruza = (a, b) => !(a.rr <= b.x || b.rr <= a.x || a.b <= b.y || b.b <= a.y);
  const sobrepostos = [];
  for (let i = 0; i < alvos.length; i++)
    for (let j = i + 1; j < alvos.length; j++) {
      if (alvos[i].contains(alvos[j]) || alvos[j].contains(alvos[i])) continue;
      if (cruza(r(alvos[i]), r(alvos[j])))
        sobrepostos.push(nome(alvos[i]) + ' x ' + nome(alvos[j]));
    }
  const cr = r(cab);
  const fora = alvos.filter(e => { const b = r(e);
      return b.y < cr.y - 0.5 || b.b > cr.b + 0.5 || b.x < cr.x - 0.5 || b.rr > cr.rr + 0.5; })
    .map(nome);
  return JSON.stringify({largura: innerWidth, altura_cab: Math.round(cr.h),
                         sobrepostos, fora,
                         rolagem_lateral: document.documentElement.scrollWidth > innerWidth + 1});
})()
"""

def cenario() -> str:
    """O HTML medido.

    Sem `--real`, o PIOR caso: todos os blocos de estado visíveis ao mesmo
    tempo. Com `--real`, o caso de todo dia: só o cronômetro.

    Os dois importam por motivos diferentes. O pior caso prova que nada se
    sobrepõe nem no limite; o real prova que o cabeçalho não engordou no uso
    normal — foi medindo o real que se viu a pílula do cronômetro dobrar a
    altura do cabeçalho em 1440px.
    """
    html = (BANCO / "index.html").read_text(encoding="utf-8")
    if "--real" not in sys.argv:
        return html
    for alvo in ('<span class="vr-progresso">', '<span class="vr-falha-aula">'):
        while alvo in html:
            i = html.index(alvo)
            html = html[:i] + html[html.index("</span>", i) + len("</span>"):]
    i = html.index('<div class="vr-hist">')
    j = html.index("</div>", html.index("</button>", i)) + len("</div>")
    return html[:i] + html[j:]


# A página medida = o banco de prova + a sonda escrevendo o resultado no DOM
# (é o DOM que o `--dump-dom` devolve; o console não vem).
(BANCO / "medir.html").write_text(
    cenario()
    + '\n<pre id="saida"></pre>\n<script>\n'
      'document.getElementById("saida").textContent = "RESULTADO: " + (' + SONDA + ');\n'
      '</script>\n',
    encoding="utf-8")

def cenario() -> str:
    """O HTML medido. Sem `--real`, o PIOR caso (todos os blocos de estado ao
    mesmo tempo). Com `--real`, o caso de todo dia: só o cronômetro.

    Os dois importam por motivos diferentes: o pior caso prova que nada se
    sobrepõe nem no limite, e o real prova que o cabeçalho não engordou no uso
    normal -- foi assim que se viu que a pílula do cronômetro dobrava a altura
    do cabeçalho em 1440px."""
    html = (BANCO / "index.html").read_text(encoding="utf-8")
    if "--real" not in sys.argv:
        return html
    for alvo in ('<span class="vr-progresso">', '<span class="vr-falha-aula">'):
        while alvo in html:
            i = html.index(alvo)
            html = html[:i] + html[html.index("</span>", i) + 7:]
    i = html.index('<div class="vr-hist">')
    j = html.index("</div>", html.index("</button>", i)) + 6
    return html[:i] + html[j:]


falhas = 0
for largura in LARGURAS:
    perfil = tempfile.mkdtemp(prefix=f"edge{largura}_")   # um perfil POR render
    saida = subprocess.run(
        [str(EDGE), "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--user-data-dir={perfil}", f"--window-size={largura},900",
         "--virtual-time-budget=1500",
         f"--dump-dom", (BANCO / "medir.html").as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    shutil.rmtree(perfil, ignore_errors=True)

    marca = "RESULTADO:"
    linha = next((l for l in saida.stdout.splitlines() if marca in l), None)
    if not linha:
        print(f"{largura:>5}px  [ERRO] a sonda não devolveu nada")
        falhas += 1
        continue
    # O dump traz a linha do DOM inteira: o JSON vem seguido de `</pre>` e do
    # resto da pagina. `raw_decode` para no fim do valor e ignora a sobra.
    import html as _html
    bruto = _html.unescape(linha.split(marca, 1)[1].strip())
    d, _ = json.JSONDecoder().raw_decode(bruto)
    problemas = []
    if d["sobrepostos"]:
        problemas.append("SOBREPOSTOS: " + "; ".join(sorted(set(d["sobrepostos"]))))
    if d["fora"]:
        problemas.append("FORA DO CABEÇALHO: " + ", ".join(sorted(set(d["fora"]))))
    if d["rolagem_lateral"]:
        problemas.append("ROLAGEM LATERAL")
    estado = "ok   " if not problemas else "FALHA"
    print(f"{largura:>5}px  {estado}  cabeçalho {d['altura_cab']}px"
          + ("" if not problemas else "\n          " + "\n          ".join(problemas)))
    falhas += bool(problemas)

print(f"\nlarguras com problema: {falhas}")
raise SystemExit(1 if falhas else 0)

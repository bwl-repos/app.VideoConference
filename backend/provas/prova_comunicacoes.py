# -*- coding: utf-8 -*-
"""O histórico das comunicações — o que ficou registrado, e para quem.

    python -B provas/prova_comunicacoes.py

## O que isto protege

1. **As duas pontas não podem divergir.** O servidor grava o EVENTO; a tela monta
   a FRASE. É o desenho certo — os rótulos das etapas vivem no frontend —, mas
   cria uma obrigação: todo tipo que o servidor emite, a tela tem de saber
   renderizar. Um tipo novo sem par do outro lado vira linha crua no histórico
   de uma aula ao vivo. Esta prova percorre `TIPOS` e confere o par.
2. **O histórico é de todos.** `_require_host` aqui tiraria do aluno atrasado a
   única forma de saber o que já foi dito.
3. **Não pode levar a cadência junto.** Gravar comunicação é caminho novo dentro
   de caminho antigo; publicar não aplica migration. Sem a tabela, fica inerte.
4. **`0 de 0` num voto que acabou de abrir** afirmaria que ninguém aprovou —
   quando ninguém foi perguntado ainda.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services.comunicacoes import TIPOS, da_decisao  # noqa: E402

falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-58s %s" % ("ok" if cond else "FALHA", oque, porque))


def ler(caminho: str) -> str:
    return io.open(RAIZ / caminho, encoding="utf-8").read()


def so_codigo(texto: str) -> str:
    """Sem comentários e sem docstrings — só o que executa.

    Afirmação de AUSÊNCIA sobre o fonte cru casa com a prosa que explica a
    ausência. Aconteceu duas vezes: "não exige host" casou com a docstring que
    diz "`optional_user`, e não `_require_host`", e "nenhum rótulo de etapa"
    casou com o exemplo de frase dentro do próprio docstring.

    O bloco de aspas triplas é cortado alternando: ímpar abre, par fecha. Basta
    para este fonte, onde não há aspas triplas dentro de string.
    """
    sem_docstring: list[str] = []
    dentro = False
    for linha in texto.splitlines():
        marcas = linha.count('"""')
        if dentro:
            if marcas:
                dentro = False
            continue
        if marcas == 1:
            dentro = True
            continue
        if marcas >= 2:          # docstring de uma linha só
            continue
        if linha.strip().startswith("#"):
            continue
        sem_docstring.append(linha)
    return "\n".join(sem_docstring)


def corpo(fonte: str, assinatura: str) -> str:
    i = fonte.index(assinatura)
    resto = fonte[i + len(assinatura):]
    fim = len(resto)
    for marca in ("\nasync def ", "\ndef ", "\n@router.", "\nclass "):
        j = resto.find(marca)
        if j != -1:
            fim = min(fim, j)
    return assinatura + resto[:fim]


print("Histórico das comunicações")
print()
print("1) a decisão da cadência vira evento")
print()

conferir(da_decisao("plenary", "nada", None, 0, 0) is None,
         "`nada` não vira comunicação nenhuma",
         "'a sala seguiu como estava' não é algo que alguém leia")

t, m = da_decisao("plenary", "abrir_voto", None, 0, 0)  # type: ignore[misc]
conferir(t == "voto_aberto" and m == {"stage": "plenary"},
         "abrir voto registra a etapa que venceu")
conferir("sim" not in m and "total" not in m,
         "e NÃO registra placar",
         "`0 de 0` diria que ninguém aprovou; ninguém foi perguntado ainda")

t, m = da_decisao("plenary", "avancar", "question", 7, 9)  # type: ignore[misc]
conferir(t == "avancou" and m["proxima"] == "question" and m["sim"] == 7 and m["total"] == 9,
         "avançar registra para onde foi, e o placar")

t, m = da_decisao("groups", "estender", None, 2, 9)  # type: ignore[misc]
conferir(t == "estendeu" and m["stage"] == "groups" and m["sim"] == 2 and m["total"] == 9,
         "estender registra a etapa que ganhou tempo, e o placar")

conferir(all(isinstance(x, str) for x in TIPOS) and len(set(TIPOS)) == len(TIPOS),
         "a lista de tipos é enumerável e sem repetição",
         "lista que ninguém percorre não dá para conferir contra a outra ponta")

print()
print("2) a tela sabe renderizar TODO tipo que o servidor emite")
print()

FRONT = (RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx").read_text(encoding="utf-8")
frase = corpo(FRONT, "function frasePara(c: OpenPblComunicacao): string {")
for tipo in TIPOS:
    conferir(f'case "{tipo}":' in frase,
             f"`{tipo}` tem frase na tela")
conferir("default:" in frase,
         "e há um padrão para tipo desconhecido",
         "histórico com buraco é pior que linha crua")

print()
print("3) o histórico é de TODO MUNDO")
print()

ROUTER = ler("app/routers/openpbl_class.py")
rota = corpo(ROUTER, "async def listar_comunicacoes(room_id: str, user: CurrentUser | None = Depends(optional_user)):")
conferir("_require_host" not in so_codigo(rota),
         "a rota NÃO exige host",
         "quem chegou atrasado é quem mais precisa ler")
conferir("ORDER BY at" in rota, "e devolve em ordem de tempo")

print()
print("4) sem a tabela, fica inerte — e só ele")
print()

grava = corpo(ROUTER, "async def _registrar_comunicacao(room_id: str, evento, texto: str = \"\") -> None:")
pos_guarda = grava.find('tem_tabela("video_room_comunicacoes")')
pos_insert = grava.find("INSERT INTO video_room_comunicacoes")
conferir(pos_guarda != -1, "pergunta se a tabela existe")
conferir(pos_guarda != -1 and pos_insert != -1 and pos_guarda < pos_insert,
         "ANTES de inserir",
         "a 018 ensinou: novo não leva o antigo junto")
conferir("except Exception" in grava and "logger.exception" in grava,
         "e falha de INSERT não derruba a aula",
         "registro não é caminho crítico; o log já guardou a decisão")
conferir("if not evento:" in grava and "return" in grava,
         "evento nulo não grava linha")

conferir("tem_tabela(\"video_room_comunicacoes\")" in rota,
         "a leitura também se protege, devolvendo lista vazia")

print()
print("5) o servidor não guarda a frase")
print()

SERVICO = ler("app/services/comunicacoes.py")
for rotulo in ("Plenária", "Aquecimento", "Sinopse", "Encerramento"):
    conferir(rotulo not in so_codigo(SERVICO),
             f"nenhum rótulo de etapa (\"{rotulo}\") no serviço",
             "uma segunda lista de nomes envelheceria calada")
conferir("stepDef(" in frase,
         "a tela monta a frase com os rótulos de STEPS")

print()
print("6) o freio de mão também é comunicação")
print()

stage = corpo(ROUTER, "async def set_stage(room_id: str, body: StageSet, user: CurrentUser = Depends(get_current_user)):")
conferir('_registrar_comunicacao(room_id, ("etapa_manual"' in stage,
         "o host avançando à mão entra no histórico",
         "senão faltaria registro justo quando alguém assume o controle")

cad = corpo(ROUTER, "async def _aplicar_cadencia(room_id: str, row):")
conferir("_registrar_comunicacao" in cad and "comunicacoes.da_decisao" in cad,
         "e a cadência registra o que decidiu")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

# -*- coding: utf-8 -*-
"""A cadência do encontro, exercitada com relógio de mentira.

    python -B provas/prova_cadencia.py

## Por que esta prova existe

Esta função substitui a pessoa que dizia "vamos seguir". Quando ela erra, erra
numa aula ao vivo, com um cliente assistindo — e os casos que ela erra são
justamente os que acontecem uma vez a cada vinte turmas:

- o host assume o manual no meio de um voto;
- o host troca a etapa à mão enquanto se vota;
- a turma inteira some da aba e ninguém vota;
- a última etapa termina e não há para onde avançar;
- um aluno vota e sai da sala antes de a janela fechar.

Nenhum deles se reproduz à mão numa sala de verdade sem gastar uma turma. Com
a regra pura e o relógio por parâmetro, todos cabem num arquivo.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services.cadencia import (  # noqa: E402
    DURACAO_DA_ETAPA, JANELA_DO_VOTO, ORDEM, Estado, apurar, decidir, maioria,
    proxima_etapa,
)

T0 = datetime(2026, 10, 28, 14, 0, 0)
TURMA = ["a", "b", "c", "d", "e"]

falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-58s %s" % ("ok" if cond else "FALHA", oque, porque))


def est(**kw) -> Estado:
    base = dict(stage="synopsis", auto=True, comecou_em=T0)
    base.update(kw)
    return Estado(**base)


print("A cadência do encontro")
print()
print("1) o modo manual tem precedência sobre TUDO")
print()

#: O host desliga a automação justamente quando ela está indo mal — o que
#: costuma ser no meio de um voto. Se o manual não ganhasse aqui, desligar não
#: desligaria nada.
d = decidir(est(auto=False, comecou_em=T0 - timedelta(hours=1)), T0, TURMA)
conferir(d.acao == "nada", "etapa vencida + manual = nada", d.porque)

votando = est(auto=False, voto_fecha_em=T0 + timedelta(seconds=5),
              voto_da_etapa="synopsis", votos={"a": True, "b": True, "c": True})
conferir(decidir(votando, T0 + timedelta(seconds=10), TURMA).acao == "nada",
         "voto com maioria + manual = nada",
         "desligar a automação tem de parar até o que já estava em curso")

print()
print("2) o relógio da etapa abre o voto, e só então")
print()

conferir(decidir(est(), T0 + timedelta(seconds=10), TURMA).acao == "nada",
         "dentro do tempo, nada acontece")
dur = DURACAO_DA_ETAPA["synopsis"]
d = decidir(est(), T0 + timedelta(seconds=dur), TURMA)
conferir(d.acao == "abrir_voto", "no instante em que o tempo esgota, pergunta", d.porque)
conferir(d.voto_fecha_em == T0 + timedelta(seconds=dur) + JANELA_DO_VOTO,
         "e a janela do voto é de 15 segundos", str(JANELA_DO_VOTO))

#: Etapas de comando do host não têm relógio: um voto ali perguntaria "pode
#: seguir?" sobre algo que depende de uma ação humana.
for etapa in ("session_start", "registration_open", "amplify_code", "registration_close"):
    d = decidir(est(stage=etapa, comecou_em=T0 - timedelta(hours=2)), T0, TURMA)
    conferir(d.acao == "nada", "`%s` não tem relógio" % etapa, d.porque)

conferir(decidir(est(comecou_em=None), T0 + timedelta(hours=1), TURMA).acao == "nada",
         "sem hora de início, não inventa uma",
         "abriria voto para quem acabou de chegar na etapa")

print()
print("3) quem não vota conta como NÃO")
print()

#: É a regra que define o viés da cadência: ela erra para o lado de esperar.
fecha = T0 + timedelta(seconds=10)
depois = fecha + timedelta(seconds=1)

ninguem = est(voto_fecha_em=fecha, voto_da_etapa="synopsis", votos={})
d = decidir(ninguem, depois, TURMA)
conferir(d.acao == "estender" and d.sim == 0 and d.total == 5,
         "turma inteira em silêncio NÃO avança",
         "%d sim de %d — %s" % (d.sim, d.total, d.porque))

dois = est(voto_fecha_em=fecha, voto_da_etapa="synopsis",
           votos={"a": True, "b": True})
d = decidir(dois, depois, TURMA)
conferir(d.acao == "estender",
         "2 sins em 5 não é maioria", "%d de %d" % (d.sim, d.total))

tres = est(voto_fecha_em=fecha, voto_da_etapa="synopsis",
           votos={"a": True, "b": True, "c": True})
d = decidir(tres, depois, TURMA)
conferir(d.acao == "avancar" and d.proxima == "groups",
         "3 sins em 5 avança", "%d de %d -> %s" % (d.sim, d.total, d.proxima))

#: EMPATE NÃO AVANÇA. Metade da turma dizendo "ainda não" basta para esperar.
par = est(voto_fecha_em=fecha, voto_da_etapa="synopsis",
          votos={"a": True, "b": True})
d = decidir(par, depois, ["a", "b", "c", "d"])
conferir(d.acao == "estender", "empate (2 de 4) NÃO avança", d.porque)

#: Um "não" explícito e uma ausência pesam igual — é o que a regra diz.
explicito = est(voto_fecha_em=fecha, voto_da_etapa="synopsis",
                votos={"a": True, "b": True, "c": False, "d": False, "e": False})
calado = est(voto_fecha_em=fecha, voto_da_etapa="synopsis",
             votos={"a": True, "b": True})
conferir(decidir(explicito, depois, TURMA).acao == decidir(calado, depois, TURMA).acao,
         "CONTROLE: 'não' explícito e silêncio dão o mesmo resultado",
         "é o que 'conta como não' significa")

print()
print("4) só os PRESENTES decidem")
print()

#: Quem saiu da sala não pode decidir o ritmo de quem ficou. Aqui `e` votou sim
#: e foi embora: sem ele a turma tem 4, e os 3 sins restantes são maioria.
saiu = est(voto_fecha_em=fecha, voto_da_etapa="synopsis",
           votos={"a": True, "b": True, "c": True, "e": True})
d = decidir(saiu, depois, ["a", "b", "c", "d"])
conferir(d.total == 4 and d.sim == 3,
         "voto de quem saiu não entra na conta", "%d de %d" % (d.sim, d.total))

dupla = est(voto_fecha_em=fecha, voto_da_etapa="synopsis", votos={"a": True})
d = decidir(dupla, depois, ["a", "a", "b"])
conferir(d.total == 2,
         "CONTROLE: presença repetida conta uma vez",
         "reconexão não deve inflar o denominador")

print()
print("5) o voto não sobrevive a uma troca de etapa à mão")
print()

trocou = est(stage="plenary", voto_fecha_em=fecha, voto_da_etapa="synopsis",
             votos={"a": True, "b": True, "c": True})
d = decidir(trocou, depois, TURMA)
conferir(d.acao == "estender" and "etapa mudou" in d.porque,
         "maioria de um voto de OUTRA etapa não avança", d.porque)

print()
print("6) a janela é respeitada")
print()

cedo = est(voto_fecha_em=fecha, voto_da_etapa="synopsis",
           votos={"a": True, "b": True, "c": True, "d": True, "e": True})
conferir(decidir(cedo, fecha - timedelta(seconds=1), TURMA).acao == "nada",
         "com todos os sins, ainda espera a janela fechar",
         "a pergunta vale 15s para todos, não até o 3º clique")

print()
print("7) o fim da fila")
print()

ultima = Estado(stage=ORDEM[-2], auto=True, voto_fecha_em=fecha,
                voto_da_etapa=ORDEM[-2], votos={x: True for x in TURMA})
d = decidir(ultima, depois, TURMA)
conferir(d.acao == "avancar" and d.proxima == "done",
         "a penúltima avança para `done`", str(d.proxima))
fim = Estado(stage="done", auto=True, comecou_em=T0 - timedelta(hours=1))
conferir(decidir(fim, T0, TURMA).acao == "nada", "e `done` não avança mais")
conferir(proxima_etapa("done") is None, "CONTROLE: não há nada depois de `done`")
conferir(proxima_etapa("inexistente") is None, "etapa desconhecida não tem seguinte")

print()
print("8) a ordem aqui é a MESMA do router")
print()

#: As duas listas vivem em arquivos diferentes de propósito (esta função é pura
#: e não importa o router). Divergirem faria a cadência pular uma etapa que a
#: sala conhece — e isso não daria erro em lugar nenhum.
import re  # noqa: E402

fonte = (RAIZ / "app/routers/openpbl_class.py").read_text(encoding="utf-8")
bloco = re.search(r"_STAGES = \((.*?)\)", fonte, re.S).group(1)
do_router = tuple(re.findall(r'"([a-z_]+)"', bloco))
conferir(do_router == ORDEM,
         "a ordem da cadência bate com `_STAGES`",
         "%d etapas dos dois lados" % len(ORDEM))
conferir(set(DURACAO_DA_ETAPA) == set(ORDEM),
         "CONTROLE: e toda etapa tem duração declarada (ou `None`)",
         "faltando: %s" % (set(ORDEM) - set(DURACAO_DA_ETAPA) or "nenhuma"))

print()
print("9) as funções auxiliares, nos extremos")
print()

conferir(apurar({}, []) == (0, 0), "turma vazia não divide por zero")
conferir(maioria(0, 0) is False, "e sem ninguém não há maioria")
conferir(maioria(1, 1) is True, "turma de um: o voto dele decide")
conferir(maioria(0, 1) is False, "CONTROLE: e o silêncio dele também")

print()
print("10) a tubulação: a regra pura não serve de nada sozinha")
print()

#: A regra ser perfeita e ninguém chamá-la é o defeito inteiro de volta.
ROUTER = (RAIZ / "app/routers/openpbl_class.py").read_text(encoding="utf-8")

conferir("_aplicar_cadencia(room_id, row)" in ROUTER,
         "a leitura do estado AVALIA a cadência",
         "é o único relógio que existe — não há laço de fundo")
conferir('@router.post("/{room_id}/openpbl/cadencia")' in ROUTER,
         "o host tem como ligar e desligar")
conferir('@router.post("/{room_id}/openpbl/voto")' in ROUTER,
         "e a turma tem como votar")

#: O VOTO É DA IDENTIDADE DE QUEM CHAMA. Aceitá-lo do corpo deixaria um aluno
#: votar pelos colegas e decidir o ritmo da aula sozinho.
voto = ROUTER[ROUTER.index('@router.post("/{room_id}/openpbl/voto")'):]
voto = voto[:voto.index('@router.post("/{room_id}/openpbl/stage")')]
conferir("user.id" in voto,
         "o voto é gravado pela identidade de QUEM CHAMA",
         "do contrário um aluno votaria pelos colegas")
conferir("identity" not in voto,
         "CONTROLE: e não há identidade vinda do corpo",
         "é o que impede votar pelos outros")
conferir("jsonb_set" in voto,
         "dois votos simultâneos não se sobrescrevem",
         "ler-modificar-gravar perderia um voto, invisivelmente")

#: Avançar à mão tem de marcar o início, senão a etapa nova nasce vencida e a
#: cadência abre um voto sobre algo que acabou de começar.
setter = ROUTER[ROUTER.index('@router.post("/{room_id}/openpbl/stage")'):]
setter = setter[:setter.index("# ── roster")]
conferir("stage_started_at=$3" in setter,
         "o host avançando à mão marca a hora de início",
         "senão a etapa nova nasceria vencida")
conferir("vote_ends_at=NULL" in setter,
         "e descarta o voto em curso",
         "o voto era sobre a etapa anterior")

#: Ligar a automação também marca o início — senão ela abriria um voto no
#: mesmo segundo, surpreendendo quem acabou de confiar nela.
modo = ROUTER[ROUTER.index('@router.post("/{room_id}/openpbl/cadencia")'):]
modo = modo[:modo.index('@router.post("/{room_id}/openpbl/voto")')]
conferir("stage_started_at=$3" in modo,
         "ligar a automação marca o início da etapa corrente",
         "senão abriria um voto no mesmo segundo")
conferir("_require_host" in modo,
         "CONTROLE: e só o host liga/desliga")

print()
print("11) a automação é o caminho PADRÃO")
print()

MIG = (RAIZ / "app/migrations/018_openpbl_cadencia.sql").read_text(encoding="utf-8")
SCHEMA = (RAIZ / "app/schema.sql").read_text(encoding="utf-8")
conferir("auto_mode BOOLEAN NOT NULL DEFAULT true" in MIG,
         "a migration cria `auto_mode` ligado",
         "o encontro roda sozinho; assumir o controle é a exceção")
conferir("auto_mode BOOLEAN NOT NULL DEFAULT true" in SCHEMA,
         "e o schema base diz o mesmo",
         "instalação nova e banco migrado têm de concordar")

#: LIGADO NÃO É CORRENDO. Sem hora de início a regra não abre voto -- é o que
#: impede uma sala existente de disparar uma votação no segundo em que a coluna
#: aparece.
conferir(decidir(est(comecou_em=None, auto=True),
                 T0 + timedelta(days=1), TURMA).acao == "nada",
         "CONTROLE: ligado + sem hora de início = nada acontece",
         "a coluna aparecer não pode disparar voto em sala nenhuma")

#: E sem a migration aplicada, a cadência não existe: o router lê `auto_mode`
#: só quando a coluna está lá, e cai em desligado.
conferir('"auto_mode" in row.keys() else False' in ROUTER,
         "banco sem a migration = cadência desligada",
         "falha para o lado seguro, não para o lado de avançar sozinho")

print()
print("12) a tela: a pergunta precisa chegar ao aluno")
print()

FRONT = (RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx").read_text(encoding="utf-8")
SDK = (RAIZ.parent / "frontend/src/lib/video-rooms-sdk.ts").read_text(encoding="utf-8")

conferir("function CartaoDoVoto" in FRONT, "o cartão existe")
conferir("<CartaoDoVoto" in FRONT,
         "e alguém o RENDERIZA",
         "um componente sem uso é o defeito inteiro de volta")
conferir("pblClass?.vote_ends_at &&" in FRONT,
         "aparece só quando há voto aberto")

#: Fora do bloco do host: se estivesse dentro, só o facilitador veria a
#: pergunta -- e a turma, que é quem vota, não.
cartao = FRONT[FRONT.index("<CartaoDoVoto"):]
cartao = cartao[:cartao.index("/>") + 2]
conferir("pblHost" not in cartao,
         "CONTROLE: e NÃO está condicionado a ser host",
         "quem vota é a turma")

conferir("setCadencia:" in SDK and "votar:" in SDK, "o SDK expõe as duas rotas")
conferir("openpbl/cadencia" in SDK and "openpbl/voto" in SDK,
         "apontando para os endpoints certos")
conferir("sdk.openpbl.setCadencia(" in FRONT,
         "o host tem a chave automático/manual na tela")

#: O RELÓGIO É DO SERVIDOR. Contar 15 a partir da chegada do cartão daria um
#: prazo diferente para cada aluno, conforme a latência.
voto_comp = FRONT[FRONT.index("function CartaoDoVoto"):]
voto_comp = voto_comp[:voto_comp.index("/* ── Avaliação de desempenho")]
conferir("new Date(fechaEm).getTime()" in voto_comp,
         "a contagem desce a partir de `vote_ends_at`",
         "e não de 15 contados na chegada do cartão")
conferir("conta como" in voto_comp,
         "e o cartão DIZ que o silêncio conta como não",
         "um voto cujo peso o eleitor desconhece não é voto")

print()
print("13) deploy sem a migration não tira nada do host")
print()

#: As migrations deste repositório são aplicadas À MÃO: o código chega ao
#: servidor por `publish.ps1`, que não roda SQL nenhum, e o `schema.sql` está
#: montado em `docker-entrypoint-initdb.d`, que o Postgres só executa com o
#: diretório de dados VAZIO. Num banco que já tem dados, ele é ignorado.
#:
#: Então existe uma janela -- de minutos ou de dias -- em que o código novo
#: conversa com o schema antigo. A cadência ficar inerte nessa janela é o
#: esperado. O que NÃO pode acontecer é o botão verde ▶, que é anterior a toda
#: esta história, parar de funcionar porque passou a escrever colunas que ainda
#: não existem: o host perderia o único controle que sempre teve, e perderia no
#: meio de uma aula.


def so_codigo(texto: str) -> str:
    """O texto sem comentários: uma guarda explicada não é uma guarda."""
    return "\n".join(l for l in texto.splitlines() if not l.lstrip().startswith("#"))


def corpo(nome: str, ate: str) -> str:
    t = ROUTER[ROUTER.index(nome):]
    return so_codigo(t[:t.index(ate)])


etapa = corpo('@router.post("/{room_id}/openpbl/stage")',
              "# ── roster: status dos alunos")
conferir('"auto_mode" in row.keys()' in etapa,
         "avançar à mão confere se as colunas existem",
         "o row já está em mãos; não custa uma consulta a mais")
conferir("UPDATE video_room_openpbl_class SET stage=$2 WHERE room_id=$1" in etapa,
         "e sem elas grava só a etapa",
         "o botão do host não passa a depender da cadência")
conferir("vote_ends_at=NULL" in etapa,
         "CONTROLE: com elas, ainda descarta o voto em curso",
         "senão a etapa nova nasceria com uma votação da anterior aberta")

#: FALSIFICAÇÃO: a guarda só vale se houver DOIS caminhos. Um `if` cujos dois
#: braços escrevem as colunas novas passaria nas três linhas acima.
conferir(etapa.count("UPDATE video_room_openpbl_class") == 2,
         "são dois caminhos de gravação, não um enfeitado",
         "um `if` com o mesmo UPDATE nos dois braços não protegeria nada")

modo_cod = corpo('@router.post("/{room_id}/openpbl/cadencia")',
                 '@router.post("/{room_id}/openpbl/voto")')
conferir('"auto_mode" not in row.keys()' in modo_cod and "503" in modo_cod,
         "a chave da cadência recusa com 503 e diz o motivo",
         "um 500 cru deixaria o host sem saber que falta a migration")

#: Iniciar a aula também tem de funcionar na janela: o INSERT não nomeia as
#: colunas novas, então vale nos dois schemas.
inicio = corpo('@router.post("/{room_id}/openpbl/start")',
               '@router.post("/{room_id}/openpbl/release')
insert = inicio[inicio.index("INSERT INTO video_room_openpbl_class"):]
insert = insert[:insert.index('"""', insert.index("ON CONFLICT"))]
for col in ("auto_mode", "stage_started_at", "vote_ends_at", "vote_stage", "votes"):
    conferir(col not in insert,
             "iniciar aula não escreve `%s`" % col,
             "nomeá-la quebraria o start num banco sem a 018")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

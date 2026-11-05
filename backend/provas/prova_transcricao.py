# -*- coding: utf-8 -*-
"""Transcrição com identificação de quem falou — e a presença que ela mexeu.

    python -B provas/prova_transcricao.py

## O que isto protege

1. **A identificação é da FAIXA, não de palpite.** No LiveKit o áudio pertence a
   um participante; "quem falou" é exato por construção. Um dia em que isso
   virar diarização por voz, a transcrição passa a errar justamente quando duas
   pessoas se atropelam — que é o normal numa plenária.
2. **O transcritor não pode virar um aluno que nunca vota.** Ele entra na sala
   como `hidden`, o que o esconde dos outros participantes mas **não** da API de
   servidor: `list_participants` continua devolvendo-o. E a lista de presentes é
   o que decide o ritmo do encontro — quem não vota conta como "não". Isto já
   valia para o GRAVADOR antes desta entrega: gravar a aula deixava a cadência
   mais difícil de passar, em silêncio.
3. **O `% conectados` é parâmetro.** Estava embutido como `sim * 2 > total`.
   Generalizar não pode ter mudado o comportamento de hoje junto — aqui se
   confere par por par.
4. **A transcrição é de quem dirige; o histórico é de todos.** A diferença é
   deliberada: isto é fala de gente passada por um reconhecedor que erra.
5. **As rotas do agente exigem o segredo**, e gravar é idempotente — o agente
   reenvia quando a resposta não chega.
6. **O agente e o backend têm DUAS cópias da lista de "quem é gente"**, porque o
   agente não importa o backend. É a situação de `ORDEM` x `_STAGES`, e a mesma
   solução: conferir aqui que não divergiram.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services.cadencia import LIMIAR_DE_AVANCO, apurar, maioria  # noqa: E402
from app.services import presenca  # noqa: E402

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
    ausência (já aconteceu duas vezes neste repositório). Use sempre sobre o
    `corpo()` de uma função, nunca sobre um router inteiro: isto remove TODOS os
    blocos de aspas triplas, e em vários routers daqui o SQL mora num deles.
    """
    sem: list[str] = []
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
        if marcas >= 2:
            continue
        if linha.strip().startswith("#"):
            continue
        sem.append(linha)
    return "\n".join(sem)


def corpo(fonte: str, assinatura: str) -> str:
    i = fonte.index(assinatura)
    resto = fonte[i + len(assinatura):]
    fim = len(resto)
    for marca in ("\nasync def ", "\ndef ", "\n@router.", "\nclass "):
        j = resto.find(marca)
        if j != -1:
            fim = min(fim, j)
    return assinatura + resto[:fim]


ROUTER = ler("app/routers/openpbl_class.py")
INTERNO = ler("app/routers/internal.py")
LIVEKIT = ler("app/services/livekit_service.py")
MIGRACAO = ler("app/migrations/022_transcricao.sql")
AGENTE = io.open(RAIZ.parent / "agent/transcritor.py", encoding="utf-8").read()
FRONT = (RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx").read_text(encoding="utf-8")

print("Transcrição com identificação")
print()
print("1) quem é gente na sala")
print()

conferir(presenca.e_pessoa("aluno@empresa.com"), "o aluno é gente")
conferir(not presenca.e_pessoa("EG_abc123"), "o gravador NÃO é",
         "ele republica o áudio de todos; contá-lo é contar a sala duas vezes")
conferir(not presenca.e_pessoa(presenca.identidade_do_transcritor("a1b2c3d4-x")),
         "o transcritor NÃO é", "`hidden` esconde do cliente, não da API de servidor")
conferir(not presenca.e_pessoa("aluno@empresa.com__bc"),
         "nem a aba que espelha o grupo", "é a MESMA pessoa entrando duas vezes")
conferir(not presenca.e_pessoa(""), "identidade vazia não é gente")
conferir(presenca.so_pessoas(["b", "a", "a", "EG_1"]) == ["a", "b"],
         "`so_pessoas` ordena e tira repetição")

print()
print("2) o defeito concreto: gravar a aula travava a cadência")
print()

# Uma pessoa na sala, o gravador ligado, e ela vota "sim".
votos = {"aluno@empresa.com": True}
crus = ["aluno@empresa.com", "EG_gravador"]

sim_cru, total_cru = apurar(votos, crus)
conferir(not maioria(sim_cru, total_cru),
         "SEM o filtro, 1 sim em 2 'presentes' NÃO avança",
         "o gravador é um 'aluno' que nunca vota, isto é, um não permanente")

sim, total = apurar(votos, presenca.so_pessoas(crus))
conferir(total == 1 and maioria(sim, total),
         "COM o filtro, a mesma sala avança",
         "era o sintoma: a sala só não andava quando estava sendo gravada")

presentes = corpo(ROUTER, "async def _presentes(room_id: str) -> list[str]:")
conferir("presenca.so_pessoas(" in so_codigo(presentes),
         "e `_presentes` aplica o filtro",
         "a regra certa com entrada mentirosa é o defeito desta sala desde sempre")

print()
print("3) o `% conectados` virou parâmetro sem mudar o comportamento de hoje")
print()

conferir(LIMIAR_DE_AVANCO == 0.5,
         "o padrão é 0,5 (maioria estrita)",
         "subir isto no mesmo deploy mudaria o ritmo de toda sala existente")

iguais = all(
    maioria(s, t, 0.5) == (s * 2 > t)
    for t in range(0, 31) for s in range(0, t + 1))
conferir(iguais,
         "limiar 0,5 == `sim * 2 > total` em todo par até 30",
         "é o que prova que a generalização não trocou a regra")

conferir(maioria(7, 12, 0.5) and not maioria(7, 12, 0.66),
         "7 de 12 avança em 0,5 e NÃO avança em 0,66",
         "o mesmo placar, duas respostas: é o parâmetro fazendo efeito")
conferir(maioria(8, 12, 0.66) and not maioria(8, 12, 2 / 3),
         "e a comparação é estrita: 8 de 12 passa em 0,66 e não em 2/3",
         "`8 > 8.0` é falso — quem quiser dois terços na prática usa 0,66")
conferir(not maioria(0, 0, 0.0) and not maioria(0, 0, 0.5),
         "sala VAZIA não avança com nenhum limiar",
         "um encontro correndo sozinho até o fim, sem ninguém dentro")
conferir("sim > total * limiar" in so_codigo(corpo(
             ler("app/services/cadencia.py"),
             "def maioria(sim: int, total: int, limiar: float = LIMIAR_DE_AVANCO) -> bool:")),
         "e a comparação é ESTRITA no fonte",
         "com `>=`, 0 de 0 passa: é a trava que de fato segura a sala vazia")

print()
print("4) a leitura é de quem dirige; sem a tabela, fica inerte")
print()

rota = corpo(ROUTER, "async def listar_transcricao(room_id: str, user: CurrentUser = Depends(get_current_user)):")
codigo_da_rota = so_codigo(rota)
conferir("_require_host(user)" in codigo_da_rota,
         "a rota exige host",
         "o erro do ASR na tela do colega abre uma discussão que não é a da aula")
pos_guarda = codigo_da_rota.find('tem_tabela("video_room_transcricao")')
pos_select = codigo_da_rota.find("FROM video_room_transcricao")
conferir(pos_guarda != -1 and pos_select != -1 and pos_guarda < pos_select,
         "e pergunta pela tabela ANTES de consultar",
         "publicar não aplica migration (a 018 ensinou)")
conferir("ORDER BY inicio" in rota,
         "devolve em ordem da FALA",
         "ordenar pela chegada ordenaria pelo tempo de GPU")

print()
print("5) as rotas do agente: segredo, idempotência e etapa do servidor")
print()

for assinatura, nome in (
    ("async def post_node_metrics(", "métricas do nó"),
    ("async def salas_para_transcrever(", "lista de salas"),
    ("async def post_transcricao(", "gravar fala"),
):
    conferir("_autorizar(x_node_secret)" in so_codigo(corpo(INTERNO, assinatura)),
             f"`{nome}` exige o segredo do nó")

guarda = corpo(INTERNO, "def _autorizar(segredo: str | None) -> None:")
conferir("not settings.node_secret" in so_codigo(guarda),
         "servidor SEM segredo configurado recusa todo mundo",
         "o contrário faria de um env esquecido uma rota aberta de escrita")

gravar = corpo(INTERNO, "async def post_transcricao(")
codigo_gravar = so_codigo(gravar)
conferir("ON CONFLICT (room_id, identity, inicio) DO NOTHING" in gravar,
         "gravar é idempotente",
         "o agente reenvia quando a resposta não chega")
conferir("CREATE UNIQUE INDEX" in MIGRACAO
         and "video_room_transcricao(room_id, identity, inicio)" in MIGRACAO,
         "e a chave única existe no schema",
         "`ON CONFLICT` sem índice correspondente é erro em tempo de execução")

pos_texto = codigo_gravar.find('if not texto:')
pos_insert = codigo_gravar.find("INSERT INTO video_room_transcricao")
conferir(pos_texto != -1 and pos_texto < pos_insert,
         "texto vazio não grava linha",
         "silêncio que o reconhecedor devolveu em branco não é fala de ninguém")
conferir('tem_tabela("video_room_transcricao")' in codigo_gravar,
         "e sem a tabela devolve 200 sem gravar",
         "4xx faria o agente reenviar para sempre")
conferir("presenca.e_pessoa(body.identity)" in codigo_gravar,
         "fala do gravador é recusada também aqui",
         "segunda tranca, do lado de quem grava")
conferir("SELECT stage FROM video_room_openpbl_class" in gravar
         and "body.stage" not in codigo_gravar,
         "a ETAPA é estampada pelo servidor, não enviada pelo agente",
         "pedir ao agente que acompanhe a cadência criaria uma 2ª cópia do estado")

salas = so_codigo(corpo(INTERNO, "async def salas_para_transcrever("))
conferir("c.stage <> 'done'" in salas,
         "só salas com aula em andamento entram na lista",
         "transcrever reunião qualquer gastaria GPU sem ninguém pedir")
conferir("livekit_participant_counts()" in salas and "<= 0" in salas,
         "e só as que têm gente conectada",
         "entrar em sala vazia mantém modelo carregado à espera de ninguém")

print()
print("6) o token do transcritor: ouve, não publica, não aparece")
print()

token = so_codigo(corpo(LIVEKIT, "def create_token_do_transcritor(*, room_name: str, identity: str) -> str:"))
conferir("can_publish=False" in token and "can_publish=True" not in token,
         "não pode publicar nada",
         "agente que PODE publicar é agente que, com um defeito, publica")
conferir("hidden=True" in token,
         "e não aparece na grade de ninguém",
         "senão a aula ganharia um tile fantasma")
conferir("can_subscribe=True" in token, "mas assina o áudio, que é o que ele precisa")
conferir("room_admin=True" not in token and "room_record=True" not in token,
         "e não tem poder de administrar a sala",
         "ouvir não exige poder expulsar ninguém")

print()
print("7) o agente e o backend não podem divergir sobre quem é gente")
print()

for nome, valor in (
    ("PREFIXO_DO_GRAVADOR", presenca.PREFIXO_DO_GRAVADOR),
    ("PREFIXO_DO_TRANSCRITOR", presenca.PREFIXO_DO_TRANSCRITOR),
    ("SUFIXO_DO_ESPELHO", presenca.SUFIXO_DO_ESPELHO),
):
    conferir(f'{nome} = "{valor}"' in AGENTE,
             f"o agente usa o mesmo `{nome}` ({valor!r})",
             "divergir faz o transcritor transcrever a aula duas vezes")

e_pessoa_do_agente = corpo(AGENTE, "def e_pessoa(identity: str) -> bool:")
for marca in ("PREFIXO_DO_GRAVADOR", "PREFIXO_DO_TRANSCRITOR", "SUFIXO_DO_ESPELHO"):
    conferir(marca in so_codigo(e_pessoa_do_agente),
             f"e o filtro dele consulta `{marca}`")

print()
print("8) o agente: identidade da faixa, thread para o ASR, fila com teto")
print()

ouvir = so_codigo(corpo(AGENTE, "    async def _ouvir(self, track: rtc.Track, participante: rtc.RemoteParticipant) -> None:"))
conferir(ouvir.count("identity=participante.identity") == 2
         and "identity=participante.name" not in ouvir,
         "as DUAS gravações atribuem pela identidade do dono da faixa",
         "pelo nome, a turma com duas Anas atribui a fala à Ana errada")
conferir("nome=participante.name or participante.identity" in ouvir,
         "e leva o nome exibido como retrato")
conferir("rtc.AudioStream(track, sample_rate=TAXA" in ouvir,
         "o áudio chega já na taxa do reconhecedor",
         "reamostrar errado degrada a transcrição em silêncio")
conferir("fechar_agora()" in so_codigo(corpo(AGENTE, "    async def _ouvir(self, track: rtc.Track, participante: rtc.RemoteParticipant) -> None:")),
         "e quem desconecta não perde a última frase")

trab = so_codigo(corpo(AGENTE, "async def trabalhador(n: int, fila: asyncio.Queue, motor, cliente: httpx.AsyncClient) -> None:"))
conferir("asyncio.to_thread(motor.transcrever" in trab,
         "o reconhecimento roda em THREAD",
         "no laço de eventos ele congelaria a leitura de áudio de todas as salas")
conferir("vale_gravar(texto)" in trab,
         "e a frase-fantasma do Whisper não é enviada",
         "gravá-la poria na boca de um aluno algo que ele não disse")

fila = so_codigo(corpo(AGENTE, "    def _enfileirar(self, fala: Fala) -> None:"))
conferir("QueueFull" in fila and "descartadas" in fila and "logger.error" in fila,
         "fila cheia CONTA e registra o descarte",
         "transcrição que some em silêncio pareceria uma aula calada")

principal = so_codigo(corpo(AGENTE, "async def principal(uma_rodada: bool = False) -> int:"))
conferir("if desejadas is not None:" in principal,
         "falha ao perguntar as salas NÃO esvazia as sessões",
         "'não sei' e 'nenhuma sala' são coisas diferentes")

buscar = so_codigo(corpo(AGENTE, "async def buscar_salas(cliente: httpx.AsyncClient) -> list[dict] | None:"))
conferir("if r.status_code == 401:" in buscar and "return None" in buscar,
         "e 401 é erro alto, não lista vazia",
         "NODE_SECRET errado se manifestaria como transcrição que nunca aparece")

print()
print("9) a tela: só o host, e sem linha repetida")
print()

efeito = FRONT[FRONT.index("// OpenPBL: TRANSCRIÇÃO do encontro"):]
efeito = efeito[:efeito.index("// Auto-gera o class-code")]
conferir("if (!scorm || !amStaff) return;" in efeito,
         "o aluno nem chama a rota",
         "seria um 403 por minuto no log de cada aluno da turma")
conferir("new Map(atuais.map((f) => [`${f.identity}|${f.inicio}`, f]))" in efeito,
         "e a fala é deduplicada por (quem, início)",
         "é a mesma chave única do banco; duas linhas iguais leem como repetição")
conferir('event === "transcricao"' in efeito,
         "a fala nova entra pelo evento, sem nova consulta")

painel = FRONT[FRONT.index("function PainelDaTranscricao("):]
painel = painel[:painel.index("/* ── Cadência")]
conferir("if (!itens.length) return null;" in painel,
         "painel vazio não aparece",
         "'Transcrição (0)' sugeriria que ninguém falou")
conferir("{f.nome || f.identity}" in painel,
         "e cada linha diz QUEM falou",
         "sem o nome isto é uma parede de texto sem dono")
conferir("<PainelDaTranscricao" in FRONT
         and "{pblActive && amStaff && (" in FRONT,
         "e a tela só o monta para quem dirige")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

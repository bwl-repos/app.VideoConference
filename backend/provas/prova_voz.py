# -*- coding: utf-8 -*-
"""A sala fala as instruções fixas do encontro ("texto + áudio").

    python -B provas/prova_voz.py

## O que isto protege

1. **A chave do mp3 é função do TEXTO.** É o que torna tudo idempotente: a
   primeira sala paga o Polly, as seguintes não pedem nada, e um texto editado
   perde a voz velha em vez de a sala dizer uma coisa enquanto a tela mostra
   outra. Nada é gravado no banco — por isso este item não tem migration.
2. **`audios[i]` fala `paragrafos[i]`.** Parágrafo vazio entra como string
   vazia em vez de ser descartado. Descartar deslocaria os índices e a sala
   falaria o parágrafo errado, sem erro nenhum na tela — o defeito mais caro
   possível aqui, porque parece funcionar.
3. **O que já existe não é pedido de novo**, e o mesmo texto repetido em duas
   seções é pedido UMA vez. São chamadas pagas.
4. **Credencial sem permissão não é "ausente".** Se `tem()` tratasse qualquer
   erro como ausência, a sala pediria e pagaria a mesma síntese em toda criação
   de sala, para sempre, sem nada no log explicando.
5. **Uma falha não cala as outras falas.** Um aviso sem voz é melhor que um
   encontro em que a voz parou no terceiro parágrafo porque o quarto falhou.
6. **Um mapa único de etapa→seção.** Com duas cópias (uma da tela, uma da voz),
   divergir faz a sala falar o texto de uma seção enquanto mostra outra.
7. **A aba espelho do grupo (`__bc`) fica muda** — é a mesma pessoa duas vezes.

## O que daqui NÃO se prova

O outro lado do contrato (`POST /api/voz/sintetizar`, cabeçalho `X-Voz-Token`)
mora no CoreService, que é outro repositório: afirmar aqui sobre arquivos de lá
faria esta prova falhar em qualquer máquina que não tenha os dois. O lado de lá
tem a sua própria prova, e quem detecta divergência entre os dois é a rota de
conferência `POST /{room_id}/openpbl/voz`, que devolve o número.
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services import voz  # noqa: E402

falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-58s %s" % ("ok" if cond else "FALHA", oque, porque))


def ler(caminho: str) -> str:
    return io.open(RAIZ / caminho, encoding="utf-8").read()


def so_codigo(texto: str) -> str:
    """Sem comentários e sem docstrings — só o que executa."""
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


PORTA = ler("app/services/voz_porta.py")
ROOMS = ler("app/routers/rooms.py")
AULA = ler("app/routers/openpbl_class.py")
FRONT = (RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx").read_text(encoding="utf-8")
SDK = (RAIZ.parent / "frontend/src/lib/video-rooms-sdk.ts").read_text(encoding="utf-8")

#: Um roteiro como o CustomerApp manda: duas seções, um aviso REPETIDO entre
#: elas, e um parágrafo vazio no meio (o formulário permite).
ROTEIRO = {
    "secoes": [
        {
            "key": "abertura",
            "titulo": "Abertura e registro",
            "blocosFixos": [
                {"titulo": "Registro de Presença",
                 "paragrafos": ["Aponte o smartphone para o QR Code na tela.",
                                "",
                                "Digite o class code no chat."]},
                {"titulo": "Importante!", "paragrafos": ["Sem smartphone, só como ouvinte."]},
            ],
        },
        {
            "key": "plenaria",
            "titulo": "Plenária",
            "blocosFixos": [
                # o MESMO aviso da abertura, com espaçamento diferente
                {"paragrafos": ["  Digite o class code   no chat.  ", "Uma questão por vez."]},
            ],
        },
    ],
    # O que VARIA por episódio. `bannerFundo` é chave de bucket, não prosa.
    "campos": {
        "sinopseParte1": "Carlos lida com as consequências de um dia desorganizado.",
        "sinopseParte2": "",
        "questoesOrientadoras": ["O que você faria?", "", "Quem decide isso?"],
        "bannerFundo": "banners/ep5-fundo.png",
        "relembrandoEpisodio": "Uma questão por vez.",   # IGUAL a um texto fixo
    },
}

print("A sala fala as instruções fixas do encontro")
print()
print("1) a chave do mp3 é função do texto, e de mais nada")
print()

conferir(voz.normalizar("  Aponte o\n  smartphone  ") == "Aponte o smartphone",
         "o texto normaliza antes de entrar no hash",
         "reindentar o schema.ts não pode gerar síntese paga")
conferir(voz.chave(" Um texto ") == voz.chave("Um   texto"),
         "espaçamento diferente, MESMA chave")
conferir(voz.chave("Um texto") != voz.chave("Um texto."),
         "texto diferente, chave diferente",
         "é o que faz o áudio velho não ser servido com o texto novo")
conferir(voz.chave("x").startswith("voz/") and voz.chave("x").endswith(".mp3"),
         "a chave mora sob o prefixo `voz/`",
         "a limpeza de gravação apaga por idade; a instrução não envelhece")

antes = voz.chave("Aponte o smartphone")
voz.VERSAO = str(int(voz.VERSAO) + 1)
depois = voz.chave("Aponte o smartphone")
voz.VERSAO = str(int(voz.VERSAO) - 1)
conferir(antes != depois and voz.chave("Aponte o smartphone") == antes,
         "bumpar VERSAO invalida TODO o cache",
         "a saída para o que o perfil não descreve (timbre que mudou do lado de lá)")

# ── 1b. E A VOZ ENTRA NA CHAVE ──────────────────────────────────────────────
#
# A voz passou a ser CONFIGURADA no painel admin. Sem o perfil no hash, o mesmo
# texto em duas vozes daria o mesmo endereço: o objeto da voz anterior já estaria
# no bucket, e a sala falaria com a voz velha para sempre. O sintoma é a
# configuração "não funcionar" — e nada erra em lugar nenhum.
conferir(voz.chave("Aponte", "polly:Camila:generative")
         != voz.chave("Aponte", "elevenlabs:abc123"),
         "a VOZ entra na chave: texto igual, voz outra, endereço outro",
         "sem isto, trocar a voz no painel serviria o audio da voz anterior")
conferir(voz.chave("Aponte", "elevenlabs:abc123")
         == voz.chave("Aponte", "elevenlabs:abc123"),
         "e a mesma voz com o mesmo texto não paga duas vezes")
conferir(voz.chave("Aponte", "polly:Camila") != voz.chave("Aponte"),
         "CONTROLE: perfil vazio não é um perfil qualquer",
         "senão a voz de fábrica e uma voz escolhida dividiriam o mesmo objeto")

print()
print("2) quais parágrafos a sala precisa falar")
print()

paragrafos = voz.paragrafos_do_roteiro(ROTEIRO)
conferir(paragrafos == ["Aponte o smartphone para o QR Code na tela.",
                        "Digite o class code no chat.",
                        "Sem smartphone, só como ouvinte.",
                        "Uma questão por vez."],
         "na ordem de leitura, sem vazios e SEM REPETIR",
         "o mesmo aviso em duas seções é uma síntese, não duas")
conferir(voz.paragrafos_do_roteiro(None) == []
         and voz.paragrafos_do_roteiro({"secoes": None}) == []
         and voz.paragrafos_do_roteiro({"secoes": [{"blocosFixos": [{}]}]}) == [],
         "roteiro ausente ou torto devolve lista vazia",
         "sala antiga sem roteiro não pode derrubar a criação de sala")

print()
print("2b) e o que varia por episódio")
print()

campos = voz.textos_dos_campos(ROTEIRO)
conferir("Carlos lida com as consequências de um dia desorganizado." in campos,
         "o campo de texto entra")
conferir("O que você faria?" in campos and "Quem decide isso?" in campos,
         "cada item de um campo de LISTA entra")
conferir("" not in campos and len(campos) == 4,
         "item vazio não vira pedido ao Polly", str(len(campos)))
conferir("banners/ep5-fundo.png" not in campos
         and "bannerFundo" in voz.CAMPOS_SEM_VOZ,
         "`bannerFundo` NÃO entra",
         "é chave de bucket: a sala leria 'banners barra ep5 ponto png'")

tudo = voz.textos_do_roteiro(ROTEIRO)
conferir(len(tudo) == len(set(tudo)),
         "fixos + campos, sem repetir",
         "'Uma questão por vez.' está nos dois e é UMA síntese")
conferir(set(tudo) == set(paragrafos) | set(campos),
         "e nada se perde no caminho")

print()
print("3) o alinhamento entre a voz e o parágrafo (o defeito que parece funcionar)")
print()

import copy  # noqa: E402

marcado = voz.com_audios(copy.deepcopy(ROTEIRO), lambda k: "URL:" + k)
bloco = marcado["secoes"][0]["blocosFixos"][0]
conferir(len(bloco["audios"]) == len(bloco["paragrafos"]) == 3,
         "`audios` tem o MESMO tamanho de `paragrafos`")
conferir(bloco["audios"][1] == "",
         "o parágrafo vazio entra como vazio, e não é descartado",
         "descartar deslocaria os índices e a sala falaria o parágrafo errado")
conferir(bloco["audios"][0] == "URL:" + voz.chave(bloco["paragrafos"][0])
         and bloco["audios"][2] == "URL:" + voz.chave(bloco["paragrafos"][2]),
         "e cada URL é a do SEU parágrafo")

repetido = marcado["secoes"][1]["blocosFixos"][0]["audios"][0]
conferir(repetido == "URL:" + voz.chave("Digite o class code no chat."),
         "o aviso repetido aponta para o MESMO mp3 nas duas seções")

def explode(_k):
    raise RuntimeError("bucket fora do ar")

tortos = voz.com_audios(copy.deepcopy(ROTEIRO), explode)
tbloco = tortos["secoes"][0]["blocosFixos"][0]
conferir(tbloco["audios"] == ["", "", ""] and len(tbloco["paragrafos"]) == 3,
         "assinatura que falha deixa a sala MUDA, não quebrada",
         "um encontro sem voz é um encontro; um travado não é")

vozes = marcado["audiosDosCampos"]
conferir(vozes["sinopseParte1"] == "URL:" + voz.chave(ROTEIRO["campos"]["sinopseParte1"]),
         "campo de texto ganha UMA voz")
conferir(isinstance(vozes["questoesOrientadoras"], list)
         and len(vozes["questoesOrientadoras"]) == 3
         and vozes["questoesOrientadoras"][1] == "",
         "campo de lista ganha uma lista do MESMO tamanho, com vazio no vazio",
         "a tela casa item e voz por índice")
conferir("bannerFundo" not in vozes and "sinopseParte2" not in vozes,
         "imagem e campo vazio ficam de fora")
conferir(marcado["campos"]["sinopseParte1"] == ROTEIRO["campos"]["sinopseParte1"],
         "e `campos` continua sendo o TEXTO",
         "voz dentro de `campos` apareceria escrita como link na sinopse")

# O que a leitura calcula tem de ser o que o aquecimento gravou.
lidas = {u[4:] for s in marcado["secoes"] for b in s["blocosFixos"]
         for u in b["audios"] if u}
lidas |= {u[4:] for v in vozes.values()
          for u in (v if isinstance(v, list) else [v]) if u}
escritas = {voz.chave(t) for t in voz.textos_do_roteiro(ROTEIRO)}
conferir(lidas == escritas,
         "a chave que a sala LÊ é a mesma que o aquecimento ESCREVE",
         "as duas se recalculam do texto; divergir deixaria a sala muda sempre")

print()
print("4) o que se pede ao sintetizador, e o que não se pede")
print()


def rodar(textos, presentes=(), falha_ao_sintetizar=(), tem_explode=(), devolve_vazio=()):
    pedidos: list[str] = []
    guardados: list[str] = []

    def tem(chave):
        if chave in tem_explode:
            raise RuntimeError("AccessDenied")
        return chave in presentes

    async def sintetizar(texto):
        pedidos.append(texto)
        if texto in falha_ao_sintetizar:
            raise RuntimeError("Polly recusou")
        if texto in devolve_vazio:
            return b""
        return b"mp3"

    contas = asyncio.run(voz.garantir(
        textos, tem=tem, sintetizar=sintetizar,
        guardar=lambda c, m: guardados.append(c)))
    return contas, pedidos, guardados


contas, pedidos, guardados = rodar(paragrafos, presentes={voz.chave(paragrafos[1])})
conferir(pedidos == [paragrafos[0], paragrafos[2], paragrafos[3]],
         "pede só o que falta no bucket")
conferir(contas == {"pedidos": 3, "prontos": 3, "falhas": 0, "ja_tinha": 1},
         "e conta o que fez", str(contas))
conferir(guardados == [voz.chave(p) for p in (paragrafos[0], paragrafos[2], paragrafos[3])],
         "guardando cada mp3 na chave do seu texto")

contas, pedidos, _ = rodar(["Mesmo aviso", "  Mesmo   aviso  ", "Outro"])
conferir(pedidos == ["Mesmo aviso", "Outro"],
         "o mesmo texto não é pedido duas vezes na mesma rodada",
         "é chamada paga, e vinha do roteiro com espaçamento diferente")

contas, pedidos, guardados = rodar(paragrafos, falha_ao_sintetizar={paragrafos[1]})
conferir(contas["falhas"] == 1 and contas["prontos"] == 3,
         "uma fala que falha não cala as outras três", str(contas))
conferir(voz.chave(paragrafos[1]) not in guardados,
         "e o que falhou não é gravado")

contas, _, guardados = rodar(paragrafos, devolve_vazio={paragrafos[0]})
conferir(voz.chave(paragrafos[0]) not in guardados and contas["falhas"] == 1,
         "mp3 vazio não é gravado como se fosse voz",
         "gravado, o objeto existiria e `tem()` nunca mais pediria a síntese")

contas, pedidos, _ = rodar(paragrafos, tem_explode={voz.chave(paragrafos[0])})
conferir(pedidos == [paragrafos[1], paragrafos[2], paragrafos[3]],
         "erro ao CONSULTAR o bucket não vira 'ausente'",
         "senão a sala pagaria a mesma síntese em toda criação de sala")
conferir(contas["falhas"] == 1, "e conta como falha, para aparecer no log")

porta_tem = so_codigo(corpo(PORTA, "def tem(chave: str) -> bool:"))
conferir('codigo in ("404", "NoSuchKey", "NotFound")' in porta_tem
         and "raise" in porta_tem,
         "a porta do bucket distingue ausência de erro de credencial")

print()
print("5) quando a síntese acontece")
print()

criar = so_codigo(corpo(ROOMS, "async def create_room("))
conferir("_aquecer_voz(body.roteiro)" in criar,
         "criar sala aquece a voz do roteiro",
         "a criação é dias antes da aula; a abertura é com os alunos esperando")
aquecer = so_codigo(corpo(ROOMS, "def _aquecer_voz(roteiro) -> None:"))
conferir("asyncio.create_task" in aquecer and "_aquecimentos.add(tarefa)" in aquecer,
         "em segundo plano, com referência FORTE à tarefa",
         "`create_task` só guarda referência fraca: a coleta mataria pela metade")
conferir("except RuntimeError:" in aquecer,
         "e sem loop de eventos a sala nasce sem voz, em vez de dar erro")

voz_rota = so_codigo(corpo(AULA, "async def preparar_voz("))
conferir("await _require_host(user)" in voz_rota,
         "a rota de conferir/consertar é só de quem dirige")
conferir("await voz_porta.preparar(roteiro)" in voz_rota,
         "e roda a MESMA preparação do aquecimento",
         "duas implementações divergiriam no dia do conserto")

conferir("_roteiro_com_voz(_roteiro_com_banner(" in ROOMS,
         "a sala recebe as URLs na carga, ao lado do banner",
         "as duas se assinam a cada carga: a chave dura meses, a URL seis horas")

print()
print("6) a sala, na tela")
print()

conferir("audios?: string[]" in SDK,
         "o SDK declara a voz de cada parágrafo")
conferir("audiosDosCampos?: Record<string, string | string[]>;" in SDK,
         "e a voz dos campos, com a MESMA forma do campo")
conferir("return rListaComVoz(r, name).map((p) => p.texto);" in FRONT,
         "a tela filtra texto e voz juntos, num lugar só",
         "dois filtros deslocariam um do outro e a sala leria o card errado")
conferir("setFilaDaVoz(cards.slice(antes.ate, shownCount).filter(Boolean));" in FRONT,
         "revelar um card fala SÓ o card que entrou",
         "a fila inteira recomeçaria a etapa a cada clique do facilitador")
conferir("if (antes.stage !== pblStage) {" in FRONT,
         "e trocar de etapa fala os fixos mais o que já está revelado")
conferir(FRONT.count('return "revisitando";') == 1,
         "existe UM mapa de etapa→seção, não dois",
         "duas cópias divergem e a sala fala uma seção enquanto mostra outra")
conferir('case "registration_open": case "amplify_code": case "registration_close":'
         in FRONT,
         "e `amplify_code` cai em `abertura`, com as de registro",
         "sem isso ela cairia no `default` e a tela mostraria FEEDBACK "
         "no meio do registro de presença")

#: O MAPA NÃO TEM CATCH-ALL. Ele devolvia "feedback" para toda etapa sem caso
#: próprio, e na TELA isso nunca apareceu (gráfico e cascatas cobrem a seção) —
#: mas a VOZ lê do mesmo mapa, e a sala anunciava a última atividade do encontro
#: no meio da análise de riscos. Uma só ocorrência: a de `release_feedback`/`done`.
conferir(FRONT.count('return "feedback";') == 1,
         "etapa sem texto do roteiro não cai em `feedback`: cai em nada",
         "um `else` que 'não acontece' para a tela acontece para a voz")
conferir('if (stage === "question") return rIntroQuestoes(r);' in FRONT
         and 'if (stage === "plenary") return rBlocos(r, secao).slice(0, 1);' in FRONT,
         "plenária e questões repartem a MESMA seção, 1º bloco e os seguintes",
         "é a divisão que a tela já fazia; a voz lia a seção inteira nas duas")
conferir(FRONT.count("blocosDaEtapa(") == 3,
         "e tela e voz leem a MESMA lista de blocos (definição + os dois usos)",
         "duas listas divergem e a sala fala um texto enquanto mostra outro")
conferir("const blocos = blocosDaEtapa(roteiro, stage);" in FRONT,
         "a tela da etapa lê desse mapa")
conferir('pblStage === "plenary" ? paresRelembrando' in FRONT,
         "o card único da plenária também é falado",
         "era o único conteúdo variável em tela que a sala não lia")
conferir("const repete = !!chaveDosFixos && chaveDosFixos === antes.fixos;" in FRONT,
         "trocar de etapa dentro da MESMA seção não relê o texto fixo",
         "3 etapas compartilham a abertura e 2 duram 30s: a fala se cortava")
conferir("onRepetir={repetirAEtapa}" in FRONT,
         "e o ↻ remonta a fila inteira da etapa, não só o último card",
         "a fila corrente guarda o delta; 'não ouvi' pede a etapa toda")
conferir("audiosDaEtapa(roteiro, pblStage)" in FRONT
         and "useVozDaEtapa(filaDaVoz," in FRONT,
         "a voz é da ETAPA, não do painel visível",
         "o painel muda com o papel; a fala do facilitador era a mesma para todos")
conferir("!isBroadcast(identity || \"\")" in FRONT,
         "a aba espelho do grupo fica muda",
         "é a mesma pessoa duas vezes: ouviria a instrução em dobro")
conferir("audio.play().catch(() => segue(i, false))" in FRONT,
         "recusa do navegador ou 404 seguem para a próxima fala",
         "autoplay sem gesto (aba do gravador) e texto sem voz são normais")
conferir("if (morto || i !== atual) return;" in FRONT,
         "e `ended` + recusa na mesma fala não pulam duas",
         "sem o índice, uma instrução seria engolida")
conferir("{pblActive && amStaff && temVozNaEtapa && (" in FRONT,
         "o controle de silenciar/repetir é só de quem dirige",
         "e não aparece em etapa sem nada a falar")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

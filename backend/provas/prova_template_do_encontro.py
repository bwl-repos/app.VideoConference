# -*- coding: utf-8 -*-
"""O encontro configurável: temporizadores, textos, pausas e voz.

    python -B provas/prova_template_do_encontro.py

## O que isto protege

1. **A configuração de fábrica é o comportamento de hoje.** Tornar algo
   ajustável não pode mudar o ritmo de nenhum encontro no mesmo deploy. A base
   é LIDA de `cadencia.py`, e esta prova confere que ela não virou uma segunda
   tabela de durações.
2. **O catálogo da tela não divergiu das outras cópias.** A ordem das etapas já
   vivia em três arquivos, e a tela divergir em silêncio custou uma produção
   (ver `prova_cadencia.py`). O catálogo é a QUARTA leitura da mesma lista: ele
   sai de `ORDEM`, e título, ação e seção são conferidos contra `STEPS` e
   `secaoDaEtapa` no `VideoRoom.tsx`.
3. **`pausas[i]` acompanha `paragrafos[i]`.** É o mesmo contrato de `audios[i]`:
   desalinhar faz a sala calar no lugar errado, sem erro nenhum na tela. A
   validação tem de garantir o alinhamento mesmo quando a tela manda uma lista
   curta, longa ou nenhuma.
4. **A voz entra na CHAVE do mp3.** Sem isso, trocar a voz no painel serviria o
   áudio da voz anterior para sempre — a configuração "não funciona" e nada
   erra. (A chave em si é prova de `prova_voz.py`; aqui se confere que o perfil
   muda quando a voz muda.)
5. **O texto CONGELA na criação da sala.** Aplicar o template na leitura faria
   uma edição no painel trocar a instrução na cara de uma turma no meio da
   leitura.
6. **A validação PODA, não recusa.** O painel é a única forma de ajustar o
   ritmo: um 422 por um campo mal digitado deixaria quem opera sem saída. E o
   valor devolvido é o efetivo, não o digitado.
7. **Inerte sem a tabela.** Publicar não aplica migration neste repositório.
   Sem a tabela, tudo devolve a base — que é o comportamento de hoje.

## O que daqui NÃO se prova

Que a tabela existe em produção, e que o CoreService aceita o provedor pedido:
as duas coisas só se sabem com o banco e o outro serviço na frente. Quem
responde a primeira é o campo `persistente` da própria tela; a segunda, o
contador de `POST /api/admin/encontro/aquecer`.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.services import cadencia, encontro  # noqa: E402

falhas = 0


def conferir(cond: bool, oque: str, porque: str = "") -> None:
    global falhas
    falhas += not cond
    print("  %-6s %-62s %s" % ("ok" if cond else "FALHA", oque, porque))


def ler(caminho: str) -> str:
    return io.open(RAIZ / caminho, encoding="utf-8").read()


#: A tela da sala sao DOIS arquivos desde que o preview do painel passou a
#: usar os mesmos componentes da aula: o sequenciador (`STEPS`) ficou no
#: VideoRoom e a tela do roteiro foi para `RoteiroStage.tsx`. As afirmacoes
#: daqui sao sobre a TELA, nao sobre um arquivo.
FRONT = (ler("../frontend/src/components/video/VideoRoom.tsx")
         + ler("../frontend/src/components/video/RoteiroStage.tsx"))
SDK = ler("../frontend/src/lib/video-rooms-sdk.ts")
VIDEOROOM = ler("../frontend/src/components/video/VideoRoom.tsx")
ROOMS = ler("app/routers/rooms.py")
ROTA = ler("app/routers/encontro.py")
TELA = ler("../frontend/src/admin/EncontroPage.tsx")

print("O encontro configuravel: etapas, tempos, textos e voz")
print()
print("1) a configuracao de fabrica E o comportamento de hoje")

BASE = encontro.base()
conferir(BASE["duracoes"] == dict(cadencia.DURACAO_DA_ETAPA),
         "as duracoes da base saem de `cadencia.DURACAO_DA_ETAPA`",
         "copiadas, divergiriam no primeiro ajuste pelo codigo")
conferir(BASE["janela_voto_s"] == int(cadencia.JANELA_DO_VOTO.total_seconds())
         and BASE["tolerancia_s"] == int(cadencia.TOLERANCIA.total_seconds())
         and BASE["limiar"] == cadencia.LIMIAR_DE_AVANCO,
         "e a janela, a tolerancia e o limiar tambem",
         "tornar ajustavel nao pode mudar o ritmo no mesmo deploy")

padrao = encontro.parametros(BASE)
conferir(padrao.duracoes == cadencia.PADRAO.duracoes
         and padrao.janela_voto == cadencia.PADRAO.janela_voto
         and padrao.tolerancia == cadencia.PADRAO.tolerancia
         and padrao.limiar == cadencia.PADRAO.limiar,
         "a base, lida como parametros, E o `PADRAO` da cadencia",
         "é o que garante que ninguem sente a diferenca sem configurar nada")

# E a regra pura continua significando o mesmo sem parametro nenhum: a
# assinatura nova nao pode ter mudado o comportamento de quem nao a usa.
conferir("params: Parametros = PADRAO" in ler("app/services/cadencia.py"),
         "`decidir` sem parametros segue valendo as constantes",
         "senao toda prova e todo chamador antigo mudariam de comportamento")

conferir(encontro.atuais() == BASE,
         "antes da primeira leitura do banco, a configuracao E a base",
         "sem isto a tela mostraria contagem zerada ao subir o servico")

print()
print("2) o catalogo da tela nao divergiu das outras copias da lista de etapas")

conferir(tuple(encontro.CATALOGO) == tuple(cadencia.ORDEM),
         "o catalogo tem exatamente as etapas de `ORDEM`, na ordem",
         "a QUARTA copia da lista: divergir deixa a tela configurando o nada")
conferir([e["id"] for e in encontro.catalogo_para_tela(BASE)] == list(cadencia.ORDEM),
         "e a tela recebe a ordem derivada de `ORDEM`, nao uma lista propria")

corpo_steps = re.search(r"const STEPS: StepDef\[\] = \[(.*?)\n\];", FRONT, re.S).group(1)
steps = {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(
    r'\{ id: "([a-z_]+)",\s*action: "([^"]+)",\s*head: "([^"]+)" \}', corpo_steps)}
conferir(len(steps) == len(cadencia.ORDEM),
         "as %d etapas de STEPS foram lidas da tela da sala" % len(steps),
         "regex que nao casa deixaria as comparacoes abaixo vazias, e verdes")
divergentes = [e for e in cadencia.ORDEM
               if steps.get(e) != (encontro.CATALOGO[e]["acao"], encontro.CATALOGO[e]["titulo"])]
conferir(not divergentes,
         "titulo e acao de cada etapa batem com `STEPS` no VideoRoom",
         "divergir faz o painel prometer uma acao que o ▶ nao executa: %s" % divergentes)

# O mapa etapa→secao, lido do `switch` da tela.
corpo_secao = FRONT[FRONT.index("function secaoDaEtapa(stage: OpenPblStage): string | null {"):]
corpo_secao = corpo_secao[:corpo_secao.index("\n}")]
mapa_da_tela: dict[str, str | None] = {}
pendentes: list[str] = []
for linha in corpo_secao.splitlines():
    pendentes += re.findall(r'case "([a-z_]+)":', linha)
    achou = re.search(r'return (?:"([a-z]+)"|null);', linha)
    if achou and pendentes:
        for etapa in pendentes:
            mapa_da_tela[etapa] = achou.group(1)
        pendentes = []
conferir(len(mapa_da_tela) >= 10,
         "o mapa etapa→secao foi lido do `switch` da tela (%d entradas)" % len(mapa_da_tela))
fora_do_mapa = [e for e in cadencia.ORDEM
                if mapa_da_tela.get(e) != encontro.CATALOGO[e]["secao"]]
conferir(not fora_do_mapa,
         "e a secao de cada etapa bate com `secaoDaEtapa`",
         "divergir faz a sala FALAR uma secao e MOSTRAR outra: %s" % fora_do_mapa)

# A reparticao da plenaria entre duas etapas: a tela faz, o catalogo diz.
conferir('if (stage === "plenary") return rBlocos(r, secao).slice(0, 1);' in FRONT
         and {e for e, c in encontro.CATALOGO.items() if c["blocos"] == "primeiro"} == {"plenary"},
         "a plenaria mostra so o 1º bloco, e o catalogo diz isso",
         "o resto da secao e a dinamica das questoes, que e outra etapa")
conferir('if (stage === "question") return rIntroQuestoes(r);' in FRONT
         and {e for e, c in encontro.CATALOGO.items() if c["blocos"] == "demais"} == {"question"},
         "e as questoes mostram do 2º bloco em diante")

sem_secao = [c["secao"] for c in encontro.CATALOGO.values()
             if c["secao"] and c["secao"] not in {s["key"] for s in encontro.SECOES_BASE}]
conferir(not sem_secao,
         "toda secao apontada por uma etapa existe nos textos",
         "apontar para uma secao inexistente deixa a etapa muda: %s" % sem_secao)

conferir({e["id"] for e in encontro.catalogo_para_tela(BASE) if e["vota"]}
         == set(cadencia.ORDEM) - cadencia.AVANCA_SOZINHA - {"done"},
         "quem vota sai de `AVANCA_SOZINHA`, nao de uma lista na tela",
         "a condicao reescrita divergiria de `decidir` no primeiro ajuste")

print()
print("3) a pausa acompanha o paragrafo (o mesmo contrato de `audios[i]`)")

entrada = {
    "secoes": [{"key": "abertura", "blocos": [
        {"titulo": "T", "paragrafos": ["um", "dois", "tres"], "pausas": [500]},
    ]}],
}
bloco = encontro.normalizar(entrada)["secoes"][0]["blocos"][0]
conferir(len(bloco["pausas"]) == len(bloco["paragrafos"]) == 3,
         "lista de pausas CURTA e completada ate o fim",
         "a tela manda 1 pausa para 3 paragrafos ao acrescentar texto no fim")
conferir(bloco["pausas"] == [500, 0, 0],
         "e o que veio e preservado na posicao em que veio")

longa = encontro.normalizar({"secoes": [{"key": "abertura", "blocos": [
    {"paragrafos": ["um"], "pausas": [100, 200, 300]}]}]})["secoes"][0]["blocos"][0]
conferir(len(longa["pausas"]) == 1,
         "lista de pausas LONGA e cortada",
         "sobra de pausa e silencio que ninguem configurou, depois do fim do bloco")

vazios = encontro.normalizar({"secoes": [{"key": "abertura", "blocos": [
    {"paragrafos": ["um", "   ", "dois"], "pausas": [1, 2, 3]}]}]})["secoes"][0]["blocos"][0]
conferir(vazios["paragrafos"] == ["um", "dois"] and len(vazios["pausas"]) == 2,
         "paragrafo em branco sai, e a pausa dele sai junto",
         "tirar so o texto deslocaria o silencio para o paragrafo seguinte")

sem_nada = encontro.normalizar({"secoes": [{"key": "abertura", "blocos": [
    {"paragrafos": ["", "  "], "pausas": []}]}]})["secoes"][0]["blocos"]
conferir(sem_nada == [],
         "bloco sem paragrafo nenhum nao e gravado",
         "a sala desenharia uma caixa muda")

teto = encontro.normalizar({"secoes": [{"key": "abertura", "blocos": [
    {"paragrafos": ["um"], "pausas": [999999]}]}]})["secoes"][0]["blocos"][0]
conferir(teto["pausas"][0] == encontro.MAX_PAUSA,
         "pausa absurda e podada ao teto, nao recusada",
         "%d ms de silencio no meio de uma aula" % 999999)

print()
print("4) os temporizadores: poda, e nunca recusa")

pod = encontro.normalizar({"duracoes": {"synopsis": 1, "groups": 99999, "done": None}})
conferir(pod["duracoes"]["synopsis"] == encontro.MIN_DURACAO
         and pod["duracoes"]["groups"] == encontro.MAX_DURACAO,
         "duracao fora dos limites e podada",
         "zero faria a etapa vencer no instante em que comeca")
conferir(pod["duracoes"]["done"] is None,
         "e `None` sobrevive como `None` (etapa sem relogio)",
         "virar numero poria um cronometro na etapa final")
conferir(set(pod["duracoes"]) == set(cadencia.ORDEM),
         "a configuracao salva tem TODAS as etapas da ordem",
         "etapa nova no codigo nasce com a duracao de fabrica, nao sem duracao")

intrusa = encontro.normalizar({"duracoes": {"etapa_que_nao_existe": 60}})
conferir("etapa_que_nao_existe" not in intrusa["duracoes"],
         "etapa fora do vocabulario e DESCARTADA",
         "gravada, ninguem a leria e a tela pareceria ter configurado algo")

conferir(encontro.normalizar({"limiar": 3.0})["limiar"] <= 0.95,
         "limiar acima de 0,95 e podado",
         "com 1,0 e comparacao estrita NENHUMA sala avanca, nem com a turma toda")
conferir(encontro.normalizar({"janela_voto_s": "abacaxi"})["janela_voto_s"]
         == BASE["janela_voto_s"],
         "texto onde se esperava numero volta ao padrao",
         "e nao um 422 que deixaria quem opera sem saida")

print()
print("5) a voz")

conferir(encontro.perfil_da_voz(BASE) == "polly:Camila:generative",
         "o perfil de fabrica e a voz de hoje (Camila generativa)",
         "trocar o som de todos os encontros por omissao seria o pior default")
conferir(encontro.perfil_da_voz({"voz": {"provedor": "elevenlabs", "voz": "abc"}})
         != encontro.perfil_da_voz(BASE),
         "trocar a voz muda o PERFIL, que e o que entra na chave do mp3",
         "sem isto o audio da voz anterior seria servido para sempre")
el = encontro.normalizar({"voz": {"provedor": "elevenlabs", "voz": "abc", "motor": "generative"}})
conferir(el["voz"]["motor"] == "",
         "no ElevenLabs o motor nao viaja: o modelo e escolhido no CoreService",
         "um campo que o outro lado ignora e um campo que alguem vai tentar ajustar")
conferir(encontro.normalizar({"voz": {"provedor": "sei_la", "voz": "x"}})["voz"]["provedor"]
         == "polly",
         "provedor desconhecido volta ao padrao")
conferir(encontro.pedido_de_voz(BASE) == {"provedor": "polly", "voz": "Camila",
                                          "motor": "generative"},
         "e o pedido ao CoreService leva provedor, voz e motor",
         "sem eles o outro lado sintetiza na voz dele, nao na configurada")

print()
print("6) o texto CONGELA na criacao da sala")

RETRATO = {
    "campos": {"sinopseParte1": "a sinopse do episodio"},
    "secoes": [
        # DOIS blocos, e o template tem UM: e a unica forma de pegar o merge por
        # indice, que substitui o 1º e deixa o 2º do texto antigo no fim da
        # secao -- a sala mostrando metade de cada versao.
        {"key": "abertura", "titulo": "Abertura e registro", "blocosFixos": [
            {"titulo": "antigo", "paragrafos": ["texto velho"]},
            {"titulo": "sobra", "paragrafos": ["este bloco nao deveria sobreviver"]},
        ]},
        {"key": "secao_de_outro_produto", "titulo": "?", "blocosFixos": [
            {"paragrafos": ["intacta"]},
        ]},
    ],
}
cfg = encontro.normalizar({"secoes": [{"key": "abertura", "blocos": [
    {"titulo": "novo", "paragrafos": ["texto novo"], "pausas": [700]}]}]})
aplicado = encontro.aplicar_no_roteiro(
    {"campos": dict(RETRATO["campos"]),
     "secoes": [dict(s, blocosFixos=[dict(b) for b in s["blocosFixos"]])
                for s in RETRATO["secoes"]]}, cfg)
abertura = aplicado["secoes"][0]["blocosFixos"]
conferir(len(abertura) == 1 and abertura[0]["paragrafos"] == ["texto novo"],
         "a secao inteira e SUBSTITUIDA, nao casada bloco a bloco",
         "um merge por indice deixaria `sobra` do texto antigo no fim da secao")
conferir(abertura[0]["pausas"] == [700],
         "e a pausa configurada viaja no retrato",
         "sem ela a sala le a cadencia de fabrica, nao a configurada")
conferir(aplicado["campos"] == RETRATO["campos"],
         "o conteudo do EPISODIO nao e tocado",
         "campos sao do curador; aqui so entra o texto da plataforma")
conferir(aplicado["secoes"][1]["blocosFixos"][0]["paragrafos"] == ["intacta"],
         "secao que o template nao conhece fica como estava",
         "apagar o que nao se entende deixaria a sala sem o texto dela")

criacao = ROOMS[ROOMS.index("async def create_room"):ROOMS.index("INSERT INTO video_rooms")]
conferir("_encontro.aplicar_no_roteiro(" in criacao,
         "e a aplicacao acontece ANTES do INSERT da sala",
         "aplicar na leitura trocaria a instrucao no meio de uma aula")
conferir("_encontro.perfil_da_voz()" in ROOMS,
         "a leitura da sala assina o audio com o perfil da voz configurada",
         "sem isto a URL aponta para o objeto da voz anterior")

print()
print("7) a pausa chega ao player da sala")

conferir("pausas?: number[]" in SDK,
         "o SDK declara `pausas` ao lado de `audios`")
conferir("b.pausas?.[i]" in FRONT and "comPausa(url" in FRONT,
         "a fila da voz carrega a pausa junto da fala",
         "duas listas paralelas desalinhariam em um dos tres caminhos que a montam")
conferir("window.clearTimeout(espera)" in FRONT,
         "e o temporizador da pausa morre na limpeza do efeito",
         "sem isto, trocar de etapa durante um silencio traz a fala antiga de volta")
conferir("const ms = honrarPausa ? pausaDoItem(lista[i]) : 0;" in FRONT,
         "404 e recusa de autoplay NAO esperam a pausa",
         "silencio no lugar de uma frase que nao foi dita e o dobro do problema")

print()
print("7b) o ensaio da etapa, na tela de configuracao")
print()

#: O ENSAIO TEM DE TOCAR O QUE A AULA VAI TOCAR.
#:
#: Uma segunda forma de sintetizar aqui (outra voz, outra chave, outro
#: bucket) faria o ensaio soar diferente do encontro -- e aí o recurso é pior
#: que não existir, porque dá confiança no lugar errado.
ensaio = ROTA[ROTA.index("async def ensaio("):ROTA.index("@router.post(\"/aquecer\")")]
conferir("encontro.perfil_da_voz(config)" in ensaio
         and "voz.chave(voz.normalizar(f.texto), perfil)" in ensaio,
         "o ensaio assina a MESMA chave que a sala tocaria",
         "chave propria faria o ensaio soar diferente da aula")
conferir("voz_porta.garantir_textos" in ensaio,
         "e sintetiza pelo mesmo caminho, sem implementacao propria",
         "e por isso ensaiar ADIANTA o aquecimento em vez de duplicar custo")
conferir("if not voz_porta.configurado():" in ensaio,
         "sem voz configurada ele devolve as falas sem URL, e nao 503",
         "ler a etapa na ordem ainda serve quando nao ha audio")

#: A MESMA REGRA DE PAUSA DA SALA: silencio so depois de uma fala que TOCOU.
conferir("const seguir = (honrarPausa: boolean) => {" in TELA
         and "const ms = honrarPausa ? fala.pausa_ms : 0;" in TELA,
         "o ensaio so espera a pausa depois de uma fala que tocou",
         "mesma regra da sala: silencio por uma frase nao dita e o dobro do erro")
conferir("useEffect(() => { parar(); setFalas([]); setErro(\"\"); }, [etapa.id]);" in TELA,
         "e trocar de etapa PARA o ensaio em andamento",
         "senao a fala da etapa anterior toca por cima da que se configura agora")

#: O INDICE DO BLOCO E O DA SECAO, NAO O DA FATIA.
#:
#: A plenaria mostra `[0]` e as questoes mostram `[1..]`. Editando pelo indice
#: da fatia, mexer no 1o bloco visivel da etapa "Questoes" gravaria no bloco da
#: plenaria -- o texto mudaria na etapa errada, sem erro nenhum.
conferir("function blocosDaEtapa(cfg: Config, etapa: Etapa)" in TELA
         and "secao.blocos.map((bloco, i) => ({ bloco, i }))" in TELA,
         "a tela carrega o indice do bloco DENTRO da secao",
         "editar pelo indice da fatia escreveria no bloco de outra etapa")
conferir("const irmas = etapas.filter(" in TELA,
         "e diz quais OUTRAS etapas mostram o mesmo texto",
         "tres etapas dividem a abertura: editar uma muda as tres")

#: O PREVIEW E A TELA DA SALA, NAO UMA IMITACAO DELA.
#:
#: Enquanto o painel desenhava a sua propria versao, qualquer ajuste de CSS ou
#: de regra na sala fazia o preview prometer uma tela que o encontro nao
#: mostra -- e ninguem notaria, porque as duas continuariam "funcionando".
#: Com o componente compartilhado o problema deixa de existir: divergir
#: exigiria que a SALA mudasse, e ai os dois mudam juntos.
conferir('from "../components/video/RoteiroStage"' in TELA
         and "<RoteiroStage" in TELA,
         "o preview renderiza o componente DA SALA",
         "uma copia no painel divergiria no primeiro ajuste de CSS")
conferir('from "./RoteiroStage"' in VIDEOROOM,
         "e a sala importa o MESMO modulo",
         "se a sala tivesse a copia dela, o compartilhamento seria aparencia")
#: E os ROTULOS das cascatas sao os mesmos dos dois lados.
#:
#: Ha etapas cujo conteudo principal nao esta no `RoteiroStage`, e sim numa
#: cascata ao lado dele -- o preview espelha essa composicao. Um rotulo que
#: exista so no painel anuncia uma tela diferente da que a aula mostra.
rotulos = ["Questões para reflexão"]
faltando = [r for r in rotulos if r not in TELA or r not in VIDEOROOM]
conferir(not faltando,
         "e os rotulos das cascatas batem com os da sala",
         "rotulo so no painel anuncia uma tela diferente da aula: %s" % faltando)

print()
print("8) quem pode configurar")

#: TODA rota, e nao "pelo menos N rotas".
#:
#: A primeira versao disto contava `>= 5` ocorrencias de require_admin. A
#: rota do ensaio virou a sexta, e aí tirar a guarda de UMA deixava cinco --
#: a prova seguia verde com a previa de voz aberta a quem tivesse a URL. Uma
#: contagem protege ate o dia em que o numero cresce; a RELACAO protege sempre.
rotas = re.findall(
    r'@router\.\w+\("([^"]*)"\)\s+(?:async\s+)?def\s+\w+\((.*?)\)', ROTA, re.S)
conferir(len(rotas) >= 6,
         "as %d rotas do painel foram lidas do arquivo" % len(rotas),
         "regex que nao casa deixaria a afirmacao abaixo vazia, e verde")
sem_guarda = [caminho for caminho, args in rotas if "require_admin" not in args]
conferir(not sem_guarda,
         "TODA rota do painel exige sessao de admin",
         "sem guarda: %s" % sem_guarda if sem_guarda
         else "sintetizar voz de graca para quem passar pela URL")
conferir('prefix="/api/admin/encontro"' in ROTA,
         "e vivem sob /api/admin, onde o cookie de sessao e valido",
         "fora desse path o navegador nao manda o cookie e a tela da 401")
conferir("etapas={dados.etapas}" in TELA and "const STEPS" not in TELA,
         "a tela NAO tem a sua propria lista de etapas",
         "seria a quinta copia da ordem do encontro")

print()
print("falhas: %d" % falhas)
raise SystemExit(1 if falhas else 0)

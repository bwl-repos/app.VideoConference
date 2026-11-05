# Transcritor das salas (identificação + transcrição)

Processo que entra nas salas da videoconferência, ouve cada participante e
devolve ao backend **quem falou o quê**. É o item "Identificação +
transcrição" do documento de premissas da facilitação autônoma.

```
  salas em aula          LiveKit (SFU)            esta máquina            backend
  ───────────────        ─────────────            ─────────────           ───────
  quem está falando ───► faixa de áudio  ───────► corta em falas ───► POST /api/internal/transcricao
                         (uma por pessoa)         reconhece (ASR)      → video_room_transcricao
                                                                       → painel "Transcrição" do host
```

## Por que não um gravador de reunião de prateleira

O Fireflies — e os concorrentes dele — entra em **Zoom, Meet, Teams e Webex**.
A sala da OpenPBL é **LiveKit próprio**: não há bot que saiba entrar. As
alternativas (extensão de Chrome, app de desktop capturando o som do sistema)
exigem **uma pessoa** rodando captura na sala, que é exatamente a figura que a
facilitação autônoma remove.

E há um ganho que nenhum deles daria: no LiveKit **cada faixa de áudio pertence
a um participante**. "Quem falou" sai da faixa, exato por construção — inclusive
quando duas pessoas falam juntas, que é o normal numa plenária e justamente
onde a diarização por voz erra.

## Como ele acha as salas

Ele **pergunta** ao backend a cada 15 s (`GET /api/internal/transcricao/salas`),
e o backend devolve só as salas com aula em andamento **e** gente conectada,
cada uma com um token já pronto — `hidden`, sem permissão de publicar nada.

Não é webhook de propósito: evento perdido não volta, e o agente reiniciado no
meio de um encontro ficaria fora dele até o próximo. Perguntando, o pior caso é
entrar alguns segundos depois, e o processo pode morrer e voltar sem ninguém
intervir.

## Os dois motores

| `ASR_ENGINE` | o que usa | custo | quando |
|---|---|---|---|
| `whisper` (padrão) | `faster-whisper` nesta máquina | a máquina (GPU) | volume alto; áudio não sai da infra |
| `deepgram` | API da Deepgram | por minuto | sem GPU para manter; volume baixo |

A escolha é de **negócio**, não de arquitetura: a interface é a mesma e trocar
é uma variável de ambiente. Com `whisper` em CPU funciona, mas devagar — o
dimensionamento sério está medido em `modelo transcricao/LEIA-ME.md` (workspace
OPENPBL): `large-v3-turbo` em `int8_float16` com `beam 1` processa 10 s de áudio
em ~1 s numa RTX 3060 Ti, e o mesmo par de wheels CUDA funciona em Linux.

## Rodar

```bash
export TRANSCRITOR_API=https://video.pbltools.io
export NODE_SECRET=...            # o MESMO do backend.env do servidor da aula
export ASR_ENGINE=whisper         # ou deepgram (+ DEEPGRAM_API_KEY)

python -B transcritor.py --uma-rodada   # só pergunta as salas e sai (teste de credencial)
python -B transcritor.py                # roda
```

Em Docker:

```bash
docker build -t bwl-transcritor .                      # CPU / Deepgram
docker build --build-arg COM_GPU=1 -t bwl-transcritor . # GPU (precisa de --gpus all)
```

### Variáveis

| variável | padrão | o que faz |
|---|---|---|
| `TRANSCRITOR_API` | `https://video.pbltools.io` | onde fica o backend da videoconferência |
| `NODE_SECRET` | — | **obrigatória**; sem ela o backend responde 401 a tudo |
| `ASR_ENGINE` | `whisper` | `whisper` ou `deepgram`; nome desconhecido **erra no boot** |
| `ASR_MODELO` | `large-v3-turbo` / `nova-3` | modelo do motor escolhido |
| `ASR_DISPOSITIVO` | `cuda` | `cuda` ou `cpu` (só whisper) |
| `ASR_COMPUTE` | `int8_float16` | em CPU use `int8` (só whisper) |
| `ASR_IDIOMA` | `pt` / `pt-BR` | sempre explícito: a autodetecção confunde pt com es |
| `DEEPGRAM_API_KEY` | — | obrigatória com `ASR_ENGINE=deepgram` |
| `TRANSCRITOR_INTERVALO` | `15` | segundos entre duas perguntas pela lista de salas |
| `TRANSCRITOR_FILA` | `64` | falas à espera do reconhecedor; estourar **é registrado** |
| `TRANSCRITOR_TRABALHADORES` | `1` | reconhecimentos em paralelo (a GPU já serializa) |
| `TRANSCRITOR_LIMIAR_DE_VOZ` | `0.012` | energia (RMS 0..1) acima da qual há voz; ajustar exige medir com uma sala de verdade |

## Provas

```bash
python -B provas/prova_segmentacao.py       # a regra: onde a fala começa e termina
python -B provas/falsifica_segmentacao.py   # e os 13 defeitos que ela pega
```

Rodam **sem áudio, sem GPU e sem rede**: é o que a separação de
`segmentacao.py` compra. Do outro lado, `backend/provas/prova_transcricao.py`
confere o contrato entre este agente e o servidor — inclusive que as duas
cópias da lista de "quem é gente na sala" não divergiram.

## O que ele NÃO faz

- **Não publica nada** na sala (o token não dá essa permissão) e **não
  aparece** para ninguém (`hidden`).
- **Não transcreve o gravador** (`EG_…`): ele republica o áudio de todos, e
  transcrevê-lo duplicaria a aula inteira, com o nome errado.
- **Não decide nada da aula.** A etapa de cada fala é estampada pelo servidor;
  o agente não acompanha a cadência.
- **Não mostra legenda ao vivo para o aluno.** A transcrição aparece no painel
  de quem dirige: é fala de gente passada por um reconhecedor que erra, e o
  erro dele na tela do colega abre uma discussão que não é a da aula.

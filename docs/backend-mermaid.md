# Backend da VideoConference BWL - diagramas

Cole cada bloco no app **Diagram as code / Mermaid** do Miro.
Gerado de `videoconf-backend.html` por `extrair_mermaid.py`.

## esquema 01 · componentes e fronteiras

```mermaid
flowchart LR
  subgraph NAV["Navegador do participante"]
    SALA["Sala - React<br/>CustomerApp / embed"]
  end

  subgraph LS["Lightsail sa-east-1"]
    APP["bwl-app<br/>FastAPI + asyncpg"]
    LK["bwl-livekit<br/>SFU"]
    EGR["bwl-egress<br/>navegador headless"]
  end

  PG[("Postgres<br/>16 tabelas")]
  S3[("S3<br/>bucket recordings")]

  subgraph OP["Serviços OpenPBL"]
    INT["integration.openpbl.ai<br/>ContentBuilder C#"]
    CHT["chat.openpbl.ai<br/>painel do professor"]
    RSE["elearnapp.openpbl.ai<br/>Rise"]
    LRS["ltiserver.openpbl.ai<br/>LRS de interações"]
  end

  SALA -->|"REST /api/* - estado, comandos"| APP
  SALA -->|"WS /ws/rooms/:id - eventos da sala"| APP
  SALA <-->|"WebRTC: áudio, vídeo, tela"| LK
  APP -->|"token JWT com os grants"| SALA

  APP -->|"SELECT / UPDATE"| PG
  APP -->|"REST: list_participants, update_participant, remove"| LK
  APP -->|"RoomCompositeEgressRequest"| EGR
  EGR -->|"entra na sala como cliente"| LK
  EGR -->|"mp4 roomDbId/room-time.mp4"| S3
  LK -.->|"webhook egress_updated / egress_ended"| APP

  APP -->|"class-code, turma, liberações, fechar registro"| INT
  APP -->|"HTTP Basic: conversas e respostas"| CHT
  APP -->|"Bearer: nota de participação"| RSE
  APP -->|"GET /interaction-events: quem respondeu"| LRS
```

## esquema 02 · POST /api/token

```mermaid
flowchart TD
  REQ["POST /api/token<br/>room_id + credencial"] --> SALA{"sala existe e<br/>status diferente de ended?"}
  SALA -->|"não"| E404["404 room not available"]
  SALA -->|"sim"| QUAL{"que credencial<br/>veio no corpo?"}

  QUAL -->|"guest_token"| G{"bate com<br/>video_rooms.guest_token?"}
  G -->|"não"| E1["403 invalid guest token"]
  G -->|"sim"| GID["identity estável:<br/>guest_ + sha256 do e-mail, 12 hex<br/>sem e-mail: 4 bytes aleatórios"]

  QUAL -->|"speaker_invite_id"| S{"convite vivo<br/>e desta sala?"}
  S -->|"não"| E2["403 invalid invite"]
  S -->|"sim"| SID["identity = speaker_ + id do convite"]

  QUAL -->|"nada: headers X-User-*"| U{"usuário resolvido?"}
  U -->|"não"| E3["401 auth headers required"]
  U -->|"sim"| T{"tenant do pedido é o<br/>dono da sala?"}
  T -->|"não"| E4["403 room does not belong<br/>to this tenant"]
  T -->|"sim"| UID["identity = user.id<br/>is_admin se role é admin ou staff"]

  GID --> MINT
  SID --> MINT
  UID --> MINT["create_token<br/>room = video_rooms.room_id, o NOME no LiveKit<br/>can_publish_sources conforme allow_screen_share<br/>room_admin e room_record só para o host<br/>TTL 6 h"]

  MINT --> REG["_register<br/>UPSERT video_room_participants: joined_at=now, left_at=NULL<br/>INSERT ... DO NOTHING em participant_permissions"]
  REG --> OK["200 token + livekit_url + identity"]
```

## esquema 03 · tubulação da cadência

```mermaid
flowchart TD
  P["cada participante na sala:<br/>GET /api/rooms/:id/openpbl a cada 10 s"] --> AP
  H["host: botão de etapa, voto, modo"] --> AP["_aplicar_cadencia - router<br/>só tubulação: ler, perguntar, gravar"]

  AP --> MIG{"a coluna auto_mode<br/>existe no banco?"}
  MIG -->|"não - schema atrás do código"| N0["devolve a linha intacta<br/>funcionalidade nova nasce inerte"]
  MIG -->|"sim"| AUTO{"auto_mode?"}
  AUTO -->|"manual"| N1["nada - o host comanda<br/>nem lê presença nem grava"]
  AUTO -->|"automático"| VOC{"stage está no<br/>vocabulário DURACAO_DA_ETAPA?"}
  VOC -->|"não"| W["log WARNING + pílula na tela do host<br/>a sala NÃO avança e NÃO é rebobinada"]
  VOC -->|"sim"| CLK{"stage_started_at<br/>é NULL?"}
  CLK -->|"sim"| MK["UPDATE stage_started_at = agora<br/>resgate: 97 salas automáticas sem relógio"]
  CLK -->|"não"| PRE
  MK --> PRE{"precisa_de_presenca?<br/>só se a janela do voto já fechou"}
  PRE -->|"não"| DEC
  PRE -->|"sim"| LKP["LiveKit list_participants<br/>pelo NOME da sala, menos quem é staff<br/>o host não vota o próprio ritmo"]
  LKP --> DEC["cadencia.decidir<br/>pura: sem banco, sem rede, sem now"]

  DEC -->|"nada"| FIM["devolve a linha"]
  DEC -->|"abrir_voto"| V["UPDATE vote_ends_at = agora + 15 s<br/>vote_stage = stage, votes = vazio"]
  DEC -->|"estender"| X["UPDATE stage_started_at recuado<br/>a etapa ganha só 120 s, não outro período"]
  DEC -->|"avancar"| EF{"a etapa que termina<br/>é registration_close?"}

  EF -->|"sim"| CLOSE["EFEITO ANTES DA ETAPA:<br/>fecha o registro no OpenPBL e divide os grupos"]
  EF -->|"não"| UPD
  CLOSE --> UPD["UPDATE stage, stage_started_at = agora<br/>limpa voto e votos"]

  V --> BC
  UPD --> BC["hub.broadcast openpbl-class<br/>+ INSERT video_room_comunicacoes - inerte sem a tabela"]
  X --> LOGA["log da decisão: ação, porque, sim/total"]
  BC --> LOGA
```

## esquema 04 · cadencia.decidir

```mermaid
flowchart TD
  I["decidir - estado, agora, presentes"] --> Q1{"auto?"}
  Q1 -->|"não"| R1["nada<br/>modo manual tem precedência sobre TUDO,<br/>inclusive sobre um voto aberto"]
  Q1 -->|"sim"| Q2{"stage está em ORDEM<br/>e não é done?"}
  Q2 -->|"não"| R2["nada - etapa terminal ou desconhecida"]
  Q2 -->|"sim"| Q3{"há voto aberto?<br/>vote_ends_at não nulo"}

  Q3 -->|"sim"| Q4{"vote_stage == stage?"}
  Q4 -->|"não"| R3["estender<br/>o host trocou a etapa durante o voto:<br/>era outra pergunta, não vale"]
  Q4 -->|"sim"| Q5{"agora < vote_ends_at?"}
  Q5 -->|"sim"| R4["nada - voto em andamento"]
  Q5 -->|"não"| AP["apurar<br/>só os PRESENTES entram na conta<br/>quem não votou conta como NÃO"]
  AP --> Q6{"sim x 2 > total?<br/>maioria ESTRITA"}
  Q6 -->|"sim"| R5["avancar para a próxima da ORDEM"]
  Q6 -->|"não - empate inclusive"| R6["estender - a pergunta volta depois<br/>sem limite de rodadas"]

  Q3 -->|"não"| Q7{"a etapa tem duração?"}
  Q7 -->|"None"| R7["nada - etapa sem relógio, depende do host"]
  Q7 -->|"sim"| Q8{"stage_started_at existe?"}
  Q8 -->|"não"| R8["nada<br/>sem hora de início não se inventa uma"]
  Q8 -->|"sim"| Q9{"já passou a duração?"}
  Q9 -->|"não"| R9["nada - ainda no tempo"]
  Q9 -->|"sim"| Q10{"stage está em AVANCA_SOZINHA?<br/>as 4 etapas da abertura"}
  Q10 -->|"sim"| R10["avancar SEM votar<br/>numa sala que está enchendo não há a quem perguntar"]
  Q10 -->|"não"| R11["abrir_voto - janela de 15 s"]
```

## esquema 05 · a espinha do encontro

```mermaid
flowchart LR
  subgraph AB["abertura - avança sozinha, sem voto"]
    direction LR
    A1["session_start<br/>10 min"] --> A2["registration_open<br/>5 min"] --> A3["amplify_code<br/>30 s"] --> A4["registration_close<br/>30 s"]
  end

  subgraph CO["o encontro - cada passagem é votada pela turma"]
    direction LR
    B1["synopsis<br/>5 min"] --> B2["groups<br/>15 min"] --> B3["plenary<br/>5 min"] --> B4["question<br/>7 min"] --> B5["situational<br/>10 min"]
    B5 --> B6["release_risks<br/>10 min"] --> B7["show_chart<br/>5 min"] --> B8["closing<br/>3 min"] --> B9["release_feedback<br/>10 min"]
  end

  A4 -->|"fecha o registro e divide os grupos"| B1
  B9 --> D["done<br/>sem relógio"]
```

## esquema 06 · abrir a aula, fechar o registro, abrir os grupos

```mermaid
flowchart TD
  ST["host: POST /openpbl/start<br/>activity_id + e-mail do facilitador"] --> SC["e-mail derivado da sala<br/>_room_scoped_email: chave única por sala"]
  SC --> P1["POST integration /api/Presentation<br/>ActivityId + email"]
  P1 -->|"erro"| ERR["502 com o CORPO da resposta no log<br/>status sozinho não distingue<br/>atividade inexistente de chave inválida"]
  P1 -->|"200"| CODE["presentationCode - o class-code da turma"]
  CODE --> P2["POST integration /api/ClassCourse<br/>name, email, courseId vazio, presentationCode"]
  P2 --> CC["ClassCourseId + 6 grupos com código"]
  CC --> DB["UPSERT video_room_openpbl_class<br/>checking_open = true"]
  DB --> BR1["hub.broadcast openpbl-class"]

  FE["cadência vence registration_close<br/>ou host: POST /openpbl/close-registration"] --> CL["POST integration<br/>/api/Presentation/CloseChecking<br/>Code + ActivityCourseId"]
  CL --> SY["_sync_openpbl_groups<br/>lê a composição dos grupos na turma"]
  SY --> SO["_sortear_lideres<br/>um líder sorteado por grupo"]
  SO --> AB["_auto_group_breakouts<br/>um video_breakout_groups por grupo OpenPBL"]
  AB --> LKN["cada grupo é uma sala LiveKit PRÓPRIA: sala__boN"]
  LKN --> TK["aluno: POST /breakouts/token<br/>só do grupo a que foi atribuído<br/>host visita qualquer um"]
  TK --> MV["o cliente troca de sala no SFU<br/>mover alguém = trocar o token dele"]
  AB --> CTRL["o controle segue na sala-PAI:<br/>WS breakout-open / close / message / timer"]
```

## esquema 07 · egress e o webhook

```mermaid
flowchart TD
  H["host: POST /api/rooms/:id/recording/start"] --> ST{"is_staff?"}
  ST -->|"não"| X1["403"]
  ST -->|"sim"| TN{"a sala é desta licença<br/>e recording_enabled nela?"}
  TN -->|"não"| X2["403 gravação não habilitada"]
  TN -->|"sim"| REQ["RoomCompositeEgressRequest<br/>layout grid<br/>custom_base_url = /recording-view?roomDbId&wb<br/>saída mp4 em roomDbId/room-time.mp4"]
  REQ --> UP["UPDATE video_rooms<br/>egress_id, recording_progress = starting"]
  UP --> BR["hub.broadcast recording-started"]
  REQ --> EG["bwl-egress abre a página headless,<br/>entra na sala e compõe"]
  EG --> S3[("S3 - bucket recordings")]

  WH["LiveKit: POST /api/webhooks/livekit"] --> EV{"evento"}
  EV -->|"egress_updated"| U1["recording_progress = status"]
  EV -->|"egress_ended + EGRESS_COMPLETE com arquivo"| U2["recording_url = chave no S3<br/>progress = completed"]
  EV -->|"egress_ended + ABORTED ou FAILED"| U3["sem chave - sala vazia não gera upload<br/>progress = aborted / failed"]
  U2 --> PL["GET /recording devolve URL assinada<br/>a chave é guardada, não a URL:<br/>presigned expira, a gravação não"]
```

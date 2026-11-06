-- Video Rooms Kit — PostgreSQL schema
-- All user_id columns are TEXT so guest/speaker pseudo-identities fit alongside UUIDs.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS video_rooms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id TEXT UNIQUE NOT NULL,                -- LiveKit room name
  title TEXT NOT NULL,
  description TEXT,
  owner_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',       -- active | ended
  max_participants INT NOT NULL DEFAULT 50,
  is_public BOOLEAN NOT NULL DEFAULT true,
  auto_record BOOLEAN NOT NULL DEFAULT false,
  lobby_enabled BOOLEAN NOT NULL DEFAULT false,
  lobby_timer_title TEXT,
  lobby_timer_seconds INT NOT NULL DEFAULT 300,
  lobby_bg_video TEXT,
  lobby_auto_admit BOOLEAN NOT NULL DEFAULT false,
  guest_token TEXT UNIQUE,                     -- public join link
  allow_camera BOOLEAN NOT NULL DEFAULT true,
  allow_mic BOOLEAN NOT NULL DEFAULT true,
  allow_screen_share BOOLEAN NOT NULL DEFAULT true,
  allow_whiteboard_edit BOOLEAN NOT NULL DEFAULT false,
  whiteboard_active BOOLEAN NOT NULL DEFAULT false,
  recording_enabled BOOLEAN NOT NULL DEFAULT false,
  egress_id TEXT,
  recording_url TEXT,
  recording_progress TEXT,
  external_ref TEXT,                           -- e.g. booking_id from host
  require_email BOOLEAN NOT NULL DEFAULT false, -- ask guests for e-mail (SCORM/OpenPBL)
  openpbl_activity_id TEXT,                      -- aula OpenPBL: auto-gera class-code
  openpbl_dimensions_id TEXT,                    -- aula OpenPBL: dimensionsId p/ o gráfico de riscos
  -- (a coluna `stage` do sequenciamento fica em video_room_openpbl_class)
  breakout_open BOOLEAN NOT NULL DEFAULT false,  -- grupos (breakout) abertos?
  breakout_ends_at TIMESTAMPTZ,                  -- retorno automático dos grupos
  breakout_mode TEXT NOT NULL DEFAULT 'auto',    -- auto | manual | self
  scheduled_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS video_rooms_owner_idx ON video_rooms(owner_id);
CREATE INDEX IF NOT EXISTS video_rooms_external_idx ON video_rooms(external_ref);

CREATE TABLE IF NOT EXISTS video_room_participants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  display_name TEXT,
  email TEXT,
  is_staff BOOLEAN NOT NULL DEFAULT false,
  joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  left_at TIMESTAMPTZ,
  UNIQUE (room_id, user_id)
);

CREATE TABLE IF NOT EXISTS video_room_participant_permissions (
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  allow_camera BOOLEAN NOT NULL DEFAULT true,
  allow_mic BOOLEAN NOT NULL DEFAULT true,
  allow_screen_share BOOLEAN NOT NULL DEFAULT true,
  allow_whiteboard_edit BOOLEAN NOT NULL DEFAULT false,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (room_id, user_id)
);

CREATE TABLE IF NOT EXISTS video_room_lobby (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  participant_type TEXT NOT NULL DEFAULT 'user',  -- user | guest | speaker
  status TEXT NOT NULL DEFAULT 'waiting',          -- waiting | admitted | denied
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS video_room_lobby_room_idx ON video_room_lobby(room_id);

CREATE TABLE IF NOT EXISTS video_room_chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  sender_id TEXT NOT NULL,
  sender_name TEXT NOT NULL,
  message TEXT NOT NULL,
  channel TEXT,                                  -- NULL = sala principal; groupId = chat do grupo
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS video_room_chat_room_idx ON video_room_chat_messages(room_id, created_at);
CREATE INDEX IF NOT EXISTS video_room_chat_channel_idx ON video_room_chat_messages(room_id, channel, created_at);

CREATE TABLE IF NOT EXISTS speaker_invite_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  label TEXT,
  allow_camera BOOLEAN NOT NULL DEFAULT true,
  allow_mic BOOLEAN NOT NULL DEFAULT true,
  allow_screen_share BOOLEAN NOT NULL DEFAULT true,
  allow_whiteboard_edit BOOLEAN NOT NULL DEFAULT false,
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS whiteboards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  state JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (room_id)
);

-- ── Multi-tenant / licensing (see migrations/002_tenancy.sql) ──
CREATE TABLE IF NOT EXISTS plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
  max_rooms INT NOT NULL DEFAULT -1, max_participants INT NOT NULL DEFAULT 50,
  recording_enabled BOOLEAN NOT NULL DEFAULT true, storage_quota_gb INT NOT NULL DEFAULT 50,
  price_cents INT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'active',
  plan_id UUID REFERENCES plans(id),
  max_rooms INT, max_participants INT, recording_enabled BOOLEAN, storage_quota_gb INT,
  branding JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tenant_api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT, key_prefix TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
  last_used_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tenant_api_keys_tenant_idx ON tenant_api_keys(tenant_id);
CREATE TABLE IF NOT EXISTS admin_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, name TEXT,
  role TEXT NOT NULL DEFAULT 'admin', status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_login_at TIMESTAMPTZ
);
ALTER TABLE video_rooms ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
CREATE INDEX IF NOT EXISTS video_rooms_tenant_idx ON video_rooms(tenant_id);
CREATE TABLE IF NOT EXISTS client_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, name TEXT,
  role TEXT NOT NULL DEFAULT 'owner', status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_login_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS client_users_tenant_idx ON client_users(tenant_id);

-- Breakout rooms ("grupos"): sub-salas LiveKit por sala-pai.
CREATE TABLE IF NOT EXISTS video_breakout_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  room_name TEXT NOT NULL,
  position INT NOT NULL DEFAULT 0,
  -- Líder sorteado UMA vez e gravado (ver migrations/019 e services/sorteio.py).
  -- Identidade, não nome: nome muda e dois alunos podem se chamar igual.
  leader_identity TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_breakout_groups_room ON video_breakout_groups(parent_room_id);

CREATE TABLE IF NOT EXISTS video_breakout_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  group_id UUID NOT NULL REFERENCES video_breakout_groups(id) ON DELETE CASCADE,
  identity TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (parent_room_id, identity)
);
CREATE INDEX IF NOT EXISTS idx_breakout_assign_group ON video_breakout_assignments(group_id);

-- Aula OpenPBL ao vivo (class-code gerado pela webconf; ver migrations/008).
CREATE TABLE IF NOT EXISTS video_room_openpbl_class (
  room_id UUID PRIMARY KEY REFERENCES video_rooms(id) ON DELETE CASCADE,
  activity_id TEXT NOT NULL,
  presentation_code TEXT NOT NULL,
  class_course_id TEXT NOT NULL,
  group_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
  facilitator_email TEXT NOT NULL,
  facilitator_name TEXT NOT NULL DEFAULT '',
  checking_open BOOLEAN NOT NULL DEFAULT true,
  released_dimensions BOOLEAN NOT NULL DEFAULT false,
  released BOOLEAN NOT NULL DEFAULT false,
  code_hidden BOOLEAN NOT NULL DEFAULT false,   -- facilitador ocultou o class-code (migration 010)
  stage TEXT NOT NULL DEFAULT 'session_start',   -- sequenciador do ▶ (migrations 012/013)
  -- Cadência: a sala avança sozinha com o aval da turma (migration 018).
  -- `auto_mode` nasce TRUE: a automação é o padrão; assumir o controle é a
  -- exceção. Ligado não é correndo — sem `stage_started_at` a regra não abre
  -- voto nenhum.
  auto_mode BOOLEAN NOT NULL DEFAULT true,
  stage_started_at TIMESTAMPTZ,
  vote_ends_at TIMESTAMPTZ,
  vote_stage TEXT,
  votes JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Histórico das comunicações do facilitador.
--
-- O log já registrava a mesma decisão (`[cadencia] ...`), mas log não é
-- histórico: ninguém numa aula abre o CloudWatch, o aluno que chegou atrasado
-- não tem como saber o que já foi dito, e quem supervisiona precisa ver a
-- automação agindo enquanto ela age.
--
-- Guarda o EVENTO, não a frase: os rótulos das etapas vivem no frontend, e
-- montar a sentença aqui exigiria uma segunda lista de nomes que envelheceria
-- calada. `meta` leva as chaves das etapas e a contagem dos votos; a tela compõe
-- a frase. Ver `backend/app/services/comunicacoes.py`.
CREATE TABLE IF NOT EXISTS video_room_comunicacoes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  at TIMESTAMPTZ NOT NULL DEFAULT now(),
  tipo TEXT NOT NULL,
  -- Só para o que é texto de verdade (recado do host). Nos eventos da cadência
  -- fica vazio: a frase não é dado, é apresentação.
  texto TEXT NOT NULL DEFAULT '',
  meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- A consulta é sempre "as desta sala, em ordem", e ela roda no polling de todo
-- mundo que está na aula.
CREATE INDEX IF NOT EXISTS idx_comunicacoes_room_at
  ON video_room_comunicacoes(room_id, at);

-- Transcrição do encontro, com IDENTIFICAÇÃO de quem falou.
--
-- É o item "Identificação + transcrição" do documento de premissas, e o motivo
-- de ele não ser um produto de prateleira: o Fireflies entra em Zoom, Meet,
-- Teams e Webex — não numa sala LiveKit própria. As alternativas dele (extensão
-- de Chrome, app de desktop) exigem uma PESSOA rodando captura na sala, que é
-- exatamente a figura que a facilitação autônoma remove.
--
-- No LiveKit cada faixa de áudio pertence a um participante. Então `identity`
-- aqui não é um palpite de diarização por voz — é o dono da faixa, exato por
-- construção, inclusive quando duas pessoas falam juntas (que é o normal numa
-- plenária e justamente onde a diarização erra).
--
-- `nome` é um RETRATO: o nome exibido no momento da fala. Quem lê a transcrição
-- de um encontro de três meses atrás quer o nome de então, e o participante
-- pode nem existir mais em tabela nenhuma.
CREATE TABLE IF NOT EXISTS video_room_transcricao (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  -- Identidade no LiveKit = quem falou. Ver `services/presenca.py`.
  identity TEXT NOT NULL,
  nome TEXT NOT NULL DEFAULT '',
  inicio TIMESTAMPTZ NOT NULL,
  fim TIMESTAMPTZ NOT NULL,
  texto TEXT NOT NULL,
  -- A etapa em que a frase foi dita. Sem ela, ler a transcrição depois obriga a
  -- cruzar horários com o histórico das comunicações para saber do que se
  -- falava.
  stage TEXT NOT NULL DEFAULT '',
  -- Qual motor de ASR produziu o texto (`whisper`, `deepgram`...). Trocar de
  -- motor sem este campo torna impossível comparar qualidade depois: a
  -- transcrição boa e a ruim ficariam indistinguíveis na mesma tabela.
  motor TEXT NOT NULL DEFAULT ''
);

-- A leitura é sempre "as desta sala, em ordem".
CREATE INDEX IF NOT EXISTS idx_transcricao_room_inicio
  ON video_room_transcricao(room_id, inicio);

-- IDEMPOTÊNCIA DO AGENTE.
--
-- O transcritor roda fora deste servidor e devolve cada fala por HTTP. Ele
-- repete o envio quando a resposta não chega — e uma resposta que não chega é
-- indistinguível de uma gravação que não aconteceu. Sem esta chave, cada
-- reenvio duplicaria a frase na tela, e o sintoma seria uma transcrição que
-- gagueja em rede ruim.
--
-- (`identity`, `inicio`) é único por sala porque uma pessoa não começa duas
-- falas no mesmo instante: `inicio` vem do relógio do áudio, não do envio.
CREATE UNIQUE INDEX IF NOT EXISTS idx_transcricao_unica
  ON video_room_transcricao(room_id, identity, inicio);


-- O template do encontro: duração de cada etapa, texto que a sala fala e a voz
-- que lê. Até aqui as três coisas eram constante de código em três
-- repositórios diferentes e só mudavam com deploy.
--
-- UMA LINHA, de propósito (`id = 1`, com CHECK). A decisão de produto é
-- "global, e a sala congela o texto na criação": um template para a
-- plataforma, e não um por licença. O CHECK é o que impede a segunda linha
-- aparecer por acidente e passar a ser lida ou não dependendo da ordem do
-- SELECT -- defeito que não dá erro, só muda o encontro de vez em quando.
--
-- `dados` é JSONB e não vinte colunas porque a forma acompanha a do roteiro
-- (seções, blocos, parágrafos, pausas), que já é JSONB na `video_rooms`.
-- Quebrá-la em colunas exigiria uma migration por parágrafo acrescentado.
--
-- Vazia significa "o padrão do código", e é por isso que esta migration não
-- tem INSERT: `services/encontro.py` devolve a base (as constantes de
-- `cadencia.py` e os textos do `schema.ts`) enquanto ninguém salvar nada. A
-- tabela também é criada na subida do serviço (`garantir_tabela`), porque
-- publicar não aplica migration neste repositório -- este arquivo é o registro
-- e o caminho do `schema.sql` em banco novo.
CREATE TABLE IF NOT EXISTS encontro_template (
  id         INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  dados      JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Quem salvou (e-mail do admin). Guardado porque mudar o ritmo do encontro é
  -- uma decisão de produto que alguém toma, e a próxima pessoa a abrir a tela
  -- precisa poder perguntar a ela.
  updated_by TEXT
);

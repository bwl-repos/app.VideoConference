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

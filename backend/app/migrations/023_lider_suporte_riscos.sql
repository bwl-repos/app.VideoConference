-- Líder geral, sala de suporte, pergunta da plenária no servidor e prazo dos riscos.
--
-- `questao_atual` vive no banco porque antes vivia só no navegador de quem conduzia: no
-- modo automático não há esse navegador, e o aluno não via pergunta nenhuma.

ALTER TABLE video_room_openpbl_class
  ADD COLUMN IF NOT EXISTS lider_fase TEXT,                 -- voluntarios | votacao | definido
  ADD COLUMN IF NOT EXISTS lider_fase_ate TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS lider_identity TEXT,
  ADD COLUMN IF NOT EXISTS lider_voluntarios JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS lider_candidatos JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS lider_votos JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS lider_ausente_desde TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS questao_atual INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS riscos_prazo TIMESTAMPTZ,        -- 5 min após 90% concluírem
  ADD COLUMN IF NOT EXISTS riscos_nf JSONB NOT NULL DEFAULT '[]'::jsonb;  -- "Não Fez"

-- Quem foi para o suporte e como terminou:
--   suporte   -> na sala de suporte, tentando conectar o pacote
--   resolvido -> conectou antes da divisão: entra nos grupos normalmente
--   ouvinte   -> não conectou até a divisão: acompanha, sem participar das contagens
CREATE TABLE IF NOT EXISTS video_room_suporte (
  room_id UUID NOT NULL REFERENCES video_rooms(id) ON DELETE CASCADE,
  identity TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'suporte',
  pediu_ajuda_em TIMESTAMPTZ,
  entrou_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolvido_em TIMESTAMPTZ,
  PRIMARY KEY (room_id, identity)
);

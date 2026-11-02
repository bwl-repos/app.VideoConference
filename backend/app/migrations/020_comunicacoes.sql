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

-- Cadência do encontro: a sala avança de etapa sozinha, com o aval da turma.
--
-- Quando o tempo da etapa esgota, a sala pergunta "pode seguir?" e dá 15
-- segundos. Avança se a maioria dos PRESENTES disser que sim; quem não vota
-- conta como "não". Ver `app/services/cadencia.py`, que tem a regra inteira.
--
-- `auto_mode` nasce FALSE de propósito: salas que já existem continuam exatamente
-- como estavam, dirigidas pelo host. A automação é uma escolha por sala, não
-- uma mudança de comportamento que chega junto com o deploy.
ALTER TABLE video_room_openpbl_class
  ADD COLUMN IF NOT EXISTS auto_mode BOOLEAN NOT NULL DEFAULT false,
  -- Quando a etapa corrente começou. NULL = etapa posta antes de a cadência
  -- existir; a regra não inventa um começo e não abre voto sobre ela.
  ADD COLUMN IF NOT EXISTS stage_started_at TIMESTAMPTZ,
  -- Janela do voto. NULL = não há voto aberto.
  ADD COLUMN IF NOT EXISTS vote_ends_at TIMESTAMPTZ,
  -- A etapa que corria quando o voto abriu. Se o host trocar a etapa à mão no
  -- meio da votação, o voto era sobre outra pergunta e deixa de valer.
  ADD COLUMN IF NOT EXISTS vote_stage TEXT,
  -- `{identidade: true|false}`, só de quem votou. JSONB e não tabela própria:
  -- o voto morre com a etapa, nunca é consultado fora dela, e uma tabela
  -- exigiria limpeza que ninguém faria.
  ADD COLUMN IF NOT EXISTS votes JSONB NOT NULL DEFAULT '{}'::jsonb;

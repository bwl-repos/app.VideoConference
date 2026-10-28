-- Cadência do encontro: a sala avança de etapa sozinha, com o aval da turma.
--
-- Quando o tempo da etapa esgota, a sala pergunta "pode seguir?" e dá 15
-- segundos. Avança se a maioria dos PRESENTES disser que sim; quem não vota
-- conta como "não". Ver `app/services/cadencia.py`, que tem a regra inteira.
--
-- `auto_mode` nasce TRUE: a automação é o caminho padrão e assumir o controle é
-- que é a exceção. O host desliga quando quiser, pelo endpoint `/cadencia`.
--
-- Ligado não significa correndo: `stage_started_at` nasce NULO, e a regra NÃO
-- abre voto sobre etapa sem hora de início (ver `services/cadencia.py`). O
-- relógio só começa quando a etapa for posta -- à mão ou pela própria cadência.
-- Uma sala que já existia, portanto, não muda de comportamento no instante em
-- que esta coluna aparece; ela passa a avançar sozinha a partir da próxima
-- etapa, que é o que se quer.
ALTER TABLE video_room_openpbl_class
  ADD COLUMN IF NOT EXISTS auto_mode BOOLEAN NOT NULL DEFAULT true,
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

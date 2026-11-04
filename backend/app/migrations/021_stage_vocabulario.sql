-- O vocabulário de etapas, realinhado -- e desta vez pelo INVARIANTE, não por
-- uma lista de nomes antigos.
--
-- POR QUE EXISTE, já havendo a 013
-- --------------------------------
-- A 013 fazia exatamente isto em 2026, e **nunca foi aplicada em produção**:
-- medido em 04/11/2026, o DEFAULT da coluna ainda era 'presentation' e 43 das
-- 99 salas estavam numa etapa que a cadência não conhece. Consequência: sem
-- duração não há `stage_ends_at` (nenhum cronômetro na tela) e `decidir` nunca
-- manda avançar -- a sala fica ligada no automático, parada, e de fora parece
-- que está "esperando o facilitador".
--
-- A 013 listava os seis nomes do modelo antigo. Esta parte do INVARIANTE: é
-- inválida toda etapa fora do vocabulário corrente, tenha o nome que tiver.
-- Uma lista de nomes só cobre o passado que alguém lembrou de escrever.
--
-- IDEMPOTENTE: rodar de novo não muda nada depois da primeira vez.

-- 1. Toda linha nova nasce numa etapa que a cadência conhece.
ALTER TABLE video_room_openpbl_class ALTER COLUMN stage SET DEFAULT 'session_start';

-- 2. As salas presas voltam para a abertura.
--
-- `stage_started_at = NULL` junto, e é deliberado: a hora gravada é de uma
-- etapa que deixou de existir. Mantê-la faria a abertura nascer vencida e a
-- sala pular de etapa no primeiro acesso. Nula, o resgate em `_aplicar_cadencia`
-- marca a hora na primeira vez que alguém abre a sala, e os 10 minutos contam
-- a partir dali.
--
-- Nada se perde que estivesse visível: a tela já desenhava estas salas como
-- "Abertura" (o frontend troca etapa desconhecida por `session_start`).
UPDATE video_room_openpbl_class
   SET stage = 'session_start',
       stage_started_at = NULL
 WHERE stage NOT IN (
         'session_start', 'registration_open', 'amplify_code', 'registration_close',
         'synopsis', 'groups', 'plenary', 'question', 'situational',
         'release_risks', 'show_chart', 'closing', 'release_feedback', 'done'
       );

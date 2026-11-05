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

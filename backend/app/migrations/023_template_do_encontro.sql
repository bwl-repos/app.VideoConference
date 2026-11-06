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

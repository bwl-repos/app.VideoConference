/**
 * O roteiro da Videoconferência Integrada, na tela.
 *
 * Saiu do `VideoRoom.tsx` para um módulo próprio quando o painel admin passou a
 * mostrar um PREVIEW de cada etapa. A alternativa seria desenhar a tela da sala
 * de novo lá — uma segunda implementação, que divergiria no primeiro ajuste de
 * CSS e passaria a prometer uma tela que o encontro não mostra.
 *
 * Importar direto do `VideoRoom.tsx` não servia: o módulo da sala arrasta
 * LiveKit, tldraw e o SDK inteiro, e tudo isso entraria no pacote do painel.
 * Aqui não há nada disso — estas funções leem um retrato de roteiro e devolvem
 * JSX, e é por isso que elas podem ser compartilhadas.
 *
 * O conteúdo do encontro (sinopse, questões, riscos e os textos fixos de cada
 * seção) vem congelado na sala, montado pelo CustomerApp a partir do roteiro do
 * episódio. Antes isso era um pacote SCORM embutido por iframe e transmitido aos
 * alunos por screen-share recortado; agora a própria sala É a apresentação, então
 * facilitador e aluno renderizam exatamente a mesma tela — e, desde este módulo,
 * quem CONFIGURA o encontro vê a mesma coisa que eles vão ver.
 */
import type { OpenPblStage, RoteiroSnapshot, RoteiroBlocoFixo } from "../../lib/video-rooms-sdk";

/** Campo de texto do roteiro (vazio se ausente). */
export function rTexto(r: RoteiroSnapshot | null, name: string): string {
  const v = r?.campos?.[name];
  return typeof v === "string" ? v.trim() : "";
}

/** Um texto do roteiro com a voz dele. A voz vem de `audiosDosCampos`, um mapa
 *  IRMÃO de `campos` com a mesma forma: texto vira texto, lista vira lista do
 *  mesmo tamanho. Sem voz sintetizada ainda, `voz` é vazio e a sala só mostra. */
export interface ComVoz { texto: string; voz: string }

export function rTextoComVoz(r: RoteiroSnapshot | null, name: string): ComVoz {
  const v = r?.audiosDosCampos?.[name];
  return { texto: rTexto(r, name), voz: typeof v === "string" ? v : "" };
}

/** Campo de lista do roteiro com a voz de cada item, já sem os itens em branco.
 *
 *  O filtro dos vazios acontece AQUI, uma vez, com o par inteiro: filtrar texto
 *  e voz em dois lugares deslocaria um em relação ao outro, e a sala leria o
 *  item errado — sem erro nenhum na tela. */
export function rListaComVoz(r: RoteiroSnapshot | null, name: string): ComVoz[] {
  const v = r?.campos?.[name];
  const vozes = r?.audiosDosCampos?.[name];
  const dasVozes = Array.isArray(vozes) ? vozes : [];
  if (!Array.isArray(v)) return [];
  return v
    .map((x, i) => ({ texto: String(x || "").trim(), voz: String(dasVozes[i] || "") }))
    .filter((p) => p.texto);
}

/** Campo de lista do roteiro, já sem os itens em branco que o formulário permite. */
export function rLista(r: RoteiroSnapshot | null, name: string): string[] {
  return rListaComVoz(r, name).map((p) => p.texto);
}

/** Textos fixos de uma seção do roteiro (iguais em todo episódio). */
export function rBlocos(r: RoteiroSnapshot | null, key: string): RoteiroBlocoFixo[] {
  return r?.secoes?.find((s) => s.key === key)?.blocosFixos ?? [];
}

/** Título de uma seção — vem do snapshot (`schema.ts` é a fonte única), não do código. */
export function rTitulo(r: RoteiroSnapshot | null, key: string): string {
  return r?.secoes?.find((s) => s.key === key)?.titulo ?? "";
}

/** Qual seção do roteiro pertence a cada etapa do encontro.
 *
 *  Uma cópia só, de propósito: a tela da etapa e a VOZ da etapa leem daqui. Com
 *  duas cópias, divergir faria a sala falar o texto de uma seção enquanto mostra
 *  outra — e nada na tela acusaria o erro. `null` = etapa sem texto fixo. */
export function secaoDaEtapa(stage: OpenPblStage): string | null {
  switch (stage) {
    case "session_start":
      return null;   // vinheta da série, não é instrução
    // `amplify_code` entra com as de registro: é a mesma seção do roteiro
    // ("Abertura e registro"), e o `head` dela em STEPS é o mesmo. Sem esta
    // linha ela cairia no `default` e a tela mostraria a seção de FEEDBACK
    // no meio do registro de presença.
    case "registration_open": case "amplify_code": case "registration_close":
      return "abertura";
    case "synopsis":
      return "revisitando";
    case "groups":
      return "aquecimento";
    // Uma seção, DUAS etapas: ver `blocosDaEtapa`, que reparte os blocos.
    case "plenary": case "question":
      return "plenaria";
    case "situational": case "release_risks":
      return "analise";
    case "release_feedback": case "done":
      return "feedback";
    // `show_chart` e `closing`: a tela é o GRÁFICO, não um texto do roteiro.
    //
    // Estas quatro (com `question` e `situational`) caíam num `else` que
    // devolvia "feedback". Na TELA isso nunca apareceu — o gráfico e as
    // cascatas cobrem a seção —, mas a VOZ lê deste mesmo mapa, e o efeito era
    // a sala ANUNCIAR a última atividade do encontro no meio da análise de
    // riscos. Um `else` que "não acontece" para a tela acontece para quem lê o
    // mapa por outro motivo.
    default:
      return null;
  }
}

/** Os blocos de texto fixo DESTA etapa: a mesma lista que a tela mostra e que a
 *  voz lê, para as duas não divergirem.
 *
 *  A seção "Discussão em Plenária" é repartida entre duas etapas: o 1º bloco (o
 *  objetivo da discussão) abre a plenária, e os seguintes descrevem a DINÂMICA
 *  das questões — estes pertencem à tela "Questões para reflexão", onde entram
 *  como `intro` da cascata (ver `rIntroQuestoes`). */
export function blocosDaEtapa(r: RoteiroSnapshot | null, stage: OpenPblStage): RoteiroBlocoFixo[] {
  const secao = secaoDaEtapa(stage);
  if (!secao) return [];
  if (stage === "plenary") return rBlocos(r, secao).slice(0, 1);
  if (stage === "question") return rIntroQuestoes(r);
  return rBlocos(r, secao);
}

/** Dos blocos fixos da plenária, o 1º ("o objetivo da discussão") abre a etapa da
 *  plenária e os seguintes explicam a DINÂMICA das questões — estes pertencem à tela
 *  "Questões para reflexão". Salas sem roteiro (ou com um bloco só) não têm intro. */
export function rIntroQuestoes(r: RoteiroSnapshot | null): RoteiroBlocoFixo[] {
  return rBlocos(r, "plenaria").slice(1);
}

/** Blocos de texto fixo de uma seção — o "corpo" da tela de cada etapa. */
export function RoteiroBlocos({ blocos }: { blocos: RoteiroBlocoFixo[] }) {
  return (
    <>
      {blocos.map((b, i) => (
        // `vr-pbl-intro` = instrução do sistema: mesmo cartão discreto usado acima das
        // cascatas. O texto fixo situa a atividade; o destaque é do conteúdo variável.
        <div className="vr-pbl-intro" key={i}>
          {b.titulo && <strong>{b.titulo}</strong>}
          {b.lista ? (
            <ul className="vr-rot-bloco-ul">
              {b.paragrafos.map((t, k) => <li key={k}>{t}</li>)}
            </ul>
          ) : (
            b.paragrafos.map((t, k) => <p key={k}>{t}</p>)
          )}
        </div>
      ))}
    </>
  );
}

/** Tela de uma etapa do roteiro: título da seção + textos fixos + o conteúdo
 *  variável que aquela etapa pede. As etapas com cascata (plenária e análise
 *  situacional) e o gráfico são tratados fora daqui. */
export function RoteiroStage({ stage, roteiro, shown = 1 }: {
  stage: OpenPblStage; roteiro: RoteiroSnapshot | null;
  /** Quantos cards da cascata já foram revelados nesta etapa. */
  shown?: number;
}) {
  if (!roteiro) {
    return (
      <div className="vr-pbl-question">
        <div className="vr-pbl-question-waiting">
          Sem roteiro para este encontro.
          <span>Escolha o episódio ao criar a sala — o roteiro é preenchido em Gerenciar produção.</span>
        </div>
      </div>
    );
  }

  // Abertura: vinheta da série (o único conteúdo que não é card de texto corrido).
  if (stage === "session_start") {
    const serie = rTexto(roteiro, "serieTemporada");
    const titulo = rTexto(roteiro, "tituloEpisodio") || roteiro.episodio?.titulo || "";
    const marca = rTexto(roteiro, "marcaSerie");
    const direitos = rTexto(roteiro, "direitos");
    return (
      <div className="vr-rot vr-rot-abertura">
        {marca && <div className="vr-rot-marca">{marca}</div>}
        {serie && <div className="vr-rot-serie">{serie}</div>}
        {titulo && <div className="vr-rot-titulo">{titulo}</div>}
        {direitos && <div className="vr-rot-direitos">{direitos}</div>}
      </div>
    );
  }

  // Feedback da interação: tela PRÓPRIA da etapa (o gráfico sai de cena aqui). Leva o
  // título da seção porque é a única atividade em tela — sem ele o texto fica solto.
  if (stage === "release_feedback" || stage === "done") {
    const titulo = rTitulo(roteiro, "feedback");
    return (
      <div className="vr-rot vr-rot-feedback">
        {titulo && <div className="vr-rot-secao-tit">{titulo}</div>}
        <RoteiroBlocos blocos={rBlocos(roteiro, "feedback")} />
      </div>
    );
  }

  // Demais etapas: os blocos fixos da etapa (mapa único, ver `blocosDaEtapa` — a
  // MESMA lista que a voz lê).
  const blocos = blocosDaEtapa(roteiro, stage);

  // Conteúdo variável por etapa.
  // Cascatas aparecem card a card, conforme o facilitador avança (`shown`).
  const sinopseTodas = stage === "synopsis"
    ? [rTexto(roteiro, "sinopseParte1"), rTexto(roteiro, "sinopseParte2")].filter(Boolean)
    : [];
  const sinopse = sinopseTodas.slice(0, shown);
  const orientadorasTodas = stage === "groups" ? rLista(roteiro, "questoesOrientadoras") : [];
  const orientadoras = orientadorasTodas.slice(0, shown);
  const relembrando = stage === "plenary" ? rTexto(roteiro, "relembrandoEpisodio") : "";

  return (
    <div className="vr-rot">
      {/* Na abertura os blocos fixos são as instruções de registro de presença —
          é o que o participante precisa ler para entrar com o class code. */}
      {!!blocos.length && <RoteiroBlocos blocos={blocos} />}
      {relembrando && (
        // Mesmo cabeçalho das cascatas, para o conteúdo variável ficar identificado
        // como os demais (o card sozinho não dizia o que era).
        <div className="vr-rot-bloco-var">
          <div className="vr-pbl-qhead">
            <span className="vr-pbl-qhead-label">Relembrando o episódio</span>
          </div>
          <div className="vr-rot-destaque">{relembrando}</div>
        </div>
      )}
      {sinopse.length > 0 && (
        <QuestionCascade items={sinopse} total={sinopseTodas.length}
          label="Revisitando a situação-problema" progress emphasize inline />
      )}
      {orientadoras.length > 0 && (
        <QuestionCascade items={orientadoras} total={orientadorasTodas.length}
          label="Questões orientadoras" progress emphasize inline />
      )}
    </div>
  );
}

/** Cascata de cards revelados progressivamente — usada nas questões da plenária e
 *  nas dimensões de risco (Análise situacional). Facilitador e aluno renderizam o
 *  MESMO componente (o aluno recebe a lista por dados), então a UI/animação fica num
 *  só lugar. `progress` mostra os passos (●) no cabeçalho e `emphasize` realça o card
 *  mais recente — ambos fazem sentido só na revelação progressiva (plenária). */
export function QuestionCascade({ items, total, label, icon, progress = false, emphasize = false, inline = false, intro }: {
  items: string[];
  total?: number;
  label?: string;
  icon?: string;
  progress?: boolean;
  emphasize?: boolean;
  /** Renderiza no fluxo (dentro de uma tela do roteiro) em vez de cobrir a area. */
  inline?: boolean;
  /** Texto do roteiro que abre a etapa, acima dos cards. */
  intro?: RoteiroBlocoFixo[];
  /** Texto do roteiro que ABRE a etapa, acima da cascata (a plenária usa a dinâmica
   *  das questões). Slot opcional — as questões em si não mudam. */
}) {
  const count = items.length;
  const tot = Math.max(total ?? count, count, 1);
  return (
    <div className="vr-pbl-question" data-inline={inline ? "1" : undefined}>
      {label && (
        <div className="vr-pbl-qhead">
          <span className="vr-pbl-qhead-label">
            {label}
          </span>
          {progress && tot > 1 && (
            <span className="vr-pbl-qdots" aria-hidden="true">
              {Array.from({ length: tot }).map((_, i) => (
                <span className="vr-pbl-qdot" key={i} data-on={i < count ? "1" : undefined} />
              ))}
            </span>
          )}
        </div>
      )}
      {/* --vr-qn: quantos cards a etapa terá. O CSS usa para dividir a altura
          disponível e escolher o tamanho de fonte que ainda cabe. */}
      {!!intro?.length && <RoteiroBlocos blocos={intro} />}
      <div className="vr-pbl-qcascade" data-emphasize={emphasize ? "1" : undefined}
        data-qn={tot} style={{ ["--vr-qn" as any]: String(tot) }}>
        {items.map((q, i) => (
          <div className="vr-pbl-qcard" key={i} data-latest={emphasize && i === count - 1 ? "1" : undefined}>
            <span className="vr-pbl-qcard-num">{i + 1}</span>
            <span className="vr-pbl-qcard-text">{q}</span>
          </div>
        ))}
      </div>
    </div>
  );
}


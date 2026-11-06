/**
 * Encontro — as etapas, os temporizadores, o que a sala FALA e com que voz.
 *
 * ## A organização, e por que ela mudou
 *
 * A primeira versão desta tela empilhava quatro painéis: voz, ritmo, a tabela
 * das etapas e, no fim, os textos agrupados por SEÇÃO. Funcionava e era difícil
 * de usar pela mesma razão: **o texto ficava longe da etapa em que ele aparece**.
 * Para saber o que a sala diz na "Análise situacional" era preciso ler a tabela,
 * descobrir a seção, rolar até ela e cruzar na cabeça.
 *
 * Agora a unidade é a ETAPA: lista à esquerda, e à direita tudo que diz respeito
 * a ela — quanto dura, o que o ▶ faz, o texto que ela mostra e fala (editável
 * ali mesmo), onde entra cada informação do roteiro, e o **ensaio**: tocar a
 * etapa inteira, com as pausas, como a turma vai ouvir.
 *
 * Voz e ritmo do voto saíram para abas próprias: são três números e uma escolha
 * que valem para TODAS as etapas, e deixá-los no topo empurrava para baixo
 * justamente o que se vem ajustar.
 *
 * ## Uma seção pode servir a mais de uma etapa
 *
 * Três etapas compartilham a seção de abertura, e a plenária é repartida entre
 * duas. Editar "o texto da etapa" é, de fato, editar a SEÇÃO — e a tela diz
 * isso, nomeando as outras etapas afetadas. Esconder esse fato faria alguém
 * ajustar uma instrução de presença e mudar, sem saber, o que a sala diz em
 * outras duas etapas.
 *
 * ## O preview é ESTRUTURAL, não uma cópia da tela da sala
 *
 * Ele mostra o que entra na etapa — blocos fixos na ordem, lugares do roteiro —
 * com a mesma regra de renderização da sala (título em negrito, `lista` vira
 * marcadores), mas **não** reproduz o layout da videoconferência. Reproduzir
 * seria manter uma segunda implementação da tela da sala, que divergiria no
 * primeiro ajuste de CSS e passaria a prometer uma tela que não existe. O que
 * precisa ser fiel é o CONTEÚDO e a ORDEM; e o que é fiel de verdade, porque
 * toca o mesmo arquivo que a aula vai tocar, é o ensaio da voz.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { adminApi, adminFetch } from "./adminApi";

interface Campo {
  name: string; label: string; tipo: string;
  rotuloItem?: string; itensPrevistos?: number;
}
interface Bloco { titulo: string; lista: boolean; paragrafos: string[]; pausas: number[] }
interface Secao { key: string; blocos: Bloco[] }
interface Config {
  duracoes: Record<string, number | null>;
  janela_voto_s: number;
  tolerancia_s: number;
  limiar: number;
  voz: { provedor: string; voz: string; motor: string; rotulo: string };
  secoes: Secao[];
}
interface Etapa {
  id: string; titulo: string; acao: string; duracao_s: number | null; vota: boolean;
  secao: string | null; secao_titulo: string; blocos: string;
  textos: Bloco[]; campos: Campo[];
}
interface Dados {
  config: Config;
  etapas: Etapa[];
  secoes: Array<{ key: string; titulo: string; campos: Campo[] }>;
  limites: Record<string, [number, number]>;
  base: Config;
  persistente: boolean;
  voz_configurada: boolean;
  avanca_sozinha: string[];
}
interface VozDoCatalogo {
  id: string; rotulo: string; nota?: string; genero?: string; motores?: string[];
}
interface Provedor { id: string; rotulo: string; nota?: string; vozes: VozDoCatalogo[] }
interface Fala { texto: string; pausa_ms: number; url: string }

type Aba = "etapas" | "voz" | "ritmo";

/** Segundos em algo que se lê: "10 min", "7 min 30 s", "30 s". */
function dur(s: number | null | undefined): string {
  if (s === null || s === undefined) return "—";
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (!m) return `${r} s`;
  return r ? `${m} min ${r} s` : `${m} min`;
}

/** A soma das etapas: o encontro inteiro, sem contar o que a turma demora a votar. */
function total(c: Config): string {
  const s = Object.values(c.duracoes).reduce<number>((a, v) => a + (v || 0), 0);
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

/** Os blocos que ESTA etapa mostra, dentro da seção dela.
 *
 *  A repartição (`todos` / `primeiro` / `demais`) vem do servidor, que a deriva
 *  do mesmo catálogo que a sala usa — a tela não a reinventa. Devolve também o
 *  ÍNDICE de cada bloco dentro da seção, que é o que permite editar no lugar
 *  certo sem recalcular a fatia de novo na hora de gravar. */
function blocosDaEtapa(cfg: Config, etapa: Etapa): Array<{ bloco: Bloco; i: number }> {
  if (!etapa.secao) return [];
  const secao = cfg.secoes.find((s) => s.key === etapa.secao);
  if (!secao) return [];
  const todos = secao.blocos.map((bloco, i) => ({ bloco, i }));
  if (etapa.blocos === "primeiro") return todos.slice(0, 1);
  if (etapa.blocos === "demais") return todos.slice(1);
  return todos;
}

export default function EncontroPage() {
  const [dados, setDados] = useState<Dados | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [provedores, setProvedores] = useState<Provedor[]>([]);
  const [avisoVoz, setAvisoVoz] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [aba, setAba] = useState<Aba>("etapas");
  const [etapaAberta, setEtapaAberta] = useState<string>("");

  useEffect(() => {
    adminApi<Dados>("/encontro")
      .then((d) => {
        setDados(d); setCfg(d.config);
        setEtapaAberta((e) => e || d.etapas[0]?.id || "");
      })
      .catch((e) => setErro(String(e.message || e)));
  }, []);
  useEffect(() => {
    adminApi<{ provedores?: Provedor[]; erro?: string; avisoElevenLabs?: string }>("/encontro/vozes")
      .then((r) => {
        setProvedores(r.provedores || []);
        setAvisoVoz(r.erro || r.avisoElevenLabs || "");
      })
      .catch((e) => setAvisoVoz(String(e.message || e)));
  }, []);

  // `sujo` compara com o que o servidor devolveu, e não um booleano ligado em
  // cada `onChange`: digitar e desfazer deixaria o botão aceso prometendo uma
  // mudança que não existe.
  const sujo = useMemo(
    () => !!(cfg && dados) && JSON.stringify(cfg) !== JSON.stringify(dados.config),
    [cfg, dados]);

  const salvar = async () => {
    if (!cfg) return;
    setSalvando(true); setErro(null); setRecado(null);
    try {
      const r = await adminApi<{ config: Config; etapas: Etapa[] }>("/encontro", {
        method: "PUT", body: JSON.stringify(cfg),
      });
      // O servidor devolve o que FICOU valendo (ele poda o que não serve), e é
      // isso que volta para a tela: mostrar o que foi digitado faria quem
      // operou acreditar num valor que o encontro não cumpre.
      setDados((d) => (d ? { ...d, config: r.config, etapas: r.etapas } : d));
      setCfg(r.config);
      setRecado("Configuração salva. Os tempos e a voz já valem, inclusive para salas "
        + "abertas; o texto entra nas salas criadas de agora em diante.");
    } catch (e: any) {
      setErro(String(e.message || e));
    } finally {
      setSalvando(false);
    }
  };

  // Os painéis recebem um setter que NUNCA vê `null`: a tela só os desenha com
  // a configuração carregada, e tipar cada um com `Config | null` faria cada
  // `onChange` repetir a mesma guarda inútil.
  const alterar = (f: (c: Config) => Config) => setCfg((c) => (c ? f(c) : c));

  if (erro && !dados) return <div className="ad-err">Falha ao carregar: {erro}</div>;
  if (!dados || !cfg) return <div className="ad-muted">Carregando…</div>;

  const etapa = dados.etapas.find((e) => e.id === etapaAberta) || dados.etapas[0];

  return (
    <div className="enc">
      <div className="ad-head-row">
        <div>
          <h2 className="ad-h">Encontro · facilitação automática</h2>
          <div className="ad-muted enc-nota">
            {dados.etapas.length} etapas · {total(cfg)} de relógio ·
            voz {cfg.voz.rotulo || cfg.voz.voz} ·
            avança com mais de {Math.round(cfg.limiar * 100)}% dos presentes
          </div>
        </div>
        <div className="enc-acoes">
          {sujo && <span className="ad-muted">alterações não salvas</span>}
          <button className="ad-btn-outline" disabled={!sujo}
            onClick={() => setCfg(dados.config)}>Descartar</button>
          <button className="ad-btn" disabled={!sujo || salvando} onClick={salvar}>
            {salvando ? "Salvando…" : "Salvar"}
          </button>
        </div>
      </div>

      {!dados.persistente && (
        <div className="enc-aviso" data-lvl="crit">
          Este banco ainda não tem a tabela <code>encontro_template</code> (migration 023).
          A tela mostra os valores de fábrica e <strong>salvar vai falhar</strong> até a
          tabela existir — ela é criada na subida do serviço, então publicar resolve.
        </div>
      )}
      {!dados.voz_configurada && (
        <div className="enc-aviso" data-lvl="warn">
          Voz desligada neste serviço (falta <code>VOZ_CORE_URL</code>/<code>VOZ_CORE_TOKEN</code>).
          A sala mostra os textos e segue sem falar — e o ensaio aqui fica sem áudio.
        </div>
      )}
      {erro && <div className="ad-err">{erro}</div>}
      {recado && <div className="enc-aviso" data-lvl="ok">{recado}</div>}

      <div className="enc-abas">
        <button data-active={aba === "etapas"} onClick={() => setAba("etapas")}>
          Etapas e textos
        </button>
        <button data-active={aba === "voz"} onClick={() => setAba("voz")}>
          A voz
        </button>
        <button data-active={aba === "ritmo"} onClick={() => setAba("ritmo")}>
          O voto da turma
        </button>
      </div>

      {aba === "etapas" && (
        <div className="enc-mestre">
          <ListaDeEtapas etapas={dados.etapas} cfg={cfg} aberta={etapa?.id || ""}
            avancaSozinha={dados.avanca_sozinha} onAbrir={setEtapaAberta} />
          {etapa && (
            <DetalheDaEtapa etapa={etapa} etapas={dados.etapas} cfg={cfg} setCfg={alterar}
              padrao={dados.base} avancaSozinha={dados.avanca_sozinha}
              vozLigada={dados.voz_configurada} />
          )}
        </div>
      )}
      {aba === "voz" && (
        <PainelDaVoz cfg={cfg} setCfg={alterar} provedores={provedores} aviso={avisoVoz}
          ligada={dados.voz_configurada} />
      )}
      {aba === "ritmo" && (
        <PainelDoRitmo cfg={cfg} setCfg={alterar} limites={dados.limites} />
      )}
    </div>
  );
}

/* ---------------- A lista (mestre) ---------------- */

function ListaDeEtapas({ etapas, cfg, aberta, avancaSozinha, onAbrir }: {
  etapas: Etapa[]; cfg: Config; aberta: string; avancaSozinha: string[];
  onAbrir: (id: string) => void;
}) {
  return (
    <nav className="enc-lista" aria-label="Etapas do encontro">
      {etapas.map((e, i) => {
        const d = cfg.duracoes[e.id];
        const falas = e.secao
          ? blocosDaEtapa(cfg, e).reduce((n, b) => n + b.bloco.paragrafos.length, 0)
          : 0;
        return (
          <button key={e.id} className="enc-item" data-aberta={e.id === aberta}
            onClick={() => onAbrir(e.id)}>
            <span className="enc-item-n">{i + 1}</span>
            <span className="enc-item-txt">
              <strong>{e.acao}</strong>
              <span className="ad-muted">{e.titulo}</span>
            </span>
            <span className="enc-item-meta">
              <span className="enc-item-dur">{dur(d)}</span>
              {falas > 0 && <span className="ad-muted" title={`${falas} parágrafos falados`}>
                🔊 {falas}
              </span>}
              {d !== null && avancaSozinha.includes(e.id) && (
                <span className="ad-muted" title="Avança sem perguntar à turma">⏩</span>
              )}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

/* ---------------- O detalhe ---------------- */

function DetalheDaEtapa({ etapa, etapas, cfg, setCfg, padrao, avancaSozinha, vozLigada }: {
  etapa: Etapa; etapas: Etapa[]; cfg: Config; setCfg: (f: (c: Config) => Config) => void;
  padrao: Config; avancaSozinha: string[]; vozLigada: boolean;
}) {
  const blocos = blocosDaEtapa(cfg, etapa);
  const valor = cfg.duracoes[etapa.id];
  const dePadrao = padrao.duracoes[etapa.id];
  const sozinha = avancaSozinha.includes(etapa.id);

  // As OUTRAS etapas que mostram o mesmo texto. Editar aqui muda lá, e esconder
  // isso faria alguém ajustar a instrução de presença sem saber que mudou o que
  // a sala diz em mais duas etapas.
  const irmas = etapas.filter(
    (e) => e.id !== etapa.id && e.secao === etapa.secao && e.blocos === etapa.blocos);

  // Edita um bloco pelo índice DELE DENTRO DA SEÇÃO — e não dentro da fatia que
  // esta etapa mostra. A plenária mostra `[0]` e as questões mostram `[1..]`:
  // gravar pelo índice da fatia escreveria no bloco errado em uma das duas.
  const mexer = (i: number, f: (b: Bloco) => Bloco) =>
    setCfg((c) => ({
      ...c,
      secoes: c.secoes.map((s) => s.key !== etapa.secao ? s : {
        ...s, blocos: s.blocos.map((b, j) => (j === i ? f(b) : b)),
      }),
    }));

  return (
    <section className="enc-detalhe">
      <header className="enc-detalhe-h">
        <div>
          <h3 className="ad-h">{etapa.acao}</h3>
          <div className="ad-muted enc-nota">
            Fase: {etapa.titulo} · <code>{etapa.id}</code>
          </div>
        </div>
        <EnsaioDaEtapa etapa={etapa} blocos={blocos.map((b) => b.bloco)} ligada={vozLigada} />
      </header>

      <div className="enc-cartoes">
        <div className="ad-card">
          <div className="ad-card-l">Duração</div>
          {valor === null ? (
            <div className="ad-card-v enc-card-v">—</div>
          ) : (
            <>
              <div className="enc-dur">
                <input className="ad-input" type="number" value={valor} min={10} max={7200}
                  onChange={(ev) => setCfg((c) => ({
                    ...c, duracoes: { ...c.duracoes, [etapa.id]: Number(ev.target.value || 0) },
                  }))} />
                <span className="ad-muted">{dur(valor)}</span>
              </div>
              {valor !== dePadrao && (
                <button className="ad-link" onClick={() => setCfg((c) => ({
                  ...c, duracoes: { ...c.duracoes, [etapa.id]: dePadrao },
                }))}>↺ voltar ao padrão ({dur(dePadrao)})</button>
              )}
            </>
          )}
        </div>
        <div className="ad-card">
          <div className="ad-card-l">Quando o tempo acaba</div>
          <div className="enc-card-v">
            {valor === null
              ? <span className="ad-muted">etapa final, sem relógio</span>
              : sozinha
                ? <><span className="ad-pill" data-ok="false">avança sozinha</span>
                    <span className="ad-muted enc-nota">
                      Numa sala que ainda está enchendo não há a quem perguntar.
                    </span></>
                : <><span className="ad-pill">pergunta à turma</span>
                    <span className="ad-muted enc-nota">
                      {cfg.janela_voto_s}s para responder; avança com mais de{" "}
                      {Math.round(cfg.limiar * 100)}% dos presentes.
                    </span></>}
          </div>
        </div>
        <div className="ad-card">
          <div className="ad-card-l">Do roteiro do episódio</div>
          {etapa.campos.length ? (
            <div className="enc-chips">
              {etapa.campos.map((c) => <Lugares key={c.name} campo={c} />)}
            </div>
          ) : <div className="enc-card-v"><span className="ad-muted">nada nesta etapa</span></div>}
        </div>
      </div>

      <div className="enc-dois">
        <div>
          <h4 className="enc-sub">O que a sala fala e mostra</h4>
          {etapa.secao ? (
            <>
              <p className="ad-muted enc-nota">
                Seção <strong>{etapa.secao_titulo}</strong>
                {etapa.blocos !== "todos" && (etapa.blocos === "primeiro"
                  ? " (só o 1º bloco)" : " (do 2º bloco em diante)")}
                {irmas.length > 0 && (
                  <> · este texto também aparece em{" "}
                    <strong>{irmas.map((e) => e.acao).join(", ")}</strong></>
                )}
              </p>
              {blocos.length === 0 && (
                <p className="ad-muted enc-nota">
                  Sem texto fixo — esta etapa mostra só conteúdo do episódio.
                </p>
              )}
              {blocos.map(({ bloco, i }) => (
                <div className="enc-bloco" key={i}>
                  <div className="enc-bloco-h">
                    <input className="ad-input" placeholder="Título do bloco (opcional)"
                      value={bloco.titulo}
                      onChange={(e) => mexer(i, (b) => ({ ...b, titulo: e.target.value }))} />
                    <label className="ad-check" title="Desenha os parágrafos como lista com marcador">
                      <input type="checkbox" checked={bloco.lista}
                        onChange={(e) => mexer(i, (b) => ({ ...b, lista: e.target.checked }))} />
                      lista
                    </label>
                    <button className="ad-link ad-danger" title="Remove o bloco inteiro"
                      onClick={() => setCfg((c) => ({
                        ...c,
                        secoes: c.secoes.map((s) => s.key !== etapa.secao ? s : {
                          ...s, blocos: s.blocos.filter((_, j) => j !== i),
                        }),
                      }))}>remover bloco</button>
                  </div>
                  {bloco.paragrafos.map((p, pi) => (
                    <div className="enc-par" key={pi}>
                      <textarea className="ad-input" rows={2} value={p}
                        onChange={(e) => mexer(i, (b) => ({
                          ...b, paragrafos: b.paragrafos.map((x, k) => (k === pi ? e.target.value : x)),
                        }))} />
                      <label className="ad-field enc-pausa">
                        pausa (ms)
                        <input className="ad-input" type="number" min={0} max={30000} step={100}
                          value={bloco.pausas[pi] ?? 0}
                          onChange={(e) => mexer(i, (b) => ({
                            ...b,
                            pausas: b.paragrafos.map((_, k) =>
                              k === pi ? Number(e.target.value || 0) : (b.pausas[k] ?? 0)),
                          }))} />
                      </label>
                      <button className="ad-link ad-danger" title="Remove este parágrafo"
                        onClick={() => mexer(i, (b) => ({
                          ...b,
                          paragrafos: b.paragrafos.filter((_, k) => k !== pi),
                          // A pausa sai COM o parágrafo: as duas listas são
                          // alinhadas por índice, e remover só o texto faria a
                          // sala calar no lugar errado a partir daqui.
                          pausas: b.pausas.filter((_, k) => k !== pi),
                        }))}>✕</button>
                    </div>
                  ))}
                  <button className="ad-link"
                    onClick={() => mexer(i, (b) => ({
                      ...b, paragrafos: [...b.paragrafos, ""], pausas: [...b.pausas, 0],
                    }))}>+ parágrafo</button>
                </div>
              ))}
              {etapa.blocos !== "demais" && (
                <button className="ad-btn-outline"
                  onClick={() => setCfg((c) => ({
                    ...c,
                    secoes: c.secoes.map((s) => s.key !== etapa.secao ? s : {
                      ...s,
                      blocos: [...s.blocos,
                               { titulo: "", lista: false, paragrafos: [""], pausas: [0] }],
                    }),
                  }))}>+ bloco</button>
              )}
            </>
          ) : (
            <p className="ad-muted enc-nota">
              Esta etapa não tem texto fixo: a tela dela é o gráfico ou a vinheta da série,
              e a sala não fala nada ao abri-la.
            </p>
          )}
        </div>

        <div>
          <h4 className="enc-sub">Como entra na tela</h4>
          <PreviewDaEtapa etapa={etapa} blocos={blocos.map((b) => b.bloco)} />
        </div>
      </div>
    </section>
  );
}

/* ---------------- O preview ---------------- */

/** O que entra na tela desta etapa, na ordem.
 *
 *  Mesma regra de renderização da sala (`RoteiroBlocos` no VideoRoom): título em
 *  negrito, `lista` vira marcadores, parágrafos viram parágrafos. O que NÃO se
 *  copia é o layout da videoconferência — ver o cabeçalho deste arquivo. */
function PreviewDaEtapa({ etapa, blocos }: { etapa: Etapa; blocos: Bloco[] }) {
  const vazio = blocos.length === 0 && etapa.campos.length === 0;
  return (
    <div className="enc-preview">
      <div className="enc-preview-topo">
        <span>{etapa.titulo}</span>
        <span className="ad-muted">{dur(etapa.duracao_s)}</span>
      </div>
      <div className="enc-preview-corpo">
        {vazio && <p className="ad-muted">Sem texto e sem campos do roteiro nesta etapa.</p>}
        {blocos.map((b, i) => (
          <div className="enc-preview-bloco" key={i}>
            {b.titulo && <strong>{b.titulo}</strong>}
            {b.lista
              ? <ul>{b.paragrafos.map((t, k) => <li key={k}>{t || <em>(vazio)</em>}</li>)}</ul>
              : b.paragrafos.map((t, k) => <p key={k}>{t || <em>(vazio)</em>}</p>)}
          </div>
        ))}
        {etapa.campos.map((c) => (
          <div className="enc-preview-slot" key={c.name}>
            <span>{c.label}</span>
            {(c.itensPrevistos || 0) > 1 && (
              <em>{Array.from({ length: c.itensPrevistos! },
                (_, i) => `${c.rotuloItem || "item"} ${i + 1}`).join(" · ")}</em>
            )}
            <small>conteúdo do episódio, preenchido no roteiro</small>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- O ensaio (a voz) ---------------- */

/** Toca a etapa inteira, com as pausas, como a turma vai ouvir.
 *
 *  Ensaia o que está NA TELA, salvo ou não: é o ponto — ajustar uma palavra e a
 *  pausa e ouvir antes de gravar. O servidor sintetiza o que faltar e devolve a
 *  URL do MESMO objeto que a sala tocaria (mesma chave, mesmo perfil de voz),
 *  então o que se ouve aqui é o que a aula vai ouvir. */
function EnsaioDaEtapa({ etapa, blocos, ligada }: {
  etapa: Etapa; blocos: Bloco[]; ligada: boolean;
}) {
  const [carregando, setCarregando] = useState(false);
  const [tocando, setTocando] = useState(-1);
  const [falas, setFalas] = useState<Fala[]>([]);
  const [erro, setErro] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const vivo = useRef(false);

  const parar = () => {
    vivo.current = false;
    if (timer.current !== undefined) window.clearTimeout(timer.current);
    audio.current?.pause();
    setTocando(-1);
  };

  // Parar ao trocar de etapa ou sair da tela: sem isto, a fala da etapa
  // anterior continua tocando por cima da que está sendo configurada agora.
  useEffect(() => { parar(); setFalas([]); setErro(""); }, [etapa.id]);
  useEffect(() => () => parar(), []);

  const tocar = (lista: Fala[], i: number) => {
    if (!vivo.current) return;
    if (i >= lista.length) { setTocando(-1); return; }
    setTocando(i);
    const fala = lista[i];
    const seguir = (honrarPausa: boolean) => {
      if (!vivo.current) return;
      const ms = honrarPausa ? fala.pausa_ms : 0;
      if (!ms) { tocar(lista, i + 1); return; }
      timer.current = window.setTimeout(() => tocar(lista, i + 1), ms);
    };
    if (!fala.url) { seguir(false); return; }   // sem voz: segue para a próxima
    const a = new Audio(fala.url);
    audio.current = a;
    a.addEventListener("ended", () => seguir(true));
    // Mesma regra da sala: 404 e recusa do navegador seguem SEM esperar a
    // pausa — silêncio no lugar de uma frase que não foi dita é o dobro do
    // problema.
    a.addEventListener("error", () => seguir(false));
    a.play().catch(() => seguir(false));
  };

  const ensaiar = async () => {
    if (tocando >= 0) { parar(); return; }
    setErro(""); setCarregando(true);
    try {
      const corpo = {
        etapa: etapa.id,
        falas: blocos.flatMap((b) => b.paragrafos
          .map((texto, i) => ({ texto, pausa_ms: b.pausas[i] ?? 0 }))
          .filter((f) => f.texto.trim())),
      };
      const r = await adminApi<{ falas: Fala[]; desligado?: number }>("/encontro/ensaio", {
        method: "POST", body: JSON.stringify(corpo),
      });
      setFalas(r.falas);
      if (!r.falas.length) { setErro("Esta etapa não tem texto para falar."); return; }
      if (r.desligado) setErro("Voz desligada neste serviço: o ensaio segue sem áudio.");
      vivo.current = true;
      tocar(r.falas, 0);
    } catch (e: any) {
      setErro(String(e.message || e));
    } finally {
      setCarregando(false);
    }
  };

  const temTexto = blocos.some((b) => b.paragrafos.some((p) => p.trim()));
  return (
    <div className="enc-ensaio">
      <button className="ad-btn" disabled={carregando || !temTexto} onClick={ensaiar}
        title={ligada
          ? "Toca os textos desta etapa, na ordem e com as pausas, como a turma vai ouvir"
          : "Voz desligada neste serviço: o ensaio mostra a ordem, sem áudio"}>
        {carregando ? "Preparando…" : tocando >= 0 ? "■ Parar" : "▶ Ensaiar a etapa"}
      </button>
      {tocando >= 0 && falas[tocando] && (
        <div className="enc-ensaio-fala">
          <span className="ad-muted">{tocando + 1}/{falas.length}</span>
          <span>{falas[tocando].texto}</span>
          {falas[tocando].pausa_ms > 0 && (
            <span className="ad-muted">↳ pausa de {falas[tocando].pausa_ms} ms</span>
          )}
        </div>
      )}
      {erro && <div className="ad-muted enc-nota">{erro}</div>}
    </div>
  );
}

/* ---------------- A voz ---------------- */

function PainelDaVoz({ cfg, setCfg, provedores, aviso, ligada }: {
  cfg: Config; setCfg: (f: (c: Config) => Config) => void;
  provedores: Provedor[]; aviso: string; ligada: boolean;
}) {
  const [texto, setTexto] = useState(
    "Aponte o smartphone para o QR Code na tela para acessar a aplicação deste encontro.");
  const [ouvindo, setOuvindo] = useState(false);
  const [previaErro, setPreviaErro] = useState("");
  const [aquecendo, setAquecendo] = useState(false);
  const [aquecimento, setAquecimento] = useState<string>("");
  const audio = useRef<HTMLAudioElement | null>(null);

  const prov = provedores.find((p) => p.id === cfg.voz.provedor);
  const voz = prov?.vozes.find((v) => v.id === cfg.voz.voz);
  const motores = voz?.motores || [];

  const trocarProvedor = (id: string) => {
    const p = provedores.find((x) => x.id === id);
    const primeira = p?.vozes[0];
    setCfg((c) => ({
      ...c,
      voz: {
        provedor: id,
        voz: primeira?.id || "",
        // O motor só existe no Polly. No ElevenLabs o modelo é escolhido no
        // CoreService, e mandar um valor daqui só criaria um campo que o outro
        // lado ignora — e que a próxima pessoa tentaria ajustar.
        motor: id === "polly" ? (primeira?.motores?.[0] || "generative") : "",
        rotulo: primeira?.rotulo || "",
      },
    }));
  };

  const ouvir = async () => {
    setOuvindo(true); setPreviaErro("");
    try {
      const r = await adminFetch("/encontro/previa", {
        method: "POST", body: JSON.stringify({ texto, ...cfg.voz }),
      });
      if (!r.ok) {
        let detalhe = `${r.status}`;
        try { detalhe = (await r.json()).detail ?? detalhe; } catch { /* corpo não-JSON */ }
        throw new Error(String(detalhe));
      }
      const url = URL.createObjectURL(await r.blob());
      audio.current?.pause();
      const a = new Audio(url);
      audio.current = a;
      // Solta o blob quando a fala termina: sem isto, cada prévia deixa um
      // objeto na memória da aba pelo resto da sessão.
      a.addEventListener("ended", () => URL.revokeObjectURL(url));
      await a.play();
    } catch (e: any) {
      setPreviaErro(String(e.message || e));
    } finally {
      setOuvindo(false);
    }
  };

  const aquecer = async () => {
    setAquecendo(true); setAquecimento("");
    try {
      const r = await adminApi<any>("/encontro/aquecer", { method: "POST" });
      setAquecimento(r.desligado
        ? "voz desligada neste serviço"
        : `${r.textos} textos · ${r.prontos} sintetizados · ${r.ja_tinha} já existiam`
          + (r.falhas ? ` · ${r.falhas} falharam (ver o log)` : ""));
    } catch (e: any) {
      setAquecimento(String(e.message || e));
    } finally {
      setAquecendo(false);
    }
  };

  return (
    <section className="ad-panel">
      <h3 className="ad-h">A voz que lê o encontro</h3>
      <p className="ad-muted">
        Vale para todos os textos — os fixos e os do episódio. Trocar a voz não apaga
        nada: o áudio de cada texto é guardado pelo <em>hash do texto mais a voz</em>,
        então voltar para a voz anterior reaproveita o que já foi sintetizado.
      </p>
      {aviso && <div className="enc-aviso" data-lvl="warn">Catálogo de vozes: {aviso}</div>}

      <div className="enc-voz">
        <label className="ad-field">
          Provedor
          <select className="ad-input" value={cfg.voz.provedor}
            onChange={(e) => trocarProvedor(e.target.value)}>
            {provedores.length === 0 && <option value={cfg.voz.provedor}>{cfg.voz.provedor}</option>}
            {provedores.map((p) => <option key={p.id} value={p.id}>{p.rotulo}</option>)}
          </select>
          {prov?.nota && <span className="ad-muted enc-nota">{prov.nota}</span>}
        </label>

        <label className="ad-field">
          Voz
          <select className="ad-input" value={cfg.voz.voz}
            onChange={(e) => {
              const v = prov?.vozes.find((x) => x.id === e.target.value);
              setCfg((c) => ({
                ...c,
                voz: {
                  ...c.voz, voz: e.target.value, rotulo: v?.rotulo || e.target.value,
                  motor: c.voz.provedor === "polly"
                    ? (v?.motores?.includes(c.voz.motor) ? c.voz.motor : (v?.motores?.[0] || ""))
                    : "",
                },
              }));
            }}>
            {!prov && <option value={cfg.voz.voz}>{cfg.voz.rotulo || cfg.voz.voz}</option>}
            {prov?.vozes.map((v) => (
              <option key={v.id} value={v.id}>
                {v.rotulo}{v.genero ? ` · ${v.genero}` : ""}
              </option>
            ))}
          </select>
          {voz?.nota && <span className="ad-muted enc-nota">{voz.nota}</span>}
        </label>

        {cfg.voz.provedor === "polly" && (
          <label className="ad-field">
            Motor
            <select className="ad-input" value={cfg.voz.motor}
              onChange={(e) => setCfg((c) => ({ ...c, voz: { ...c.voz, motor: e.target.value } }))}>
              {(motores.length ? motores : [cfg.voz.motor]).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <span className="ad-muted enc-nota">
              generative soa melhor; neural e standard existem para as vozes que não têm generative.
            </span>
          </label>
        )}
      </div>

      <label className="ad-field">
        Ouvir antes de salvar
        <textarea className="ad-input" rows={2} value={texto}
          onChange={(e) => setTexto(e.target.value)} />
      </label>
      <div className="enc-acoes enc-acoes--esq">
        <button className="ad-btn-outline" disabled={ouvindo || !ligada || !texto.trim()}
          onClick={ouvir}>{ouvindo ? "Sintetizando…" : "🔊 Ouvir"}</button>
        <button className="ad-btn-outline" disabled={aquecendo || !ligada} onClick={aquecer}
          title="Sintetiza agora todo o texto fixo na voz salva, para a primeira sala não esperar">
          {aquecendo ? "Aquecendo…" : "⚡ Sintetizar todo o texto fixo"}
        </button>
        {aquecimento && <span className="ad-muted">{aquecimento}</span>}
      </div>
      {previaErro && <div className="ad-err">{previaErro}</div>}
      <p className="ad-muted enc-nota">
        A prévia usa a voz <strong>selecionada</strong>, mesmo antes de salvar — e o áudio
        fica guardado, então ouvir já adianta a síntese. O botão de sintetizar todo o
        texto usa a voz <strong>salva</strong>: é o que evita que a primeira sala criada
        depois da troca seja quem paga a espera.
      </p>
    </section>
  );
}

/* ---------------- O ritmo do voto ---------------- */

function PainelDoRitmo({ cfg, setCfg, limites }: {
  cfg: Config; setCfg: (f: (c: Config) => Config) => void;
  limites: Record<string, [number, number]>;
}) {
  const num = (campo: keyof Config, valor: string) =>
    setCfg((c) => ({ ...c, [campo]: Number(valor || 0) } as Config));
  return (
    <section className="ad-panel">
      <h3 className="ad-h">O voto da turma</h3>
      <p className="ad-muted">
        Vale para todas as etapas que perguntam. As quatro primeiras não perguntam:
        numa sala que ainda está enchendo não há a quem perguntar, e quem não vota conta
        como “não” — o voto nunca passaria.
      </p>
      <div className="enc-ritmo">
        <label className="ad-field">
          Janela do voto (s)
          <input className="ad-input" type="number" value={cfg.janela_voto_s}
            min={limites.janela[0]} max={limites.janela[1]}
            onChange={(e) => num("janela_voto_s", e.target.value)} />
          <span className="ad-muted enc-nota">
            Quanto a turma tem para responder “podemos seguir?”.
          </span>
        </label>
        <label className="ad-field">
          Tolerância (s)
          <input className="ad-input" type="number" value={cfg.tolerancia_s}
            min={limites.tolerancia[0]} max={limites.tolerancia[1]}
            onChange={(e) => num("tolerancia_s", e.target.value)} />
          <span className="ad-muted enc-nota">
            O que a etapa ganha quando o voto não passa — um empurrão, não outro período.
          </span>
        </label>
        <label className="ad-field">
          Para avançar, % dos presentes
          <input className="ad-input" type="number" step={1} min={0} max={95}
            value={Math.round(cfg.limiar * 100)}
            onChange={(e) => setCfg((c) => ({ ...c, limiar: Number(e.target.value || 0) / 100 }))} />
          <span className="ad-muted enc-nota">
            Comparação <strong>estrita</strong>: com 50%, empate não avança. Quem não vota
            conta como “não”, então subir este número endurece bastante o avanço.
          </span>
        </label>
      </div>
    </section>
  );
}

/* ---------------- Peças pequenas ---------------- */

/** Os LUGARES do roteiro, não o conteúdo: "Questão 1 · 2 · 3".
 *
 *  É o que a tela de configuração precisa dizer — em que etapa cada informação
 *  do roteiro aparece. O conteúdo é do episódio, muda a cada semana e é
 *  preenchido no CustomerApp. */
function Lugares({ campo }: { campo: Campo }) {
  const n = campo.itensPrevistos || 0;
  return (
    <span className="enc-chip" data-tipo={campo.tipo}>
      {campo.label}
      {n > 1 && (
        <em>
          {Array.from({ length: n }, (_, i) => `${campo.rotuloItem || "item"} ${i + 1}`).join(" · ")}
        </em>
      )}
      {campo.tipo === "imagem" && <em>imagem de fundo</em>}
    </span>
  );
}

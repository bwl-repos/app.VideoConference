/**
 * Encontro — as etapas, os temporizadores, o que a sala FALA e com que voz.
 *
 * Até esta tela existir, as três coisas eram constante de código em três
 * repositórios: a duração em `cadencia.py`, o texto fixo no `schema.ts` do
 * CustomerApp, a voz no `routers/voz.py` do CoreService. Ajustar o ritmo de um
 * encontro pedia um deploy; trocar a voz, outro.
 *
 * O que a tela mostra, e por que nesta ordem:
 *
 *  1. **A voz** — é a decisão que muda o encontro inteiro, e é a única com
 *     prévia: ninguém deveria trocar a voz de todos os encontros sem ouvir.
 *  2. **O ritmo do voto** — três números que valem para todas as etapas.
 *  3. **As etapas** — a ordem do encontro, com a duração de cada uma, se a
 *     turma vota para sair dela, e QUAIS LUGARES do roteiro aparecem nela.
 *  4. **Os textos** — por seção, com a pausa depois de cada parágrafo.
 *
 * ## O que esta tela NÃO mostra
 *
 * O conteúdo do episódio. "Questão 1, 2, 3" é o LUGAR onde a questão entra; a
 * questão em si é preenchida pelo curador no CustomerApp e muda a cada semana.
 * Mostrá-la aqui faria esta tela parecer editável quando não é — e daria duas
 * telas para a mesma informação.
 *
 * ## A ordem das etapas não está escrita aqui
 *
 * Ela vem do servidor (`GET /api/admin/encontro`), que a deriva de
 * `cadencia.ORDEM`. Escrevê-la neste arquivo criaria a QUARTA cópia da lista de
 * etapas — e a terceira já custou uma produção com a tela mentindo sobre onde o
 * encontro estava (ver `provas/prova_cadencia.py`).
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

export default function EncontroPage() {
  const [dados, setDados] = useState<Dados | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [provedores, setProvedores] = useState<Provedor[]>([]);
  const [avisoVoz, setAvisoVoz] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [recado, setRecado] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  const carregar = () =>
    adminApi<Dados>("/encontro")
      .then((d) => { setDados(d); setCfg(d.config); })
      .catch((e) => setErro(String(e.message || e)));

  useEffect(() => { carregar(); }, []);
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
      setRecado("Configuração salva. Vale para as salas criadas de agora em diante — "
        + "os temporizadores e a voz valem também para as salas já abertas.");
    } catch (e: any) {
      setErro(String(e.message || e));
    } finally {
      setSalvando(false);
    }
  };

  // Os painéis recebem um setter que NUNCA vê `null`: a tela só os desenha com
  // a configuração carregada, e tipar cada um deles com `Config | null` faria
  // cada `onChange` repetir a mesma guarda inútil.
  const alterar = (f: (c: Config) => Config) => setCfg((c) => (c ? f(c) : c));

  if (erro && !dados) return <div className="ad-err">Falha ao carregar: {erro}</div>;
  if (!dados || !cfg) return <div className="ad-muted">Carregando…</div>;

  return (
    <div className="enc">
      <div className="ad-head-row">
        <h2 className="ad-h">Encontro · facilitação automática</h2>
        <div className="enc-acoes">
          {sujo && <span className="ad-muted">alterações não salvas</span>}
          <button className="ad-btn-outline" disabled={!sujo}
            onClick={() => setCfg(dados.config)}>Descartar</button>
          <button className="ad-btn" disabled={!sujo || salvando} onClick={salvar}>
            {salvando ? "Salvando…" : "Salvar"}
          </button>
        </div>
      </div>

      <p className="ad-muted enc-intro">
        O encontro inteiro soma <strong>{total(cfg)}</strong> de etapas, mais o que a
        turma demorar a votar. Quando o tempo de uma etapa esgota, a sala pergunta
        “podemos seguir?” e avança se mais de {Math.round(cfg.limiar * 100)}% dos
        presentes disser que sim — <strong>quem não vota conta como “não”</strong>.
      </p>

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
          A sala mostra os textos e segue sem falar — e a prévia aqui não funciona.
        </div>
      )}
      {erro && <div className="ad-err">{erro}</div>}
      {recado && <div className="enc-aviso" data-lvl="ok">{recado}</div>}

      <PainelDaVoz cfg={cfg} setCfg={alterar} provedores={provedores} aviso={avisoVoz}
        ligada={dados.voz_configurada} />

      <PainelDoRitmo cfg={cfg} setCfg={alterar} limites={dados.limites} />

      <PainelDasEtapas cfg={cfg} setCfg={alterar} etapas={dados.etapas}
        padrao={dados.base} avancaSozinha={dados.avanca_sozinha} />

      <PainelDosTextos cfg={cfg} setCfg={alterar} dados={dados} />
    </div>
  );
}

/* ---------------- 1. A voz ---------------- */

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

/* ---------------- 2. O ritmo do voto ---------------- */

function PainelDoRitmo({ cfg, setCfg, limites }: {
  cfg: Config; setCfg: (f: (c: Config) => Config) => void;
  limites: Record<string, [number, number]>;
}) {
  const num = (campo: keyof Config, valor: string) =>
    setCfg((c) => ({ ...c, [campo]: Number(valor || 0) } as Config));
  return (
    <section className="ad-panel">
      <h3 className="ad-h">O voto da turma</h3>
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

/* ---------------- 3. As etapas ---------------- */

function PainelDasEtapas({ cfg, setCfg, etapas, padrao, avancaSozinha }: {
  cfg: Config; setCfg: (f: (c: Config) => Config) => void;
  etapas: Etapa[]; padrao: Config; avancaSozinha: string[];
}) {
  return (
    <section className="ad-panel">
      <h3 className="ad-h">As {etapas.length} etapas, na ordem do encontro</h3>
      <p className="ad-muted">
        A ordem vem do servidor e não se configura aqui — ela está no código da cadência,
        do sequenciador do facilitador e da tela da sala, e as três são conferidas por
        prova. O que se ajusta é <strong>quanto cada uma dura</strong>.
      </p>
      <table className="ad-table enc-etapas">
        <thead>
          <tr>
            <th>#</th><th>Etapa</th><th>O que o ▶ faz</th>
            <th>Duração</th><th>Ao vencer</th><th>Texto e roteiro na tela</th>
          </tr>
        </thead>
        <tbody>
          {etapas.map((e, i) => {
            const valor = cfg.duracoes[e.id];
            const dePadrao = padrao.duracoes[e.id];
            const sozinha = avancaSozinha.includes(e.id);
            return (
              <tr key={e.id}>
                <td className="ad-muted">{i + 1}</td>
                <td>
                  <strong>{e.titulo}</strong>
                  <div className="ad-muted enc-id">{e.id}</div>
                </td>
                <td>{e.acao}</td>
                <td className="enc-dur">
                  {valor === null ? (
                    <span className="ad-muted" title="Etapa final: não tem relógio">sem relógio</span>
                  ) : (
                    <>
                      <input className="ad-input" type="number" value={valor} min={10} max={7200}
                        onChange={(ev) => setCfg((c) => ({
                          ...c, duracoes: { ...c.duracoes, [e.id]: Number(ev.target.value || 0) },
                        }))} />
                      <span className="ad-muted">{dur(valor)}</span>
                      {valor !== dePadrao && (
                        <button className="ad-link" title={`Padrão: ${dur(dePadrao)}`}
                          onClick={() => setCfg((c) => ({
                            ...c, duracoes: { ...c.duracoes, [e.id]: dePadrao },
                          }))}>↺ padrão</button>
                      )}
                    </>
                  )}
                </td>
                <td>
                  {valor === null
                    ? <span className="ad-muted">—</span>
                    : sozinha
                      ? <span className="ad-pill" data-ok="false">avança sozinha</span>
                      : <span className="ad-pill">pergunta à turma</span>}
                </td>
                <td>
                  {e.secao ? (
                    <div className="enc-secao-ref">
                      <span className="ad-muted">{e.secao_titulo}</span>
                      {e.blocos !== "todos" && (
                        <span className="ad-muted enc-nota">
                          {e.blocos === "primeiro" ? "só o 1º bloco" : "do 2º bloco em diante"}
                        </span>
                      )}
                      <span className="ad-muted enc-nota">
                        {e.textos.reduce((n, b) => n + b.paragrafos.length, 0)} parágrafos falados
                      </span>
                    </div>
                  ) : <span className="ad-muted">sem texto fixo</span>}
                  <div className="enc-chips">{e.campos.map((c) => <Lugares key={c.name} campo={c} />)}</div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="ad-muted enc-nota">
        As quatro primeiras etapas <strong>avançam sozinhas</strong>: numa sala que ainda
        está enchendo não há a quem perguntar, e quem não vota conta como “não” — o voto
        nunca passaria e a sala nunca começaria.
      </p>
    </section>
  );
}

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

/* ---------------- 4. Os textos e as pausas ---------------- */

function PainelDosTextos({ cfg, setCfg, dados }: {
  cfg: Config; setCfg: (f: (c: Config) => Config) => void; dados: Dados;
}) {
  // Atualiza um parágrafo (ou a pausa dele) sem mutar nada: cada nível é
  // recriado. Mutar o objeto em estado faria o React não re-renderizar e o
  // campo "não aceitar o que foi digitado".
  const mexer = (si: number, bi: number, f: (b: Bloco) => Bloco) =>
    setCfg((c) => ({
      ...c,
      secoes: c.secoes.map((s, i) => i !== si ? s : {
        ...s, blocos: s.blocos.map((b, j) => (j === bi ? f(b) : b)),
      }),
    }));

  return (
    <section className="ad-panel">
      <h3 className="ad-h">O que a sala mostra e fala</h3>
      <p className="ad-muted">
        Este é o texto da plataforma, igual em todo episódio. Editar aqui vale para as
        salas criadas <strong>de agora em diante</strong>: cada sala guarda o texto do dia
        em que foi criada, para uma edição não trocar a instrução na cara de uma turma no
        meio da leitura. A <strong>pausa</strong> é o silêncio depois do parágrafo.
      </p>
      {cfg.secoes.map((secao, si) => {
        const meta = dados.secoes.find((s) => s.key === secao.key);
        const etapas = dados.etapas.filter((e) => e.secao === secao.key);
        return (
          <div className="enc-secao" key={secao.key}>
            <div className="enc-secao-h">
              <h4>{meta?.titulo || secao.key}</h4>
              <span className="ad-muted">
                {etapas.length
                  ? `aparece em: ${etapas.map((e) => e.titulo).join(", ")}`
                  : "nenhuma etapa usa esta seção"}
              </span>
            </div>
            {!!meta?.campos.length && (
              <div className="enc-chips">
                {meta.campos.map((c) => <Lugares key={c.name} campo={c} />)}
              </div>
            )}
            {secao.blocos.length === 0 && (
              <p className="ad-muted enc-nota">
                Sem texto fixo — esta seção é só conteúdo do episódio.
              </p>
            )}
            {secao.blocos.map((bloco, bi) => (
              <div className="enc-bloco" key={bi}>
                <div className="enc-bloco-h">
                  <input className="ad-input" placeholder="Título do bloco (opcional)"
                    value={bloco.titulo}
                    onChange={(e) => mexer(si, bi, (b) => ({ ...b, titulo: e.target.value }))} />
                  <label className="ad-check" title="Desenha os parágrafos como lista com marcador">
                    <input type="checkbox" checked={bloco.lista}
                      onChange={(e) => mexer(si, bi, (b) => ({ ...b, lista: e.target.checked }))} />
                    lista
                  </label>
                  <button className="ad-link ad-danger" title="Remove o bloco inteiro"
                    onClick={() => setCfg((c) => ({
                      ...c,
                      secoes: c.secoes.map((s, i) => i !== si ? s : {
                        ...s, blocos: s.blocos.filter((_, j) => j !== bi),
                      }),
                    }))}>remover bloco</button>
                </div>
                {bloco.paragrafos.map((p, pi) => (
                  <div className="enc-par" key={pi}>
                    <textarea className="ad-input" rows={2} value={p}
                      onChange={(e) => mexer(si, bi, (b) => ({
                        ...b, paragrafos: b.paragrafos.map((x, k) => (k === pi ? e.target.value : x)),
                      }))} />
                    <label className="ad-field enc-pausa">
                      pausa (ms)
                      <input className="ad-input" type="number" min={0} max={30000} step={100}
                        value={bloco.pausas[pi] ?? 0}
                        onChange={(e) => mexer(si, bi, (b) => ({
                          ...b,
                          pausas: b.paragrafos.map((_, k) =>
                            k === pi ? Number(e.target.value || 0) : (b.pausas[k] ?? 0)),
                        }))} />
                    </label>
                    <button className="ad-link ad-danger" title="Remove este parágrafo"
                      onClick={() => mexer(si, bi, (b) => ({
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
                  onClick={() => mexer(si, bi, (b) => ({
                    ...b, paragrafos: [...b.paragrafos, ""], pausas: [...b.pausas, 0],
                  }))}>+ parágrafo</button>
              </div>
            ))}
            <button className="ad-btn-outline"
              onClick={() => setCfg((c) => ({
                ...c,
                secoes: c.secoes.map((s, i) => i !== si ? s : {
                  ...s, blocos: [...s.blocos, { titulo: "", lista: false, paragrafos: [""], pausas: [0] }],
                }),
              }))}>+ bloco</button>
          </div>
        );
      })}
      <p className="ad-muted enc-nota">
        Parágrafo em branco é descartado ao salvar, e bloco sem parágrafo nenhum também —
        a sala desenharia uma caixa muda. Texto editado perde a voz antiga e ganha uma
        chave nova: use <strong>⚡ Sintetizar todo o texto fixo</strong> depois de editar,
        ou a primeira sala criada é que vai esperar pela síntese.
      </p>
    </section>
  );
}

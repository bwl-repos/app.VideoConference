import React, { useEffect, useMemo, useRef, useState, lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes, useParams } from "react-router-dom";
import { SDKContext } from "./lib/sdk-context";
import { createVideoRoomsSDK } from "./lib/video-rooms-sdk";
import { guestAuth } from "./lib/guest-auth";
import { applyBranding } from "./lib/branding";
import { clientApi } from "./client/clientApi";
import VideoRoom from "./components/video/VideoRoom";
import NewRoomModal, { type NewRoomData } from "./components/NewRoomModal";
import LobbyWaiting from "./components/video/LobbyWaiting";
import "./styles/app.css";

// Egress recording template — loaded only when egress opens /recording-view.
const RecordingView = lazy(() => import("./components/video/RecordingView"));
// Admin panel — loaded only on /admin.
const AdminApp = lazy(() => import("./admin/AdminApp"));
// Public integration docs — loaded only on /documentation.
const Documentation = lazy(() => import("./components/Documentation"));
// SaaS marketing landing — loaded only on /.
const Landing = lazy(() => import("./components/Landing"));
// Client self-service portal — loaded only on /portal.
const ClientApp = lazy(() => import("./client/ClientApp"));

const apiBase = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const wsBase = import.meta.env.VITE_WS_BASE || "ws://localhost:8000";

// Host/app SDK: identity + tenant come from the portal session cookie, not from
// spoofable X-User-* headers. The backend reads `client_session`. Em dev o apiBase
// fica em outra origem (:8000), então o cookie só viaja com credentials "include".
const sdk = createVideoRoomsSDK({ apiBase, wsBase, headers: () => ({}), credentials: "include" });

/** Guests join via invite token — no host auth headers. */
const guestSdk = createVideoRoomsSDK({
  apiBase, wsBase,
  headers: () => guestAuth.id ? { "X-User-Id": guestAuth.id, "X-User-Name": guestAuth.name, "X-User-Role": "user" } : {},
});

const STATUS_LABEL: Record<string, string> = { active: "ativa", ended: "encerrada" };
function fmtDate(iso?: string): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

function Logo() {
  return <div className="app-logo">V</div>;
}

function Home() {
  const [me, setMe] = useState<any>(null);
  const [booting, setBooting] = useState(true);
  const [usage, setUsage] = useState<any>(null);
  const [rooms, setRooms] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [filter, setFilter] = useState<"all" | "active" | "ended">("all");

  const refresh = () => {
    sdk.rooms.list().then(setRooms).catch(() => {});
    clientApi("/usage").then(setUsage).catch(() => {});
  };

  useEffect(() => {
    clientApi<any>("/me")
      .then((m) => {
        setMe(m);
        applyBranding(m.license?.branding || {});
        if (m.user?.name) localStorage.setItem("uname", m.user.name);
        refresh();
      })
      .catch(() => { location.href = "/portal"; })
      .finally(() => setBooting(false));
  }, []);

  const limits = me?.license?.limits;
  const activeCount = usage?.rooms_active ?? rooms.filter((r) => r.status === "active").length;
  const roomCap = limits && limits.max_rooms !== -1 ? limits.max_rooms : null;
  const atLimit = roomCap != null && activeCount >= roomCap;

  const createRoom = async (data: NewRoomData) => {
    try {
      const r = await sdk.rooms.create(data as any);
      location.href = `/r/${r.id}`;
    } catch (e: any) {
      const msg = String(e?.message || "");
      alert(msg.includes("limite") ? "Limite de salas ativas da sua licença atingido." : "Não foi possível criar a sala.");
      setShowModal(false);
    }
  };

  const endRoom = async (id: string) => {
    if (!confirm("Encerrar esta sala?")) return;
    await sdk.rooms.end(id).catch(() => {});
    refresh();
  };

  const logout = async () => { await clientApi("/logout", { method: "POST" }).catch(() => {}); location.href = "/portal"; };

  const openRecording = async (id: string) => {
    try {
      const r = await sdk.recording.get(id);
      if (r.url) window.open(r.url, "_blank", "noopener");
      else alert("Gravação ainda processando — tente novamente em instantes.");
    } catch {
      alert("Não foi possível abrir a gravação.");
    }
  };

  if (booting) return <div className="app-shell app-center"><div className="app-sub">Carregando…</div></div>;
  if (!me) return null; // redirecting to /portal

  const brand = me.license?.branding || {};
  const firstName = (me.user?.name || "").split(" ")[0] || "Anfitrião";
  const shown = rooms.filter((r) => filter === "all" || r.status === filter);

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="app-brand">
          {brand.logo_url ? <img className="app-logo app-logo-img" src={brand.logo_url} alt="" /> : <Logo />}
          <span>{brand.product_name || "Video Rooms"}</span>
        </div>
        <div className="app-user">
          <span className="app-lic-chip">{me.license?.name}</span>
          <a className="app-navlink" href="/portal">Portal</a>
          <div className="app-avatar" title={me.user?.email}>{firstName.slice(0, 1).toUpperCase()}</div>
          <button className="app-navlink app-navlink-btn" onClick={logout}>Sair</button>
        </div>
      </header>

      <main className="app-main">
        <section className="app-hero">
          <h1>Olá, {firstName} 👋</h1>
          <p className="app-sub">Crie uma sala e convide participantes em segundos.</p>
        </section>

        <div className="app-create">
          <button className="app-btn app-btn-create" disabled={atLimit} onClick={() => setShowModal(true)}>
            + Nova sala de vídeo
          </button>
          {atLimit && <p className="app-limit-msg">Você atingiu o limite de {roomCap} sala(s) ativa(s) da sua licença. Encerre uma sala para criar outra.</p>}
        </div>

        {showModal && <NewRoomModal onClose={() => setShowModal(false)} onCreate={createRoom} />}

        <div className="app-list-head">
          <h2 className="app-section-title">Suas salas</h2>
          <div className="app-tabs">
            {([["all", "Todas"], ["active", "Ativas"], ["ended", "Encerradas"]] as const).map(([k, lbl]) => (
              <button key={k} className="app-tab" data-active={filter === k} onClick={() => setFilter(k)}>{lbl}</button>
            ))}
          </div>
        </div>

        <div className="app-room-list">
          {shown.length === 0 && <div className="app-empty">Nenhuma sala {filter === "active" ? "ativa" : filter === "ended" ? "encerrada" : "ainda"}.</div>}
          {shown.map((r) => (
            <div className="app-room" key={r.id}>
              <a className="app-room-info" href={`/r/${r.id}`}>
                <span className="app-room-title">{r.title}</span>
                <span className="app-room-date">{fmtDate(r.created_at)}</span>
              </a>
              <div className="app-room-actions">
                {r.recording_url && (
                  <button className="app-rec" onClick={() => openRecording(r.id)} title="Assistir gravação">▶ Gravação</button>
                )}
                <span className="app-badge" data-status={r.status}>{STATUS_LABEL[r.status] || r.status}</span>
                {r.status === "active" ? (
                  <>
                    <a className="app-join" href={`/r/${r.id}`}>Entrar</a>
                    <button className="app-end" onClick={() => endRoom(r.id)}>Encerrar</button>
                  </>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

function RoomPage() {
  const { id } = useParams();
  const name = localStorage.getItem("uname") || "Anfitrião";
  return <VideoRoom roomId={id!} isStaff displayName={name} onLeft={() => (location.href = "/app")} />;
}

/** Iframe embed: the client's backend mints a token (with its API key) and loads
 *  this URL in an <iframe>. The API key never reaches the browser. */
function EmbedPage() {
  const p = new URLSearchParams(location.search);
  const roomId = p.get("room") || "";
  const token = p.get("token") || "";
  const url = p.get("url") || "";
  const name = p.get("name") || "Participante";
  const identity = p.get("identity") || undefined;
  const staff = p.get("staff") === "1";

  // Embed roda em outra origem (iframe), então não há cookie de sessão. Para as
  // chamadas REST de host (abrir quadro, gravar, encerrar) o backend precisa
  // identificar o usuário — enviamos a identidade via X-User-* (a mesma do token).
  const embedSdk = useMemo(
    () => createVideoRoomsSDK({
      apiBase, wsBase,
      headers: () => identity
        ? { "X-User-Id": identity, "X-User-Name": name, "X-User-Role": staff ? "admin" : "user" }
        : {},
    }),
    [identity, name, staff],
  );

  // Saguão (lobby): o embed do cliente OpenPBL também respeita o lobby. O host (staff)
  // entra direto; o aluno aguarda a admissão do host. "pending" enquanto carrega a info.
  const [info, setInfo] = useState<any | null>(null);
  const [phase, setPhase] = useState<"pending" | "lobby" | "room" | "denied">("pending");
  const lobbyIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!roomId) return;
    guestSdk.rooms.publicInfo(roomId).then((r) => {
      applyBranding(r.branding);
      setInfo(r);
      // Host entra direto; aluno vai ao saguão só se o lobby estiver ativo.
      setPhase(!staff && r.lobby_enabled ? "lobby" : "room");
    }).catch(() => { setInfo({}); setPhase("room"); });   // sem info → não bloqueia a entrada
  }, [roomId, staff]);

  // Aluno no saguão: entra na fila e aguarda a decisão do host.
  useEffect(() => {
    if (phase !== "lobby" || !roomId) return;
    embedSdk.lobby.join(roomId, name, "guest").then((res: any) => { lobbyIdRef.current = res.id; }).catch(() => {});
    return embedSdk.subscribe(roomId, (event, payload) => {
      if (event === "lobby-decision" && payload.lobby_id === lobbyIdRef.current)
        setPhase(payload.admit ? "room" : "denied");
    });
  }, [phase, roomId, embedSdk, name]);

  if (!roomId || !token) {
    return <div className="app-shell app-center"><div className="app-card app-gate"><div className="app-logo app-logo-lg">V</div><p className="app-sub">Parâmetros de embed ausentes (room, token).</p></div></div>;
  }
  if (phase === "pending") {
    return <div className="app-shell app-center"><div className="app-card app-gate"><div className="app-logo app-logo-lg">V</div><p className="app-sub">Carregando…</p></div></div>;
  }
  if (phase === "lobby" || phase === "denied") {
    return (
      <LobbyWaiting
        roomTitle={info?.title}
        timerTitle={info?.lobby_timer_title}
        timerSeconds={info?.lobby_timer_seconds}
        startedAt={info?.created_at}
        bgVideo={info?.lobby_bg_video}
        denied={phase === "denied"}
        onTimerEnd={() => { if (info?.lobby_auto_admit) setPhase("room"); }}
      />
    );
  }
  return (
    <SDKContext.Provider value={embedSdk}>
      <VideoRoom roomId={roomId} displayName={name} isStaff={staff}
        presetToken={token} presetLivekitUrl={url} presetIdentity={identity} />
    </SDKContext.Provider>
  );
}

function GuestPage() {
  const { token } = useParams();
  const [room, setRoom] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phase, setPhase] = useState<"name" | "lobby" | "room" | "denied">("name");
  const lobbyIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!token) return;
    guestSdk.rooms.byGuestToken(token).then((r) => { setRoom(r); applyBranding((r as any).branding); }).catch(() => setError("Convite inválido ou sala encerrada."));
  }, [token]);

  // Lobby: join the waiting room and wait for the host's decision.
  useEffect(() => {
    if (phase !== "lobby" || !room) return;
    guestSdk.lobby.join(room.id, name.trim(), "guest").then((res: any) => { lobbyIdRef.current = res.id; }).catch(() => {});
    return guestSdk.subscribe(room.id, (event, payload) => {
      if (event === "lobby-decision" && payload.lobby_id === lobbyIdRef.current) {
        setPhase(payload.admit ? "room" : "denied");
      }
      if (event === "room-ended") setError("A sala foi encerrada.");
    });
  }, [phase, room]);

  if (error)
    return <div className="app-shell app-center"><div className="app-card app-gate"><div className="app-logo app-logo-lg">V</div><p className="app-sub">{error}</p></div></div>;

  if (!room)
    return <div className="app-shell app-center"><div className="app-card app-gate"><div className="app-logo app-logo-lg">V</div><p className="app-sub">Carregando convite…</p></div></div>;

  if (phase === "name") {
    return (
      <div className="app-shell app-center">
        <div className="app-card app-gate">
          {room.branding?.logo_url
            ? <img className="app-logo app-logo-lg app-logo-img" src={room.branding.logo_url} alt="" />
            : <div className="app-logo app-logo-lg">V</div>}
          <h1>{room.title}</h1>
          <p className="app-sub">Você foi convidado{room.tenant_name ? ` por ${room.tenant_name}` : ""} para esta sala.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              if (room.require_email && !/.+@.+\..+/.test(email.trim())) return;
              setPhase(room.lobby_enabled ? "lobby" : "room");
            }}
          >
            <input className="app-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Seu nome" autoFocus />
            {room.require_email && (
              <input className="app-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Seu e-mail" required />
            )}
            <button className="app-btn">{room.lobby_enabled ? "Entrar no saguão" : "Entrar na sala"}</button>
          </form>
        </div>
      </div>
    );
  }

  if (phase === "lobby" || phase === "denied") {
    return (
      <LobbyWaiting
        roomTitle={room.title}
        timerTitle={room.lobby_timer_title}
        timerSeconds={room.lobby_timer_seconds}
        startedAt={room.created_at}
        bgVideo={room.lobby_bg_video}
        denied={phase === "denied"}
        onTimerEnd={() => { if (room.lobby_auto_admit) setPhase("room"); }}
      />
    );
  }

  return (
    <SDKContext.Provider value={guestSdk}>
      <VideoRoom roomId={room.id} guestToken={token} displayName={name.trim()} learnerEmail={email.trim() || undefined} onLeft={() => setPhase("name")} />
    </SDKContext.Provider>
  );
}

// ── O CHUNK QUE SUMIU DEPOIS DE UM DEPLOY ───────────────────────────────────
//
// Todas as telas acima entram por `import()`, e o nome do arquivo carrega o hash
// do conteúdo. Um deploy publica nomes novos e apaga os antigos — então o
// navegador que guardou o `index.html` de ontem pede um arquivo que não existe
// mais. O servidor responde o `index.html` no lugar (é o fallback de SPA do
// Caddy), o `import()` recebe HTML onde esperava um módulo, e o React não
// desenha nada. Como o `body` tem fundo escuro, o resultado é uma TELA PRETA —
// sem erro na tela, sem nada no log do servidor, que respondeu 200.
//
// Aconteceu em 06/11/2026: quem abriu `/admin` com a aba de antes do deploy em
// cache via preto, e quem recarregou via a tela de login.
//
// Duas defesas, e as duas são necessárias:
//
//   · o Caddy passou a servir `/assets/*` SEM o fallback (arquivo que não
//     existe vira 404, e não um HTML disfarçado de módulo) e a marcar o HTML
//     como `no-cache`, que é o que impede o índice velho de sobreviver ao
//     deploy — ver `infra/deploy/app/Caddyfile`;
//   · e aqui, a recarga: quem já estava com a página ABERTA durante o deploy
//     continua com o índice velho na memória, e nenhum cabeçalho alcança isso.
//
// UMA recarga só. Se o módulo continuar faltando depois dela, o problema não é
// cache, e insistir seria um laço infinito — aí a tela passa a dizer o que
// houve, que é melhor que preto.
const MARCA_DE_RECARGA = "chunk-recarregado";

function podeRecarregar(): boolean {
  try {
    if (sessionStorage.getItem(MARCA_DE_RECARGA)) return false;
    sessionStorage.setItem(MARCA_DE_RECARGA, "1");
    return true;
  } catch {
    // Sem `sessionStorage` (aba anônima com armazenamento bloqueado) não há
    // como lembrar que já tentamos, e recarregar viraria laço. Mostra o aviso.
    return false;
  }
}

/** A tela de falha, escrita direto no DOM.
 *
 *  No DOM e não em React de propósito: ela precisa funcionar justamente quando
 *  o React não está de pé — é o caso de um módulo que não carregou e o de um
 *  erro no meio da montagem. `detalhe` é a mensagem do erro, e ela aparece na
 *  TELA: quem vê o problema costuma ser quem não tem como abrir o console, e
 *  uma foto da tela precisa bastar para diagnosticar. */
function mostrarFalha(titulo: string, explicacao: string, detalhe = "") {
  const raiz = document.getElementById("root");
  if (!raiz) return;
  raiz.innerHTML = `
    <div style="min-height:100%;display:grid;place-items:center;padding:24px;
                font-family:Inter,system-ui,sans-serif;color:#e7e9ee;text-align:center">
      <div style="max-width:460px;display:grid;gap:12px">
        <div style="font-size:17px;font-weight:600">${titulo}</div>
        <div style="font-size:14px;line-height:1.5;color:#a8aeba">${explicacao}</div>
        ${detalhe ? `<code style="font-size:12px;color:#8a909a;background:#16181f;
          border-radius:8px;padding:8px 10px;word-break:break-word">${detalhe}</code>` : ""}
        <button id="recarregar" style="justify-self:center;background:#e11d2a;color:#fff;
                border:none;border-radius:9px;padding:10px 18px;font-weight:600;cursor:pointer">
          Recarregar
        </button>
      </div>
    </div>`;
  raiz.querySelector("#recarregar")?.addEventListener("click", () => {
    try { sessionStorage.removeItem(MARCA_DE_RECARGA); } catch { /* sem storage */ }
    window.location.reload();
  });
}

function avisarQueFaltaRecarregar() {
  mostrarFalha(
    "Esta página está desatualizada",
    "O sistema foi atualizado enquanto esta aba estava aberta. Recarregue " +
    "segurando <strong>Ctrl</strong> (ou <strong>⌘</strong>) para buscar a versão nova.");
}

// ── QUALQUER OUTRA FALHA TAMBÉM PRECISA APARECER ────────────────────────────
//
// O `vite:preloadError` acima cobre o módulo que não CARREGA. Mas um erro ao
// MONTAR a tela (uma exceção no meio da renderização, uma API do navegador que
// este navegador não tem, um bloqueio de armazenamento) produz exatamente o
// mesmo sintoma — React desmonta a árvore, `#root` fica vazio, e o fundo
// escuro do `body` entrega uma TELA PRETA sem uma palavra.
//
// Em 06/11/2026 isso custou caro: a tela preta de um usuário não dava para
// diagnosticar daqui, porque a única fonte era o console DELE. Com a mensagem
// na tela, uma foto basta.
//
// `#root` VAZIO é a guarda: um erro assíncrono qualquer, com o app já
// desenhado, não pode apagar a tela de quem está usando o sistema.
function raizVazia(): boolean {
  const raiz = document.getElementById("root");
  return !!raiz && raiz.childElementCount === 0;
}

function relatarSeTelaVazia(detalhe: string) {
  if (!raizVazia()) return;
  mostrarFalha(
    "Esta página não conseguiu carregar",
    "Recarregue segurando <strong>Ctrl</strong> (ou <strong>⌘</strong>). Se continuar " +
    "assim, envie esta tela para o suporte — a linha abaixo diz o que falhou.",
    detalhe.slice(0, 300));
}

window.addEventListener("error", (e) => relatarSeTelaVazia(
  String(e.message || (e.error && e.error.message) || e.error || "")));
window.addEventListener("unhandledrejection", (e) => relatarSeTelaVazia(
  String((e as PromiseRejectionEvent).reason ?? "")));

/** O mesmo, para o que acontece DENTRO do React.
 *
 *  Sem esta barreira, uma exceção em qualquer tela desmonta a árvore inteira e
 *  não sobra nada na página — o React faz isso de propósito desde a 16, para
 *  não deixar uma interface meio desenhada no ar. O preço é que, sem barreira,
 *  "meio desenhada" vira "nada", e nada é indistinguível de um site fora do ar. */
class BarreiraDeErro extends React.Component<
  { children: React.ReactNode }, { erro: string }
> {
  state = { erro: "" };

  static getDerivedStateFromError(erro: any) {
    return { erro: String(erro?.message || erro || "erro desconhecido") };
  }

  render() {
    if (!this.state.erro) return this.props.children;
    return (
      <div style={{ minHeight: "100%", display: "grid", placeItems: "center", padding: 24,
                    color: "#e7e9ee", textAlign: "center" }}>
        <div style={{ maxWidth: 460, display: "grid", gap: 12 }}>
          <div style={{ fontSize: 17, fontWeight: 600 }}>Esta tela falhou ao abrir</div>
          <div style={{ fontSize: 14, lineHeight: 1.5, color: "#a8aeba" }}>
            O resto do sistema continua funcionando. Recarregue a página; se o erro
            voltar, envie esta tela para o suporte.
          </div>
          <code style={{ fontSize: 12, color: "#8a909a", background: "#16181f",
                         borderRadius: 8, padding: "8px 10px", wordBreak: "break-word" }}>
            {this.state.erro.slice(0, 300)}
          </code>
          <button className="ad-btn" style={{ justifySelf: "center" }}
            onClick={() => window.location.reload()}>Recarregar</button>
        </div>
      </div>
    );
  }
}

window.addEventListener("vite:preloadError" as any, (e: Event) => {
  // `preventDefault` impede o Vite de relançar o erro: quem trata somos nós.
  e.preventDefault();
  if (podeRecarregar()) window.location.reload();
  else avisarQueFaltaRecarregar();
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <BarreiraDeErro>
  <SDKContext.Provider value={sdk}>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Suspense fallback={null}><Landing /></Suspense>} />
        <Route path="/app" element={<Home />} />
        <Route path="/portal" element={<Suspense fallback={null}><ClientApp /></Suspense>} />
        <Route path="/r/:id" element={<RoomPage />} />
        <Route path="/guest/:token" element={<GuestPage />} />
        <Route path="/recording-view" element={<Suspense fallback={null}><RecordingView /></Suspense>} />
        <Route path="/admin" element={<Suspense fallback={null}><AdminApp /></Suspense>} />
        <Route path="/embed" element={<EmbedPage />} />
        <Route path="/documentation" element={<Suspense fallback={null}><Documentation /></Suspense>} />
      </Routes>
    </BrowserRouter>
  </SDKContext.Provider>
  </BarreiraDeErro>,
);

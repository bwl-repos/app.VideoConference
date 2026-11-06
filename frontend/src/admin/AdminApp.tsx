import { useEffect, useRef, useState } from "react";
import { adminApi } from "./adminApi";
import EncontroPage from "./EncontroPage";
import "../styles/admin.css";

type View = "dashboard" | "monitoring" | "servers" | "finance" | "rooms" | "licenses" | "license" | "plans" | "encontro";

export default function AdminApp() {
  const [me, setMe] = useState<any>(null);
  const [booting, setBooting] = useState(true);

  useEffect(() => {
    adminApi("/me").then(setMe).catch(() => {}).finally(() => setBooting(false));
  }, []);

  const logout = async () => { await adminApi("/logout", { method: "POST" }).catch(() => {}); setMe(null); };

  if (booting) return <div className="ad-shell ad-center">Carregando…</div>;
  if (!me) return <Login onLogin={setMe} />;
  return <Panel me={me} onLogout={logout} />;
}

/* ---------------- Login ---------------- */
function Login({ onLogin }: { onLogin: (me: any) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      const r = await adminApi<{ admin: any }>("/login", { method: "POST", body: JSON.stringify({ email, password }) });
      onLogin(r.admin);
    } catch {
      setErr("Credenciais inválidas.");
    } finally { setBusy(false); }
  };

  return (
    <div className="ad-shell ad-center">
      <form className="ad-login" onSubmit={submit}>
        <div className="ad-logo">V</div>
        <h1>Painel Administrativo</h1>
        <p className="ad-muted">Acesso restrito.</p>
        <input className="ad-input" type="email" placeholder="E-mail" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        <input className="ad-input" type="password" placeholder="Senha" value={password} onChange={(e) => setPassword(e.target.value)} />
        {err && <div className="ad-err">{err}</div>}
        <button className="ad-btn" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
      </form>
    </div>
  );
}

/* ---------------- Panel shell ---------------- */
function Panel({ me, onLogout }: { me: any; onLogout: () => void }) {
  const [view, setView] = useState<View>("dashboard");
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);

  const open = (id: string) => { setTenantId(id); setView("license"); };

  return (
    <div className="ad-shell">
      <header className="ad-top">
        <div className="ad-brand"><div className="ad-logo sm">V</div> Admin · Video Rooms</div>
        <div className="ad-top-right">
          <span className="ad-muted">{me.email} · {me.role}</span>
          <button className="ad-link" onClick={() => setShowPw(true)}>Trocar senha</button>
          <button className="ad-link" onClick={onLogout}>Sair</button>
        </div>
      </header>
      <div className="ad-body">
        <nav className="ad-nav">
          <button data-active={view === "dashboard"} onClick={() => setView("dashboard")}>Visão geral</button>
          <button data-active={view === "monitoring"} onClick={() => setView("monitoring")}>Monitoramento</button>
          <button data-active={view === "servers"} onClick={() => setView("servers")}>Servidores</button>
          <button data-active={view === "finance"} onClick={() => setView("finance")}>Financeiro</button>
          <button data-active={view === "rooms"} onClick={() => setView("rooms")}>Salas</button>
          <button data-active={view === "licenses" || view === "license"} onClick={() => setView("licenses")}>Licenças</button>
          <button data-active={view === "plans"} onClick={() => setView("plans")}>Planos</button>
          <button data-active={view === "encontro"} onClick={() => setView("encontro")}>Encontro</button>
        </nav>
        <main className="ad-content">
          {view === "dashboard" && <Dashboard />}
          {view === "monitoring" && <Monitoring />}
          {view === "servers" && <Servers />}
          {view === "finance" && <Finance />}
          {view === "rooms" && <Rooms />}
          {view === "licenses" && <Licenses onOpen={open} />}
          {view === "license" && tenantId && <LicenseDetail id={tenantId} onBack={() => setView("licenses")} />}
          {view === "plans" && <Plans />}
          {view === "encontro" && <EncontroPage />}
        </main>
      </div>
      {showPw && <ChangePassword onClose={() => setShowPw(false)} />}
    </div>
  );
}

/* ---------------- Dashboard ---------------- */
function Dashboard() {
  const [s, setS] = useState<any>(null);
  const [ts, setTs] = useState<any[]>([]);
  const [tenants, setTenants] = useState<any[]>([]);
  useEffect(() => {
    const stats = () => adminApi("/stats").then(setS).catch(() => {});
    const series = () => adminApi<any[]>("/stats/timeseries?days=14").then(setTs).catch(() => {});
    const tens = () => adminApi<any[]>("/tenants").then(setTenants).catch(() => {});
    stats(); series(); tens();
    const a = setInterval(stats, 5000);
    const b = setInterval(() => { series(); tens(); }, 30000);
    return () => { clearInterval(a); clearInterval(b); };
  }, []);
  if (!s) return <div className="ad-muted">Carregando…</div>;
  const dd = (iso: string) => iso.slice(8, 10) + "/" + iso.slice(5, 7);
  const topTen = [...tenants].sort((x, y) => y.stats.rooms_total - x.stats.rooms_total).slice(0, 6);
  const maxRooms = Math.max(1, ...topTen.map((t) => t.stats.rooms_total));

  return (
    <>
      <div className="ad-head-row"><h2 className="ad-h2">Visão geral</h2><span className="ad-live">ao vivo</span></div>
      <div className="ad-cards">
        <div className="ad-card ad-card-live"><div className="ad-card-v">{s.live_participants}</div><div className="ad-card-l">Participantes ao vivo</div></div>
        <div className="ad-card ad-card-live"><div className="ad-card-v">{s.live_rooms}</div><div className="ad-card-l">Salas ao vivo</div></div>
        <div className="ad-card"><div className="ad-card-v">{s.tenants}</div><div className="ad-card-l">Licenças</div></div>
        <div className="ad-card"><div className="ad-card-v">{s.rooms_active}</div><div className="ad-card-l">Salas ativas</div></div>
        <div className="ad-card"><div className="ad-card-v">{s.rooms_total}</div><div className="ad-card-l">Salas (total)</div></div>
        <div className="ad-card"><div className="ad-card-v">{s.recordings}</div><div className="ad-card-l">Gravações</div></div>
      </div>

      <div className="ad-charts">
        <div className="ad-panel"><h3 className="ad-h3">Salas por dia · 14 dias</h3><Bars data={ts.map((d) => ({ x: dd(d.day), v: d.rooms }))} /></div>
        <div className="ad-panel"><h3 className="ad-h3">Participantes por dia · 14 dias</h3><Line data={ts.map((d) => ({ x: dd(d.day), v: d.participants }))} /></div>
      </div>

      <div className="ad-charts">
        <div className="ad-panel">
          <h3 className="ad-h3">Salas por licença</h3>
          {topTen.length === 0 ? <div className="ad-muted">Sem dados.</div> : topTen.map((t) => (
            <div className="ad-hbar" key={t.id}>
              <span className="ad-hbar-l">{t.name}</span>
              <div className="ad-hbar-track"><div className="ad-hbar-fill" style={{ width: `${(t.stats.rooms_total / maxRooms) * 100}%` }} /></div>
              <span className="ad-hbar-v">{t.stats.rooms_total}</span>
            </div>
          ))}
        </div>
        <div className="ad-panel ad-panel-console">
          <div className="ad-head-row" style={{ marginBottom: 8 }}><h3 className="ad-h3" style={{ margin: 0 }}>Console · tempo real</h3><span className="ad-live">live</span></div>
          <LogConsole />
        </div>
      </div>
    </>
  );
}

function Bars({ data }: { data: { x: string; v: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.v));
  return (
    <div className="ad-bars">
      {data.map((d, i) => (
        <div className="ad-bar-col" key={i} title={`${d.x}: ${d.v}`}>
          <div className="ad-bar" style={{ height: `${(d.v / max) * 100}%` }} />
          <span className="ad-bar-x">{d.x.slice(0, 2)}</span>
        </div>
      ))}
    </div>
  );
}

function Line({ data }: { data: { x: string; v: number }[] }) {
  const W = 300, H = 90, n = data.length;
  const max = Math.max(1, ...data.map((d) => d.v));
  const pts = data.map((d, i) => [(i / (n - 1 || 1)) * W, H - (d.v / max) * (H - 6) - 3]);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ad-svg" preserveAspectRatio="none">
      {data.length > 0 && <>
        <path d={`${path} L${W} ${H} L0 ${H} Z`} className="ad-area" />
        <path d={path} className="ad-linep" vectorEffect="non-scaling-stroke" />
      </>}
    </svg>
  );
}

function LogConsole() {
  const [lines, setLines] = useState<any[]>([]);
  const last = useRef(0);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const poll = () => adminApi(`/logs?after=${last.current}`).then((r: any) => {
      if (r.logs?.length) { last.current = r.last; setLines((p) => [...p, ...r.logs].slice(-250)); }
    }).catch(() => {});
    poll();
    const id = setInterval(poll, 1500);
    return () => clearInterval(id);
  }, []);
  useEffect(() => { const b = box.current; if (b) b.scrollTop = b.scrollHeight; }, [lines]);
  return (
    <div className="ad-console" ref={box}>
      {lines.length === 0 && <div className="ad-con-empty">Aguardando requisições…</div>}
      {lines.map((l) => (
        <div className="ad-con-line" key={l.seq}>
          <span className="ad-con-t">{new Date(l.t * 1000).toLocaleTimeString("pt-BR")}</span>
          <span className="ad-con-m" data-m={l.method}>{l.method}</span>
          <span className="ad-con-s" data-s={Math.floor(l.status / 100)}>{l.status}</span>
          <span className="ad-con-p">{l.path}</span>
          <span className="ad-con-ms">{l.ms}ms</span>
        </div>
      ))}
    </div>
  );
}

/* ---------------- Monitoring ---------------- */
function pctClass(v: number) { return v >= 90 ? "crit" : v >= 70 ? "warn" : "ok"; }
function fmtUptime(s?: number) {
  if (!s) return "—";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
function Gauge({ label, pct }: { label: string; pct?: number | null }) {
  const v = pct ?? 0;
  return (
    <div className="ad-gauge">
      <div className="ad-gauge-top"><span>{label}</span><b>{pct == null ? "—" : v + "%"}</b></div>
      <div className="ad-gauge-track"><div className="ad-gauge-fill" data-l={pctClass(v)} style={{ width: `${v}%` }} /></div>
    </div>
  );
}
function Pill({ ok }: { ok?: boolean }) {
  return <span className="ad-pill" data-ok={!!ok}>{ok ? "online" : "offline"}</span>;
}

function Monitoring() {
  const [m, setM] = useState<any>(null);
  const [sys, setSys] = useState<any>(null);
  const [rooms, setRooms] = useState<any[]>([]);
  const [ts, setTs] = useState<any[]>([]);
  const [days, setDays] = useState(14);
  useEffect(() => {
    const lm = () => adminApi("/metrics").then(setM).catch(() => {});
    const ls = () => adminApi("/system").then(setSys).catch(() => {});
    const lr = () => adminApi<any[]>("/live-rooms").then(setRooms).catch(() => {});
    lm(); ls(); lr();
    const a = setInterval(lm, 3000), b = setInterval(ls, 5000), c = setInterval(lr, 4000);
    return () => { clearInterval(a); clearInterval(b); clearInterval(c); };
  }, []);
  useEffect(() => { adminApi<any[]>(`/stats/timeseries?days=${days}`).then(setTs).catch(() => {}); }, [days]);
  const dd = (iso: string) => iso.slice(8, 10) + "/" + iso.slice(5, 7);

  return (
    <>
      <div className="ad-head-row"><h2 className="ad-h2">Monitoramento</h2><span className="ad-live">ao vivo</span></div>

      <div className="ad-cards">
        <div className="ad-card"><div className="ad-card-v">{m ? m.rpm : "—"}</div><div className="ad-card-l">Requisições / min</div></div>
        <div className="ad-card"><div className="ad-card-v">{m ? m.avg_ms : "—"}<small>ms</small></div><div className="ad-card-l">Latência média</div></div>
        <div className="ad-card"><div className="ad-card-v">{m ? m.p95_ms : "—"}<small>ms</small></div><div className="ad-card-l">Latência p95</div></div>
        <div className="ad-card" data-bad={m && m.error_rate > 5}><div className="ad-card-v">{m ? m.error_rate : "—"}<small>%</small></div><div className="ad-card-l">Taxa de erro</div></div>
        <div className="ad-card ad-card-live"><div className="ad-card-v">{sys ? (sys.live_participants ?? 0) : "—"}</div><div className="ad-card-l">Participantes ao vivo</div></div>
      </div>

      <div className="ad-charts">
        <div className="ad-panel">
          <h3 className="ad-h3">Sistema · nó da aplicação</h3>
          <Gauge label="CPU" pct={sys?.cpu_pct} />
          <Gauge label="Memória" pct={sys?.mem_pct} />
          <Gauge label="Disco" pct={sys?.disk_pct} />
          <div className="ad-sys-meta">
            <span>Uptime <b>{fmtUptime(sys?.uptime_s)}</b></span>
            <span>Gravações <b>{sys ? `${sys.storage_mb} MB` : "—"}</b> ({sys?.storage_files ?? "—"})</span>
          </div>
          <div className="ad-sys-meta">
            <span>Banco <Pill ok={sys?.db} /></span>
            <span>LiveKit <Pill ok={sys?.livekit} /></span>
          </div>
        </div>
        <div className="ad-panel ad-panel-console">
          <div className="ad-head-row" style={{ marginBottom: 8 }}><h3 className="ad-h3" style={{ margin: 0 }}>Console · tempo real</h3><span className="ad-live">live</span></div>
          <LogConsole />
        </div>
      </div>

      <div className="ad-panel">
        <div className="ad-head-row">
          <h3 className="ad-h3">Tendência</h3>
          <div className="ad-range">{[7, 14, 30, 90].map((d) => <button key={d} data-active={days === d} onClick={() => setDays(d)}>{d}d</button>)}</div>
        </div>
        <div className="ad-charts" style={{ marginTop: 4 }}>
          <div><div className="ad-muted" style={{ fontSize: 12, marginBottom: 4 }}>Salas / dia</div><Bars data={ts.map((d) => ({ x: dd(d.day), v: d.rooms }))} /></div>
          <div><div className="ad-muted" style={{ fontSize: 12, marginBottom: 4 }}>Participantes / dia</div><Line data={ts.map((d) => ({ x: dd(d.day), v: d.participants }))} /></div>
        </div>
      </div>

      <div className="ad-charts">
        <div className="ad-panel">
          <h3 className="ad-h3">Salas ao vivo agora</h3>
          {rooms.length === 0 ? <div className="ad-muted">Nenhuma sala ativa no momento.</div> : (
            <table className="ad-table"><thead><tr><th>Sala</th><th>Licença</th><th>Participantes</th></tr></thead><tbody>
              {rooms.map((r) => <tr key={r.room}><td>{r.title}{r.recording ? " 🔴" : ""}</td><td className="ad-muted">{r.tenant || "—"}</td><td><span className="ad-live-pill">{r.participants}</span></td></tr>)}
            </tbody></table>
          )}
        </div>
        <div className="ad-panel">
          <h3 className="ad-h3">Top endpoints (5 min)</h3>
          {!m || m.top_endpoints.length === 0 ? <div className="ad-muted">Sem tráfego recente.</div> : (
            <table className="ad-table"><thead><tr><th>Endpoint</th><th>Reqs</th><th>Média</th><th>Erros</th></tr></thead><tbody>
              {m.top_endpoints.map((e: any) => <tr key={e.ep}><td><code style={{ fontSize: 11 }}>{e.ep}</code></td><td>{e.count}</td><td>{e.avg_ms}ms</td><td data-bad={e.errors > 0} style={e.errors ? { color: "#e11d2a", fontWeight: 700 } : {}}>{e.errors}</td></tr>)}
            </tbody></table>
          )}
        </div>
      </div>

      <div className="ad-panel">
        <h3 className="ad-h3">Erros recentes</h3>
        {!m || m.recent_errors.length === 0 ? <div className="ad-muted" style={{ color: "#16a34a" }}>Nenhum erro recente ✓</div> : (
          <div className="ad-console" style={{ maxHeight: 180 }}>
            {m.recent_errors.map((l: any) => (
              <div className="ad-con-line" key={l.seq}>
                <span className="ad-con-t">{new Date(l.t * 1000).toLocaleTimeString("pt-BR")}</span>
                <span className="ad-con-m" data-m={l.method}>{l.method}</span>
                <span className="ad-con-s" data-s={Math.floor(l.status / 100)}>{l.status}</span>
                <span className="ad-con-p">{l.path}</span>
                <span className="ad-con-ms">{l.ms}ms</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

/* ---------------- Rooms management ---------------- */
function Rooms() {
  const [rows, setRows] = useState<any[]>([]);
  const [tenants, setTenants] = useState<any[]>([]);
  const [tenant, setTenant] = useState("");
  const [status, setStatus] = useState("active");
  const [chatRoom, setChatRoom] = useState<any>(null);

  useEffect(() => { adminApi<any[]>("/tenants").then(setTenants).catch(() => {}); }, []);
  useEffect(() => {
    const load = () => adminApi<any[]>(`/rooms?status=${status}${tenant ? `&tenant=${tenant}` : ""}`).then(setRows).catch(() => {});
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [status, tenant]);

  const end = async (id: string) => {
    if (!confirm("Encerrar esta sessão para todos os participantes?")) return;
    await adminApi(`/rooms/${id}/end`, { method: "POST" }).catch(() => {});
    adminApi<any[]>(`/rooms?status=${status}${tenant ? `&tenant=${tenant}` : ""}`).then(setRows).catch(() => {});
  };

  return (
    <>
      <div className="ad-head-row"><h2 className="ad-h2">Salas</h2><span className="ad-live">ao vivo</span></div>
      <div className="ad-filters">
        <select className="ad-input" style={{ maxWidth: 220 }} value={tenant} onChange={(e) => setTenant(e.target.value)}>
          <option value="">Todos os clientes</option>
          {tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select className="ad-input" style={{ maxWidth: 160 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="active">Ativas</option>
          <option value="ended">Encerradas</option>
          <option value="all">Todas</option>
        </select>
      </div>
      <table className="ad-table">
        <thead><tr><th>Sala</th><th>Cliente</th><th>Participantes</th><th>Criada</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td><b>{r.title}</b>{r.recording ? " 🔴" : ""}</td>
              <td className="ad-muted">{r.tenant || "—"}</td>
              <td>{r.participants > 0 ? <span className="ad-live-pill">{r.participants}</span> : <span className="ad-muted">0</span>}</td>
              <td className="ad-muted">{new Date(r.created_at).toLocaleString("pt-BR")}</td>
              <td><span className="ad-badge" data-s={r.status === "active" ? "active" : "ended"}>{r.status === "active" ? "ativa" : "encerrada"}</span></td>
              <td style={{ whiteSpace: "nowrap" }}>
                <button className="ad-link" onClick={() => setChatRoom(r)}>Ver chat</button>
                {r.status === "active" && <button className="ad-link ad-danger" onClick={() => end(r.id)}>Encerrar</button>}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={6} className="ad-muted" style={{ padding: 18 }}>Nenhuma sala.</td></tr>}
        </tbody>
      </table>
      {chatRoom && <ChatModal room={chatRoom} onClose={() => setChatRoom(null)} />}
    </>
  );
}

function ChatModal({ room, onClose }: { room: any; onClose: () => void }) {
  const [msgs, setMsgs] = useState<any[] | null>(null);
  useEffect(() => { adminApi<any[]>(`/rooms/${room.id}/chat`).then(setMsgs).catch(() => setMsgs([])); }, [room.id]);
  return (
    <div className="ad-overlay" onClick={onClose}>
      <div className="ad-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ad-modal-head"><h3>Chat · {room.title}</h3><button className="ad-x" onClick={onClose}>×</button></div>
        <div className="ad-chatlog">
          {msgs === null && <div className="ad-muted">Carregando…</div>}
          {msgs && msgs.length === 0 && <div className="ad-muted">Sem mensagens nesta sala.</div>}
          {msgs && msgs.map((m, i) => (
            <div className="ad-chatmsg" key={i}>
              <span className="ad-chatmsg-h"><b>{m.sender}</b> <small>{new Date(m.at).toLocaleString("pt-BR")}</small></span>
              <span>{m.message}</span>
            </div>
          ))}
        </div>
        <div className="ad-modal-foot"><button className="ad-btn-outline" onClick={onClose}>Fechar</button></div>
      </div>
    </div>
  );
}

/* ---------------- Servers / infra ---------------- */
function Servers() {
  const [nodes, setNodes] = useState<any[]>([]);
  const [cons, setCons] = useState<any[]>([]);
  useEffect(() => {
    const ln = () => adminApi<any[]>("/nodes").then(setNodes).catch(() => {});
    const lc = () => adminApi<any[]>("/consumption").then(setCons).catch(() => {});
    ln(); lc();
    const a = setInterval(ln, 5000), b = setInterval(lc, 15000);
    return () => { clearInterval(a); clearInterval(b); };
  }, []);

  const alerts: { lvl: string; msg: string }[] = [];
  nodes.forEach((n) => {
    if (n.age_s > 120) alerts.push({ lvl: "crit", msg: `${n.name}: sem métricas há ${n.age_s}s (agente offline?)` });
    if (n.cpu >= 90) alerts.push({ lvl: "crit", msg: `${n.name}: CPU em ${n.cpu}%` });
    if (n.mem >= 90) alerts.push({ lvl: "warn", msg: `${n.name}: memória em ${n.mem}%` });
    if (n.disk >= 85) alerts.push({ lvl: "warn", msg: `${n.name}: disco em ${n.disk}%` });
  });
  const consSorted = [...cons].sort((a, b) => b.rooms_total - a.rooms_total);

  return (
    <>
      <div className="ad-head-row"><h2 className="ad-h2">Servidores & Consumo</h2><span className="ad-live">ao vivo</span></div>

      <div className="ad-panel">
        <h3 className="ad-h3">Alertas</h3>
        {alerts.length === 0 ? <div className="ad-muted" style={{ color: "#16a34a" }}>Nenhum alerta — tudo dentro dos limites ✓</div> : (
          <div className="ad-alerts">{alerts.map((a, i) => <div className="ad-alert" data-lvl={a.lvl} key={i}>{a.lvl === "crit" ? "🔴" : "🟠"} {a.msg}</div>)}</div>
        )}
      </div>

      <div className="ad-charts">
        {nodes.length === 0 && <div className="ad-muted">Aguardando agentes…</div>}
        {nodes.map((n) => (
          <div className="ad-panel" key={n.name}>
            <div className="ad-head-row" style={{ marginBottom: 8 }}>
              <h3 className="ad-h3" style={{ margin: 0 }}>{n.name}</h3>
              <span className="ad-badge">{n.role}</span>
            </div>
            <Gauge label="CPU" pct={n.cpu} />
            <Gauge label="Memória" pct={n.mem} />
            <Gauge label="Disco" pct={n.disk} />
            <div className="ad-sys-meta"><span>Visto há <b>{n.age_s}s</b> {n.age_s > 120 && <span className="ad-pill" data-ok="false">stale</span>}</span></div>
          </div>
        ))}
      </div>

      <div className="ad-panel">
        <h3 className="ad-h3">Consumo por cliente</h3>
        <table className="ad-table">
          <thead><tr><th>Cliente</th><th>Status</th><th>Salas</th><th>Participantes</th><th>Gravações</th><th>Storage</th><th>Ao vivo</th></tr></thead>
          <tbody>
            {consSorted.map((c) => (
              <tr key={c.id}>
                <td><b>{c.name}</b></td>
                <td><span className="ad-badge" data-s={c.status}>{c.status}</span></td>
                <td>{c.rooms_total}</td><td>{c.participants}</td><td>{c.recordings}</td>
                <td>{c.storage_mb} MB</td>
                <td>{c.live_participants > 0 ? <span className="ad-live-pill">{c.live_participants}</span> : <span className="ad-muted">—</span>}</td>
              </tr>
            ))}
            {cons.length === 0 && <tr><td colSpan={7} className="ad-muted" style={{ padding: 16 }}>Carregando…</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ---------------- Finance ---------------- */
function Finance() {
  const [f, setF] = useState<any>(null);
  useEffect(() => {
    const load = () => adminApi("/finance").then(setF).catch(() => {});
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, []);
  if (!f) return <div className="ad-muted">Carregando…</div>;
  const fx = f.usd_to_brl || 0;
  const usd = (v: number) => `$${(v ?? 0).toFixed(2)}`;
  const brl = (v: number) => `R$ ${((v ?? 0) * fx).toFixed(2).replace(".", ",")}`;
  const money = (v: number, l: string, hint?: string) => (
    <div className="ad-card">
      <div className="ad-card-v">{usd(v)}</div>
      <div className="ad-card-l">{l}</div>
      <div className="ad-muted" style={{ fontSize: 11, marginTop: 2 }}>{brl(v)}{hint ? ` · ${hint}` : ""}</div>
    </div>
  );
  const pctOfProj = f.projection_eom_usd ? Math.min(100, (f.month_to_date_usd / f.projection_eom_usd) * 100) : 0;

  return (
    <>
      <div className="ad-head-row"><h2 className="ad-h2">Financeiro</h2><span className="ad-live">ao vivo</span></div>
      <p className="ad-muted" style={{ marginTop: -6 }}>
        Custos de infraestrutura · {f.month?.label} · dia {f.month?.day}/{f.month?.days} · câmbio US$ 1 = R$ {fx}
      </p>

      <div className="ad-cards">
        {money(f.fixed_monthly_usd, "Servidores (fixo/mês)")}
        {money(f.storage.monthly_usd, "Storage (atual/mês)", `${f.storage.gb} GB`)}
        {money(f.total_monthly_usd, "Custo mensal (ritmo atual)")}
        {money(f.month_to_date_usd, "Mês até agora")}
        {money(f.projection_eom_usd, "Projeção fim do mês")}
      </div>

      <div className="ad-panel">
        <h3 className="ad-h3">Acúmulo do mês</h3>
        <div className="ad-hbar">
          <span className="ad-hbar-l">Gasto até agora</span>
          <div className="ad-hbar-track"><div className="ad-hbar-fill" style={{ width: `${pctOfProj}%` }} /></div>
          <span className="ad-hbar-v">{usd(f.month_to_date_usd)}</span>
        </div>
        <p className="ad-muted" style={{ marginTop: 6 }}>
          {pctOfProj.toFixed(0)}% da projeção de {usd(f.projection_eom_usd)} para o fim do mês.
        </p>
      </div>

      <div className="ad-panel">
        <h3 className="ad-h3">Servidores</h3>
        <table className="ad-table">
          <thead><tr><th>Servidor</th><th>Função</th><th>Specs</th><th>Plano</th><th>US$/mês</th></tr></thead>
          <tbody>
            {f.servers.map((s: any) => (
              <tr key={s.name}>
                <td><b>{s.name}</b></td><td>{s.role}</td><td className="ad-muted">{s.specs}</td>
                <td><code>{s.bundle}</code></td><td>{usd(s.monthly_usd)}</td>
              </tr>
            ))}
            <tr><td colSpan={4}><b>Total servidores</b></td><td><b>{usd(f.fixed_monthly_usd)}</b></td></tr>
            <tr><td colSpan={4} className="ad-muted">Storage S3 · {f.storage.gb} GB · {f.storage.files} arquivos · ${f.storage.rate_per_gb}/GB</td><td>{usd(f.storage.monthly_usd)}</td></tr>
            <tr><td colSpan={4}><b>Total geral / mês</b></td><td><b>{usd(f.total_monthly_usd)}</b></td></tr>
          </tbody>
        </table>
      </div>

      <div className="ad-panel">
        <h3 className="ad-h3">Custo por cliente (rateio)</h3>
        <p className="ad-muted" style={{ marginTop: -4 }}>Storage real do cliente + infra compartilhada proporcional ao uso (nº de salas).</p>
        <table className="ad-table">
          <thead><tr><th>Cliente</th><th>Uso</th><th>Storage</th><th>Storage US$</th><th>Infra US$</th><th>Total US$</th><th>Total R$</th></tr></thead>
          <tbody>
            {f.by_tenant.map((t: any) => (
              <tr key={t.id}>
                <td><b>{t.name}</b></td><td>{t.usage_pct}%</td><td>{t.storage_gb} GB</td>
                <td>{usd(t.storage_usd)}</td><td>{usd(t.infra_usd)}</td>
                <td><b>{usd(t.total_usd)}</b></td><td className="ad-muted">{brl(t.total_usd)}</td>
              </tr>
            ))}
            {f.by_tenant.length === 0 && <tr><td colSpan={7} className="ad-muted" style={{ padding: 16 }}>Sem clientes.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

/* ---------------- Licenses ---------------- */
function Licenses({ onOpen }: { onOpen: (id: string) => void }) {
  const [list, setList] = useState<any[]>([]);
  const [plans, setPlans] = useState<any[]>([]);
  const [creating, setCreating] = useState(false);
  const refresh = () => adminApi<any[]>("/tenants").then(setList).catch(() => {});
  useEffect(() => {
    refresh();
    adminApi<any[]>("/plans").then(setPlans).catch(() => {});
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      <div className="ad-head-row">
        <h2 className="ad-h2">Licenças</h2>
        <button className="ad-btn" onClick={() => setCreating(true)}>+ Nova licença</button>
      </div>
      <table className="ad-table">
        <thead><tr><th>Nome</th><th>Status</th><th>Plano</th><th>Ao vivo</th><th>Salas ativas</th><th>Salas</th><th>Gravações</th></tr></thead>
        <tbody>
          {list.map((t) => (
            <tr key={t.id} onClick={() => onOpen(t.id)} className="ad-row">
              <td><b>{t.name}</b><div className="ad-muted" style={{ fontSize: 12 }}>{t.slug}</div></td>
              <td><span className="ad-badge" data-s={t.status}>{t.status}</span></td>
              <td>{t.plan_name || "—"}</td>
              <td>{t.stats.live_participants > 0 ? <span className="ad-live-pill">{t.stats.live_participants} 👤</span> : <span className="ad-muted">—</span>}</td>
              <td>{t.stats.rooms_active}</td><td>{t.stats.rooms_total}</td><td>{t.stats.recordings}</td>
            </tr>
          ))}
          {list.length === 0 && <tr><td colSpan={7} className="ad-muted" style={{ padding: 20 }}>Nenhuma licença ainda.</td></tr>}
        </tbody>
      </table>
      {creating && <CreateLicense plans={plans} onClose={() => setCreating(false)} onCreated={() => { setCreating(false); refresh(); }} />}
    </>
  );
}

function CreateLicense({ plans, onClose, onCreated }: { plans: any[]; onClose: () => void; onCreated: () => void }) {
  const [f, setF] = useState({ name: "", slug: "", plan_id: "", max_rooms: "", max_participants: "" });
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      await adminApi("/tenants", { method: "POST", body: JSON.stringify({
        name: f.name, slug: f.slug || f.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        plan_id: f.plan_id || null,
        max_rooms: f.max_rooms ? parseInt(f.max_rooms) : null,
        max_participants: f.max_participants ? parseInt(f.max_participants) : null,
      }) });
      onCreated();
    } catch (e: any) { setErr(e.message || "erro"); }
  };
  return (
    <Modal title="Nova Licença" onClose={onClose} onSubmit={submit} submitLabel="Criar" err={err}>
      <L label="Nome"><input className="ad-input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></L>
      <L label="Slug (opcional)"><input className="ad-input" value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value })} placeholder="auto a partir do nome" /></L>
      <L label="Plano"><select className="ad-input" value={f.plan_id} onChange={(e) => setF({ ...f, plan_id: e.target.value })}>
        <option value="">— sem plano —</option>
        {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></L>
      <div className="ad-grid2">
        <L label="Máx. salas (override)"><input className="ad-input" type="number" value={f.max_rooms} onChange={(e) => setF({ ...f, max_rooms: e.target.value })} placeholder="herda do plano" /></L>
        <L label="Máx. participantes (override)"><input className="ad-input" type="number" value={f.max_participants} onChange={(e) => setF({ ...f, max_participants: e.target.value })} placeholder="herda do plano" /></L>
      </div>
    </Modal>
  );
}

/* ---------------- License detail ---------------- */
function LicenseDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [t, setT] = useState<any>(null);
  const [liveStats, setLiveStats] = useState<any>(null);
  const [plans, setPlans] = useState<any[]>([]);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [acct, setAcct] = useState({ name: "", email: "" });
  const [acctResult, setAcctResult] = useState<{ email: string; temp_password: string } | null>(null);
  const [acctErr, setAcctErr] = useState<string | null>(null);
  const refresh = () => adminApi(`/tenants/${id}`).then(setT).catch(() => {});
  useEffect(() => {
    refresh();
    adminApi<any[]>("/plans").then(setPlans).catch(() => {});
    // poll only the stats so we don't clobber the edit form
    const poll = () => adminApi(`/tenants/${id}`).then((r: any) => setLiveStats(r.stats)).catch(() => {});
    const iv = setInterval(poll, 5000);
    return () => clearInterval(iv);
  }, [id]);
  if (!t) return <div className="ad-muted">Carregando…</div>;
  const st = liveStats ?? t.stats;

  const save = async (patch: any) => {
    await adminApi(`/tenants/${id}`, { method: "PUT", body: JSON.stringify({
      name: t.name, slug: t.slug, plan_id: t.plan_id, status: t.status,
      max_rooms: t.overrides.max_rooms, max_participants: t.overrides.max_participants,
      recording_enabled: t.overrides.recording_enabled, storage_quota_gb: t.overrides.storage_quota_gb,
      branding: t.branding || {},
      ...patch,
    }) });
    refresh();
  };
  const setBrand = (k: string, v: string) => setT({ ...t, branding: { ...(t.branding || {}), [k]: v } });
  const delTenant = async () => {
    if (!confirm("Excluir esta licença? (só é possível se não houver salas)")) return;
    try { await adminApi(`/tenants/${id}`, { method: "DELETE" }); onBack(); }
    catch (e: any) { alert(e.message || "erro"); }
  };
  const genKey = async () => {
    const r = await adminApi<{ api_key: string }>(`/tenants/${id}/keys`, { method: "POST", body: JSON.stringify({ name: "key" }) });
    setNewKey(r.api_key);
    refresh();
  };
  const revoke = async (kid: string) => { if (confirm("Revogar esta API key?")) { await adminApi(`/keys/${kid}`, { method: "DELETE" }); refresh(); } };
  const createAcct = async () => {
    setAcctErr(null);
    if (!acct.email.trim() || !acct.name.trim()) { setAcctErr("Preencha nome e e-mail."); return; }
    try {
      const r = await adminApi<{ email: string; temp_password: string }>(`/tenants/${id}/client`, { method: "POST", body: JSON.stringify(acct) });
      setAcctResult(r); setAcct({ name: "", email: "" });
    } catch (e: any) { setAcctErr(e.message || "erro"); }
  };

  return (
    <>
      <button className="ad-link" onClick={onBack}>← Licenças</button>
      <div className="ad-head-row">
        <h2 className="ad-h2">{t.name} <span className="ad-badge" data-s={t.status}>{t.status}</span></h2>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button className="ad-btn-outline" onClick={() => save({ status: t.status === "active" ? "suspended" : "active" })}>
            {t.status === "active" ? "Suspender" : "Ativar"}
          </button>
          <button className="ad-link ad-danger" onClick={delTenant}>Excluir</button>
        </div>
      </div>

      <div className="ad-cards">
        <div className="ad-card ad-card-live"><div className="ad-card-v">{st.live_participants}</div><div className="ad-card-l">Participantes ao vivo</div></div>
        <div className="ad-card ad-card-live"><div className="ad-card-v">{st.live_rooms}</div><div className="ad-card-l">Salas ao vivo</div></div>
        <Stat v={st.rooms_active} l="Salas ativas" /><Stat v={st.rooms_total} l="Salas (total)" />
        <Stat v={st.recordings} l="Gravações" /><Stat v={st.participants} l="Participantes (hist.)" />
      </div>

      <h3 className="ad-h3">Limites efetivos</h3>
      <p className="ad-muted">Máx. salas: <b>{eff(t.effective.max_rooms)}</b> · Máx. participantes: <b>{t.effective.max_participants}</b> · Gravação: <b>{t.effective.recording_enabled ? "sim" : "não"}</b> · Storage: <b>{t.effective.storage_quota_gb} GB</b></p>

      <div className="ad-panel">
        <h3 className="ad-h3">Plano & overrides</h3>
        <div className="ad-grid2">
          <L label="Plano"><select className="ad-input" value={t.plan_id || ""} onChange={(e) => setT({ ...t, plan_id: e.target.value || null })}>
            <option value="">— sem plano —</option>
            {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select></L>
          <L label="Máx. salas (override)"><input className="ad-input" type="number" value={t.overrides.max_rooms ?? ""} onChange={(e) => setT({ ...t, overrides: { ...t.overrides, max_rooms: e.target.value ? parseInt(e.target.value) : null } })} /></L>
          <L label="Máx. participantes (override)"><input className="ad-input" type="number" value={t.overrides.max_participants ?? ""} onChange={(e) => setT({ ...t, overrides: { ...t.overrides, max_participants: e.target.value ? parseInt(e.target.value) : null } })} /></L>
          <L label="Storage GB (override)"><input className="ad-input" type="number" value={t.overrides.storage_quota_gb ?? ""} onChange={(e) => setT({ ...t, overrides: { ...t.overrides, storage_quota_gb: e.target.value ? parseInt(e.target.value) : null } })} /></L>
        </div>
        <button className="ad-btn" onClick={() => save({})}>Salvar alterações</button>
      </div>

      <div className="ad-panel">
        <h3 className="ad-h3">Branding (white-label)</h3>
        <p className="ad-muted" style={{ marginTop: -4 }}>O cliente e os convidados dele veem esta marca (cor, nome e logo).</p>
        <div className="ad-grid2">
          <L label="Nome do produto"><input className="ad-input" value={t.branding?.product_name || ""} onChange={(e) => setBrand("product_name", e.target.value)} placeholder="Ex.: OpenPBL Meet" /></L>
          <L label="Cor de destaque"><input className="ad-input" type="color" value={t.branding?.accent_color || "#6366f1"} onChange={(e) => setBrand("accent_color", e.target.value)} style={{ height: 42, padding: 4 }} /></L>
        </div>
        <L label="URL do logo (PNG/SVG)"><input className="ad-input" value={t.branding?.logo_url || ""} onChange={(e) => setBrand("logo_url", e.target.value)} placeholder="https://..." /></L>
        <button className="ad-btn" onClick={() => save({})}>Salvar branding</button>
      </div>

      <div className="ad-panel">
        <div className="ad-head-row"><h3 className="ad-h3">API Keys</h3><button className="ad-btn" onClick={genKey}>+ Gerar key</button></div>
        {newKey && (
          <div className="ad-keybox">
            <div className="ad-muted">Copie agora — esta key não será mostrada de novo:</div>
            <code className="ad-key">{newKey}</code>
            <button className="ad-btn-outline" onClick={() => { navigator.clipboard?.writeText(newKey); }}>Copiar</button>
          </div>
        )}
        <table className="ad-table">
          <thead><tr><th>Prefixo</th><th>Nome</th><th>Último uso</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {t.api_keys.map((k: any) => (
              <tr key={k.id}>
                <td><code>{k.key_prefix}…</code></td><td>{k.name || "—"}</td>
                <td className="ad-muted">{k.last_used_at ? new Date(k.last_used_at).toLocaleString("pt-BR") : "nunca"}</td>
                <td>{k.revoked_at ? <span className="ad-badge" data-s="suspended">revogada</span> : <span className="ad-badge" data-s="active">ativa</span>}</td>
                <td>{!k.revoked_at && <button className="ad-link ad-danger" onClick={() => revoke(k.id)}>revogar</button>}</td>
              </tr>
            ))}
            {t.api_keys.length === 0 && <tr><td colSpan={5} className="ad-muted" style={{ padding: 14 }}>Nenhuma key. Gere uma para o cliente integrar.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="ad-panel">
        <h3 className="ad-h3">Acesso ao portal do cliente</h3>
        <p className="ad-muted" style={{ marginTop: -4 }}>Crie um login para o responsável desta licença acessar o portal em <code>/portal</code> (ver limites, uso, API keys e marca).</p>
        {acctResult && (
          <div className="ad-keybox">
            <div className="ad-muted">Conta criada. Envie estas credenciais ao cliente (a senha não será mostrada de novo):</div>
            <code className="ad-key">{acctResult.email} · {acctResult.temp_password}</code>
            <button className="ad-btn-outline" onClick={() => navigator.clipboard?.writeText(`E-mail: ${acctResult.email}\nSenha: ${acctResult.temp_password}`)}>Copiar</button>
          </div>
        )}
        <div className="ad-grid2">
          <L label="Nome do responsável"><input className="ad-input" value={acct.name} onChange={(e) => setAcct({ ...acct, name: e.target.value })} placeholder="Ex.: Maria Silva" /></L>
          <L label="E-mail de acesso"><input className="ad-input" type="email" value={acct.email} onChange={(e) => setAcct({ ...acct, email: e.target.value })} placeholder="maria@cliente.com" /></L>
        </div>
        {acctErr && <div className="ad-err">{acctErr}</div>}
        <button className="ad-btn" onClick={createAcct}>Criar acesso</button>
      </div>
    </>
  );
}

/* ---------------- Plans ---------------- */
function Plans() {
  const [list, setList] = useState<any[]>([]);
  const [creating, setCreating] = useState(false);
  const refresh = () => adminApi<any[]>("/plans").then(setList).catch(() => {});
  useEffect(() => { refresh(); }, []);
  const delPlan = async (id: string) => {
    if (!confirm("Excluir este plano? (só é possível se nenhuma licença o usa)")) return;
    try { await adminApi(`/plans/${id}`, { method: "DELETE" }); refresh(); }
    catch (e: any) { alert(e.message || "erro"); }
  };
  return (
    <>
      <div className="ad-head-row"><h2 className="ad-h2">Planos</h2><button className="ad-btn" onClick={() => setCreating(true)}>+ Novo plano</button></div>
      <table className="ad-table">
        <thead><tr><th>Nome</th><th>Slug</th><th>Máx. salas</th><th>Máx. part.</th><th>Gravação</th><th>Storage</th><th>Preço</th><th></th></tr></thead>
        <tbody>
          {list.map((p) => (
            <tr key={p.id}><td><b>{p.name}</b></td><td className="ad-muted">{p.slug}</td><td>{eff(p.max_rooms)}</td><td>{p.max_participants}</td><td>{p.recording_enabled ? "sim" : "não"}</td><td>{p.storage_quota_gb} GB</td><td>{(p.price_cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}</td><td><button className="ad-link ad-danger" onClick={() => delPlan(p.id)}>excluir</button></td></tr>
          ))}
        </tbody>
      </table>
      {creating && <CreatePlan onClose={() => setCreating(false)} onCreated={() => { setCreating(false); refresh(); }} />}
    </>
  );
}

function CreatePlan({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [f, setF] = useState({ name: "", slug: "", max_rooms: "-1", max_participants: "50", recording_enabled: true, storage_quota_gb: "50", price: "0" });
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      await adminApi("/plans", { method: "POST", body: JSON.stringify({
        name: f.name, slug: f.slug || f.name.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
        max_rooms: parseInt(f.max_rooms), max_participants: parseInt(f.max_participants),
        recording_enabled: f.recording_enabled, storage_quota_gb: parseInt(f.storage_quota_gb),
        price_cents: Math.round(parseFloat(f.price || "0") * 100),
      }) });
      onCreated();
    } catch (e: any) { setErr(e.message || "erro"); }
  };
  return (
    <Modal title="Novo Plano" onClose={onClose} onSubmit={submit} submitLabel="Criar" err={err}>
      <L label="Nome"><input className="ad-input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></L>
      <div className="ad-grid2">
        <L label="Máx. salas (-1 = ilimitado)"><input className="ad-input" type="number" value={f.max_rooms} onChange={(e) => setF({ ...f, max_rooms: e.target.value })} /></L>
        <L label="Máx. participantes"><input className="ad-input" type="number" value={f.max_participants} onChange={(e) => setF({ ...f, max_participants: e.target.value })} /></L>
        <L label="Storage (GB)"><input className="ad-input" type="number" value={f.storage_quota_gb} onChange={(e) => setF({ ...f, storage_quota_gb: e.target.value })} /></L>
        <L label="Preço (R$/mês)"><input className="ad-input" type="number" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></L>
      </div>
      <label className="ad-check"><input type="checkbox" checked={f.recording_enabled} onChange={(e) => setF({ ...f, recording_enabled: e.target.checked })} /> Gravação habilitada</label>
    </Modal>
  );
}

/* ---------------- Change password ---------------- */
function ChangePassword({ onClose }: { onClose: () => void }) {
  const [cur, setCur] = useState(""); const [nw, setNw] = useState("");
  const [err, setErr] = useState<string | null>(null); const [ok, setOk] = useState(false);
  const submit = async () => {
    setErr(null);
    if (nw.length < 8) { setErr("Nova senha: mínimo 8 caracteres."); return; }
    try { await adminApi("/change-password", { method: "POST", body: JSON.stringify({ current_password: cur, new_password: nw }) }); setOk(true); setTimeout(onClose, 1200); }
    catch (e: any) { setErr(e.message || "erro"); }
  };
  return (
    <Modal title="Trocar senha" onClose={onClose} onSubmit={submit} submitLabel="Salvar" err={err}>
      {ok ? <div className="ad-ok">Senha alterada ✓</div> : <>
        <L label="Senha atual"><input className="ad-input" type="password" value={cur} onChange={(e) => setCur(e.target.value)} /></L>
        <L label="Nova senha"><input className="ad-input" type="password" value={nw} onChange={(e) => setNw(e.target.value)} /></L>
      </>}
    </Modal>
  );
}

/* ---------------- small helpers ---------------- */
function L({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="ad-field"><span>{label}</span>{children}</label>;
}
function Stat({ v, l }: { v: number; l: string }) {
  return <div className="ad-card"><div className="ad-card-v">{v}</div><div className="ad-card-l">{l}</div></div>;
}
function eff(v: number) { return v === -1 ? "∞" : v; }
function Modal({ title, children, onClose, onSubmit, submitLabel, err }: { title: string; children: React.ReactNode; onClose: () => void; onSubmit: () => void; submitLabel: string; err?: string | null }) {
  return (
    <div className="ad-overlay" onClick={onClose}>
      <div className="ad-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ad-modal-head"><h3>{title}</h3><button className="ad-x" onClick={onClose}>×</button></div>
        {children}
        {err && <div className="ad-err">{err}</div>}
        <div className="ad-modal-foot"><button className="ad-btn-outline" onClick={onClose}>Cancelar</button><button className="ad-btn" onClick={onSubmit}>{submitLabel}</button></div>
      </div>
    </div>
  );
}

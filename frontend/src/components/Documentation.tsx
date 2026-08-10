import { useEffect, useRef, useState } from "react";
import "../styles/doc.css";

const API = "https://video.pbltools.io";

function Code({ children, lang = "bash" }: { children: string; lang?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="doc-code">
      <div className="doc-code-bar">
        <span>{lang}</span>
        <button onClick={() => { navigator.clipboard?.writeText(children); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          {copied ? "copiado ✓" : "copiar"}
        </button>
      </div>
      <pre><code>{children}</code></pre>
    </div>
  );
}

function M({ m }: { m: string }) {
  return <span className="doc-method" data-m={m}>{m}</span>;
}

const SECTIONS: [string, string][] = [
  ["overview", "Visão geral"],
  ["auth", "Autenticação"],
  ["quickstart", "Início rápido"],
  ["endpoints", "Endpoints"],
  ["embed-iframe", "Embed via iframe"],
  ["embed-sdk", "Embed via SDK"],
  ["modal", "Modal de criação"],
  ["guests", "Convidados"],
  ["scheduling", "Agendamento"],
  ["limits", "Limites da licença"],
  ["errors", "Erros"],
];

export default function Documentation() {
  const [active, setActive] = useState("overview");
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const root = mainRef.current;
    if (!root) return;
    const obs = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (vis[0]) setActive(vis[0].target.id);
      },
      { root, rootMargin: "-10% 0px -70% 0px", threshold: 0 },
    );
    root.querySelectorAll("section[id]").forEach((s) => obs.observe(s));
    return () => obs.disconnect();
  }, []);

  return (
    <div className="doc-root">
      <aside className="doc-side">
        <div className="doc-brand"><div className="doc-logo">V</div><div><div className="doc-brand-t">Video Rooms</div><div className="doc-brand-s">API · Integração</div></div></div>
        <nav>
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`} data-active={active === id}>{label}</a>
          ))}
        </nav>
        <a className="doc-side-link" href="/admin">Abrir painel →</a>
      </aside>

      <main className="doc-main" ref={mainRef}>
        <header className="doc-hero">
          <div className="doc-hero-badge">Documentação</div>
          <h1>Integre a webconferência na sua plataforma</h1>
          <p>Crie salas, agende, gerencie histórico e renderize a chamada — via API REST, iframe ou SDK. Em qualquer linguagem.</p>
          <div className="doc-hero-meta"><span>Base</span><code>{API}</code></div>
        </header>

        <section id="overview">
          <h2>Visão geral</h2>
          <p>A integração usa <b>2 camadas de segurança</b>:</p>
          <div className="doc-twocol">
            <div className="doc-mini"><div className="doc-mini-t">🔑 API key <span>server-side</span></div>Identifica a sua licença. Fica <b>apenas no seu backend</b> — nunca no navegador.</div>
            <div className="doc-mini"><div className="doc-mini-t">🎟️ Token curto <span>client-side</span></div>Autoriza um usuário a entrar numa sala. Gerado pelo seu backend e repassado ao frontend.</div>
          </div>
          <div className="doc-diagram">
            <pre>{`[Seu backend]  --X-API-Key-->  [Video Rooms API]   cria sala / assina token
      |
      +-- token curto -->  [Seu frontend]  -->  entra na chamada`}</pre>
          </div>
          <div className="doc-warn">Nunca exponha a API key no frontend. Toda chamada autenticada por API key parte do seu backend.</div>
        </section>

        <section id="auth">
          <h2>Autenticação</h2>
          <p>Envie a sua API key (gerada no painel) no header de cada requisição server-side:</p>
          <Code lang="http">{`X-API-Key: bwl_live_xxxxxxxxxxxxxxxxxxxxxxxx`}</Code>
          <p>Tudo fica <b>isolado à sua licença</b> — você só enxerga e gerencia as suas salas. A identidade do usuário final vai em <code>X-User-Id</code>, <code>X-User-Name</code> e <code>X-User-Role</code> (<code>admin</code> | <code>user</code>).</p>
        </section>

        <section id="quickstart">
          <h2>Início rápido</h2>
          <p>No seu backend: crie a sala e emita um token para o usuário entrar.</p>
          <Code lang="javascript">{`const API = "${API}";
const KEY = process.env.VIDEO_ROOMS_API_KEY; // bwl_live_...

// 1) cria a sala
const room = await fetch(\`\${API}/api/rooms\`, {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": KEY },
  body: JSON.stringify({ title: "Mentoria 1:1", lobby_enabled: true }),
}).then(r => r.json());

// 2) emite um token para ESTE usuário entrar NESTA sala
const tok = await fetch(\`\${API}/api/token\`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": KEY,
    "X-User-Id": user.id,
    "X-User-Name": user.name,
    "X-User-Role": user.isHost ? "admin" : "user",
  },
  body: JSON.stringify({ room_id: room.id }),
}).then(r => r.json());
// tok => { token, livekit_url, identity }`}</Code>
        </section>

        <section id="endpoints">
          <h2>Endpoints</h2>
          <table className="doc-table">
            <thead><tr><th>Método</th><th>Rota</th><th>Descrição</th></tr></thead>
            <tbody>
              <tr><td><M m="POST" /></td><td><code>/api/rooms</code></td><td>Criar sala</td></tr>
              <tr><td><M m="GET" /></td><td><code>/api/rooms</code></td><td>Listar salas (histórico)</td></tr>
              <tr><td><M m="GET" /></td><td><code>/api/rooms/&#123;id&#125;</code></td><td>Detalhe da sala</td></tr>
              <tr><td><M m="POST" /></td><td><code>/api/rooms/&#123;id&#125;/end</code></td><td>Encerrar sala</td></tr>
              <tr><td><M m="POST" /></td><td><code>/api/rooms/bookings/sync</code></td><td>Agendar/criar sala (idempotente)</td></tr>
              <tr><td><M m="POST" /></td><td><code>/api/token</code></td><td>Emitir token de entrada</td></tr>
              <tr><td><M m="POST" /></td><td><code>/api/rooms/&#123;id&#125;/recording/start</code> · <code>/stop</code></td><td>Gravação</td></tr>
              <tr><td><M m="GET" /></td><td><code>/api/rooms/&#123;id&#125;/recording</code></td><td>Status + URL assinada da gravação</td></tr>
            </tbody>
          </table>
          <p className="doc-muted">Referência interativa (OpenAPI): <code>{API}/docs</code></p>
        </section>

        <section id="embed-iframe">
          <h2>Embed via iframe <span className="doc-tag">qualquer stack</span></h2>
          <p>O jeito mais simples de encaixar a chamada — funciona em qualquer linguagem. Seu backend gera o token (acima) e você carrega o iframe:</p>
          <Code lang="html">{`<iframe
  src="${API}/embed?room=ROOM_ID&token=TOKEN&url=LIVEKIT_URL&name=Maria&staff=0"
  allow="camera; microphone; display-capture; autoplay"
  style="width:100%;height:600px;border:0;border-radius:12px"
></iframe>`}</Code>
          <p><code>room</code> = id da sala; <code>token</code> e <code>url</code> vêm de <code>/api/token</code> (<code>token</code> e <code>livekit_url</code>); <code>name</code> = nome exibido; <code>staff=1</code> para anfitrião.</p>
          <div className="doc-warn">O atributo <code>allow="camera; microphone; ..."</code> é obrigatório para o navegador liberar mídia dentro do iframe.</div>
        </section>

        <section id="embed-sdk">
          <h2>Embed via SDK <span className="doc-tag">React</span></h2>
          <p>Se a sua plataforma usa React, monte o componente com o token recebido do seu backend:</p>
          <Code lang="tsx">{`import { createVideoRoomsSDK, SDKContext } from "@video-rooms-kit/sdk";
import VideoRoom from "@video-rooms-kit/sdk/VideoRoom";

const sdk = createVideoRoomsSDK({
  apiBase: "${API}",
  wsBase: "wss://video.pbltools.io",
  headers: () => ({ "X-User-Id": user.id, "X-User-Name": user.name }),
});

<SDKContext.Provider value={sdk}>
  <VideoRoom roomId={roomId} isStaff={user.isHost} displayName={user.name} />
</SDKContext.Provider>`}</Code>
        </section>

        <section id="modal">
          <h2>Modal de criação <span className="doc-tag">React</span></h2>
          <p>Código base, pronto para copiar, de um modal "Nova sala" com todas as opções (capacidade, gravação, permissões e saguão). São <b>2 peças</b>: a rota de backend (BFF) que guarda a API key e o componente React que a chama.</p>

          <h3>1. Backend (BFF) — a API key fica só no servidor</h3>
          <Code lang="tsx">{`// app/api/salas/route.ts  (Next.js App Router)
import { NextRequest, NextResponse } from "next/server";

const API = "${API}";
const KEY = process.env.VIDEO_ROOMS_API_KEY!; // bwl_live_...

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(API + "/api/rooms", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": KEY,                  // identifica a sua licença
      "X-User-Id": "user@empresa.com",   // identidade do usuário logado
      "X-User-Name": "Anfitriao",
      "X-User-Role": "admin",            // anfitriao = admin
    },
    body: JSON.stringify(body),
  });
  return NextResponse.json(await res.json(), { status: res.status });
}`}</Code>

          <h3>2. Frontend — o modal (React puro, sem dependências)</h3>
          <Code lang="tsx">{`// CreateRoomModal.tsx
import { useState } from "react";

const DEFAULTS = {
  title: "",
  max_participants: 50,
  auto_record: false,
  is_public: true,
  allow_camera: true,
  allow_mic: true,
  allow_screen_share: false,
  allow_whiteboard_edit: false,
  lobby_enabled: false,
  lobby_timer_title: "A sessao comecara em breve",
  lobby_timer_seconds: 300,
  lobby_auto_admit: false,
};

export default function CreateRoomModal({ onClose, onCreated }) {
  const [d, setD] = useState(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setD((p) => ({ ...p, [k]: v }));
  const Toggle = ({ k }) => (
    <input type="checkbox" checked={d[k]} onChange={(e) => set(k, e.target.checked)} />
  );

  const submit = async () => {
    if (!d.title.trim() || busy) return;
    setBusy(true);
    try {
      // chama o seu BFF (acima) — nunca a API key no navegador
      const room = await fetch("/api/salas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(d),
      }).then((r) => r.json());
      onCreated(room); // { id, room_id, guest_token, ... }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal">
      <h2>Nova sala de video</h2>

      <label>Nome da sala</label>
      <input value={d.title} onChange={(e) => set("title", e.target.value)} />

      <label>Max. participantes</label>
      <input type="number" min={2} max={500} value={d.max_participants}
        onChange={(e) => set("max_participants", +e.target.value || 2)} />

      <label><Toggle k="auto_record" /> Gravacao</label>
      <label><Toggle k="is_public" /> Sala publica</label>

      <fieldset>
        <legend>Permissoes dos participantes</legend>
        <label><Toggle k="allow_camera" /> Camera</label>
        <label><Toggle k="allow_mic" /> Microfone</label>
        <label><Toggle k="allow_screen_share" /> Compartilhar tela</label>
        <label><Toggle k="allow_whiteboard_edit" /> Editar quadro</label>
      </fieldset>

      <fieldset>
        <legend><Toggle k="lobby_enabled" /> Saguao (lobby)</legend>
        {d.lobby_enabled && (
          <>
            <label>Titulo do cronometro</label>
            <input value={d.lobby_timer_title}
              onChange={(e) => set("lobby_timer_title", e.target.value)} />
            <label>Tempo do cronometro (segundos)</label>
            <input type="number" min={0} value={d.lobby_timer_seconds}
              onChange={(e) => set("lobby_timer_seconds", +e.target.value || 0)} />
            <label><Toggle k="lobby_auto_admit" /> Admissao automatica</label>
          </>
        )}
      </fieldset>

      <div className="modal-foot">
        <button onClick={onClose}>Cancelar</button>
        <button onClick={submit} disabled={busy}>{busy ? "Criando..." : "Criar sala"}</button>
      </div>
    </div>
  );
}`}</Code>
          <p className="doc-muted">Depois de criar, use o <code>id</code> retornado em <code>/api/token</code> (ver <a href="#quickstart">Início rápido</a>) e abra a chamada no iframe. Para galeria/upload de vídeo de fundo do saguão, use <code>GET</code>/<code>POST</code> <code>/api/backgrounds</code> (multipart) com a mesma API key.</p>
        </section>

        <section id="guests">
          <h2>Convidados (sem login)</h2>
          <p>Ao criar a sala, a resposta inclui um <code>guest_token</code>. Compartilhe o link público — o convidado informa o nome e entra (passando pelo saguão, se ativo):</p>
          <Code lang="text">{`${API}/guest/<guest_token>`}</Code>
        </section>

        <section id="scheduling">
          <h2>Agendamento</h2>
          <p>Crie a sala de um agendamento de forma idempotente (por <code>external_ref</code>):</p>
          <Code lang="javascript">{`await fetch(\`\${API}/api/rooms/bookings/sync\`, {
  method: "POST",
  headers: { "Content-Type": "application/json", "X-API-Key": KEY },
  body: JSON.stringify({
    external_ref: booking.id,           // idempotente por este campo
    title: \`Sessão: \${booking.title}\`,
    scheduled_at: booking.scheduled_at, // ISO 8601
    owner_id: booking.mentor_id,
    lobby_enabled: true,
  }),
});`}</Code>
        </section>

        <section id="limits">
          <h2>Limites da licença</h2>
          <p>Cada licença tem limites (máximo de salas ativas, participantes por sala, gravação, storage), definidos pelo plano e/ou override. Requisições que excedam o limite retornam <code>403</code>. Veja os limites efetivos no painel.</p>
        </section>

        <section id="errors">
          <h2>Erros</h2>
          <table className="doc-table">
            <thead><tr><th>Código</th><th>Significado</th></tr></thead>
            <tbody>
              <tr><td><span className="doc-err-code">401</span></td><td>API key ausente, inválida ou revogada</td></tr>
              <tr><td><span className="doc-err-code">403</span></td><td>Sala de outra licença, ou limite atingido</td></tr>
              <tr><td><span className="doc-err-code">404</span></td><td>Sala ou convite não encontrado</td></tr>
            </tbody>
          </table>
          <div className="doc-foot">Precisa de uma API key? Gere no painel (<a href="/admin">/admin</a>) → Licenças → API Keys.</div>
        </section>
      </main>
    </div>
  );
}

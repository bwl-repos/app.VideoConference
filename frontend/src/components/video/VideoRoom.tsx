import { useEffect, useMemo, useRef, useState, useCallback, lazy, Suspense, type ReactNode } from "react";
import {
  LiveKitRoom, RoomAudioRenderer, GridLayout, ParticipantTile,
  useTracks, useParticipants, useTrackToggle, useRoomContext, useLocalParticipant,
  useMaybeTrackRefContext,
} from "@livekit/components-react";
import { Track, RoomEvent, Room, ConnectionState, ParticipantEvent, ConnectionQuality } from "livekit-client";
import { QRCodeSVG } from "qrcode.react";
import "@livekit/components-styles";
import "../../styles/room.css";
import { useSDK } from "../../lib/sdk-context";
import { guestAuth } from "../../lib/guest-auth";
import { applyBranding, type Branding } from "../../lib/branding";
import type { BreakoutState, BreakoutGroup, OpenPblStage, RoteiroSnapshot, RoteiroBlocoFixo } from "../../lib/video-rooms-sdk";
import RoomChat from "./RoomChat";
import LobbyPanel from "./LobbyPanel";
import RemoteControlEnforcer from "./RemoteControlEnforcer";

// tldraw is heavy — only load it when the whiteboard is actually opened.
const Whiteboard = lazy(() => import("./Whiteboard"));
const BreakoutPanel = lazy(() => import("./BreakoutPanel"));

/** Estado da troca de mídia quando o participante/host está dentro de um grupo. */
interface BreakoutMedia { token: string; url: string; groupId: string; groupName: string; endsAt: string | null; }
/** Tudo que o RoomShell precisa para a UI de grupos. */
interface BreakoutCtx {
  active: { groupId: string; groupName: string; endsAt: string | null } | null;
  message: string | null;
  identity?: string;
  displayName?: string;
  isStaff: boolean;
  enter: (g: { id: string; name: string }, endsAt: string | null) => void;
  leave: () => void;
}

interface Props {
  roomId: string;
  guestToken?: string;
  speakerInviteId?: string;
  displayName?: string;
  isStaff?: boolean;
  onLeft?: () => void;
  /** Pre-minted LiveKit token (iframe embed) — skips token minting when set. */
  presetToken?: string;
  presetLivekitUrl?: string;
  presetIdentity?: string;
  /** Learner e-mail (SCORM/OpenPBL) — stored on join for progress matching. */
  learnerEmail?: string;
}

/* ---------------- icons (inline, no deps) ---------------- */
const I = {
  mic: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4"/></svg>,
  micOff: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M1 1l22 22"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M19 10v2a7 7 0 0 1-.11 1.23M12 19v4M5 10v2a7 7 0 0 0 12 5"/></svg>,
  cam: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>,
  camOff: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 1l22 22"/><path d="M16 16H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h1m4 0h4a2 2 0 0 1 2 2v4l1 1 5-3.5v9"/></svg>,
  screen: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>,
  chat: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  people: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  board: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M8 21h8M12 17v4"/><path d="M7 11l3-3 2 2 4-4"/></svg>,
  record: <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="7"/></svg>,
  stop: <svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>,
  phone: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M21 15.46l-5.27-.61-2.52 2.52a15.05 15.05 0 0 1-6.59-6.59l2.53-2.53L8.54 3H3.03C2.45 13.18 10.82 21.55 21 20.97v-5.51z"/></svg>,
  groups: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>,
  more: <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>,
  eye: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
  eyeOff: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>,
  expand: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>,
  copy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
  playTri: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"><path d="M7 5.5v13l11-6.5z"/></svg>,
  qr: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3M21 14v7M17 21h4"/></svg>,
  gear: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>,
};

export default function VideoRoom({ roomId, guestToken, speakerInviteId, displayName, isStaff, onLeft, presetToken, presetLivekitUrl, presetIdentity, learnerEmail }: Props) {
  const sdk = useSDK();
  const [token, setToken] = useState<string | null>(presetToken ?? null);
  const [livekitUrl, setLivekitUrl] = useState<string | null>(presetLivekitUrl ?? null);
  const [identity, setIdentity] = useState<string | null>(presetIdentity ?? null);
  const [ended, setEnded] = useState(false);
  const [left, setLeft] = useState(false);
  const [roomTitle, setRoomTitle] = useState<string>("");
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  // pre-join choices
  const [joined, setJoined] = useState(false);
  const [camOn, setCamOn] = useState(true);
  const [micOn, setMicOn] = useState(true);

  // Emite o token UMA vez por sala. Antes o efeito reagia a `displayName`/`learnerEmail`:
  // qualquer mudança (mesmo cosmética, vinda de um re-render do pai) reemitia o token, e
  // trocar o token no <LiveKitRoom> derruba e refaz a conexão — o aluno "caía" sozinho
  // segundos após entrar. O nome exibido não precisa de token novo.
  const tokenIssuedFor = useRef<string | null>(null);
  const [tokenAttempt, setTokenAttempt] = useState(0);   // incrementa para tentar de novo
  useEffect(() => {
    // Nome/e-mail entram na chave: se chegarem depois (fluxo assíncrono/LTI), o token é
    // reemitido UMA vez com os dados certos — sem reemitir a cada render, que era o bug.
    const key = `${roomId}|${guestToken ?? ""}|${speakerInviteId ?? ""}|${presetToken ?? ""}|${displayName}|${learnerEmail ?? ""}`;
    if (tokenIssuedFor.current === key) return;
    tokenIssuedFor.current = key;
    if (presetToken) {  // iframe embed: token already minted by the client backend
      setToken(presetToken); setLivekitUrl(presetLivekitUrl ?? null); setIdentity(presetIdentity ?? null);
      return;
    }
    sdk.token
      .issue({ room_id: roomId, guest_token: guestToken, speaker_invite_id: speakerInviteId, display_name: displayName, email: learnerEmail })
      .then((r) => { setToken(r.token); setLivekitUrl(r.livekit_url); setIdentity(r.identity); })
      .catch((e) => {
        // Falhou (rede/500): destrava e reagenda. Sem isto o aluno ficava preso em
        // "Conectando…" para sempre, sem retry nem aviso.
        console.error(e);
        tokenIssuedFor.current = null;
        setTimeout(() => setTokenAttempt((n) => n + 1), 2000);
      });
  }, [roomId, guestToken, speakerInviteId, displayName, presetToken, presetLivekitUrl, presetIdentity, learnerEmail, tokenAttempt]);

  useEffect(() => {
    return sdk.subscribe(roomId, (event, payload) => {
      if (event === "room-ended") { setEnded(true); return; }
      // `force-kick` é transmitido para a SALA INTEIRA com o alvo em payload.user_id.
      // Sem filtrar, expulsar UM aluno derrubava TODOS (inclusive o próprio anfitrião).
      if (event === "force-kick") {
        if (isStaff) return;                                    // host nunca se auto-expulsa
        if (payload?.user_id && payload.user_id !== identity) return;   // não é para mim
        leftRef.current = true;                                 // saída definitiva: não reconecta
        setLeft(true);
        onLeft?.();
      }
    });
  }, [roomId, identity, isStaff, onLeft]);

  /* ---------------- Grupos (breakout) ---------------- */
  const [breakout, setBreakout] = useState<BreakoutMedia | null>(null);
  const [boMessage, setBoMessage] = useState<string | null>(null);
  const [boChoices, setBoChoices] = useState<BreakoutGroup[] | null>(null);
  // Trocar de sala (principal ↔ grupo) remonta o LiveKitRoom e dispara onDisconnected.
  // Guardamos o INSTANTE do swap em vez de um booleano: uma transição pode gerar MAIS
  // de uma desconexão (a sala antiga e uma tentativa falha da nova), e o booleano era
  // consumido na primeira — a segunda caía como "saiu da sala" e ejetava o aluno.
  const swapAtRef = useRef(0);
  // Saída intencional (botão "Sair"): já tratada por requestLeave, então o
  // onDisconnected que vem em seguida não deve disparar onLeft de novo.
  const leftRef = useRef(false);

  // Contador de entradas: entra na `key` do <LiveKitRoom> para que CADA entrada em
  // grupo crie uma conexão nova. Sem ele, reentrar no MESMO grupo (caso de quem cai
  // e volta) mantinha a chave igual — o React não remontava e o token novo era
  // ignorado, deixando a pessoa presa numa sessão morta: dentro do grupo, sem ver
  // nem falar com ninguém.
  const [boSeq, setBoSeq] = useState(0);

  const enterBreakout = useCallback(async (group: { id: string; name: string }, endsAt: string | null) => {
    if (!identity) return;
    try {
      const t = await sdk.breakouts.token(roomId, group.id, identity, displayName);
      swapAtRef.current = Date.now();
      setBoSeq((n) => n + 1);
      setBreakout({ token: t.token, url: t.livekit_url, groupId: group.id, groupName: t.group_name, endsAt });
      setBoChoices(null);
    } catch (e) { console.error("breakout token", e); }
  }, [identity, roomId, displayName]);

  const leaveBreakout = useCallback(() => { swapAtRef.current = Date.now(); setBreakout(null); setBoChoices(null); }, []);

  const handleDisconnected = useCallback(() => {
    // Dentro da janela do swap, QUALQUER desconexão é da troca de sala — não ejeta.
    if (Date.now() - swapAtRef.current < SWAP_WINDOW_MS) return;
    if (leftRef.current) return;                              // saída intencional já tratada
    setLeft(true);    // mostra a tela de saída (essencial no embed, onde não há onLeft)
    onLeft?.();
  }, [onLeft]);

  // Sair de verdade: desmonta o LiveKitRoom levantando `left`. Não dependemos de
  // room.disconnect() sozinho porque `connect` fica sempre true no LiveKitRoom — a
  // desconexão manual podia ser desfeita por uma reconexão automática ("Sair" travava).
  const requestLeave = useCallback(() => {
    if (leftRef.current) return;
    leftRef.current = true;
    setLeft(true);
    onLeft?.();
  }, [onLeft]);

  // Eventos de controle dos grupos (chegam pela sala-pai, mesmo dentro do grupo).
  useEffect(() => {
    if (!identity) return;
    return sdk.subscribe(roomId, (event, payload) => {
      if (event === "breakout-open") {
        const st = payload as BreakoutState;
        if (isStaff) return; // host fica na principal; visita pelo painel
        const mine = st.groups.find((g) => g.members.some((m) => m.identity === identity));
        if (mine) enterBreakout(mine, st.ends_at);
        else if (st.mode === "self") setBoChoices(st.groups);
      } else if (event === "breakout-close") {
        leaveBreakout();
      } else if (event === "breakout-message") {
        setBoMessage(payload?.text ? `${payload.from || "Anfitrião"}: ${payload.text}` : null);
      }
    });
  }, [roomId, identity, isStaff, enterBreakout, leaveBreakout]);

  // Volta para o grupo ao qual a pessoa está atribuída (a atribuição é persistida e o
  // identity do convidado é estável por e-mail). Usado na resolução inicial e no
  // "Entrar novamente" da tela de saída.
  const rejoinMyGroup = useCallback(async () => {
    if (!identity || isStaff) return;
    try {
      const st = await sdk.breakouts.state(roomId);
      if (!st.open) { setBreakout(null); return; }   // grupos encerraram enquanto esteve fora
      const mine = st.groups.find((g) => g.members.some((m) => m.identity === identity));
      if (mine) await enterBreakout(mine, st.ends_at);   // token novo, não o antigo
      else if (st.mode === "self") setBoChoices(st.groups);
    } catch { /* sem estado de grupos: segue na sala principal */ }
  }, [identity, isStaff, roomId, enterBreakout]);

  // Resolve a sala-destino ANTES da primeira conexão. Antes conectávamos na principal e
  // só depois descobríamos o grupo — o aluno era movido ~5s após entrar, e cada
  // movimentação derruba e refaz a sessão de mídia (parecia "caiu sozinho").
  // Roda UMA vez (resolvedRef): sem a trava, mudanças de `displayName` recriavam o
  // callback e reentravam no grupo no meio da aula, gerando novas quedas.
  const [boResolved, setBoResolved] = useState(false);
  const resolvedRef = useRef(false);
  const resolveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (isStaff) { setBoResolved(true); return; }   // host entra sempre na principal
    if (resolvedRef.current) return;
    if (!token) return;                             // sem token ainda: a tela "Conectando…" cobre
    // Embed pode passar token sem identity — aí não há grupo a resolver; libera a entrada
    // em vez de travar em "Entrando…".
    if (!identity) { setBoResolved(true); return; }
    resolvedRef.current = true;
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      if (resolveTimerRef.current) { clearTimeout(resolveTimerRef.current); resolveTimerRef.current = null; }
      setBoResolved(true);
    };
    // Rede de segurança: a entrada nunca fica travada pela consulta de grupos. Fica num
    // ref (não no cleanup do efeito) — senão uma re-execução do efeito matava o timer e,
    // com `resolvedRef` já travado, ninguém reagendava.
    resolveTimerRef.current = setTimeout(finish, 5000);
    (async () => {
      try { await rejoinMyGroup(); } catch { /* segue na principal */ }
      finish();
    })();
  }, [identity, isStaff, token, rejoinMyGroup]);

  // Reconcilia os grupos quando o WS volta de uma queda, e quando o host REMANEJA
  // alguém com os grupos já abertos (o backend emite `breakout-state` nesse caso).
  // Fica separado do handler de breakout-open/close porque precisa de `rejoinMyGroup`,
  // definido acima — e a resolução inicial roda uma vez só, então sem isto o aluno que
  // perdesse o evento durante um blip nunca entraria no grupo.
  useEffect(() => {
    if (isStaff || !identity) return;
    return sdk.subscribe(roomId, (event) => {
      if (event === "__reconnected" || event === "breakout-state") rejoinMyGroup();
    });
  }, [roomId, identity, isStaff, rejoinMyGroup]);

  // Auto-some o aviso após alguns segundos.
  useEffect(() => {
    if (!boMessage) return;
    const t = setTimeout(() => setBoMessage(null), 8000);
    return () => clearTimeout(t);
  }, [boMessage]);

  useEffect(() => {
    sdk.rooms.get(roomId).then((r) => {
      setRoomTitle(r.title || "Sala");
      if (isStaff && r.guest_token) setInviteUrl(`${location.origin}/guest/${r.guest_token}`);
    }).catch(() => {});
  }, [roomId, isStaff]);

  if (ended) return (
    <div className="vr-root">
      <div className="vr-center">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
          <div>Esta sala foi encerrada.</div>
          <button className="vr-join-btn" style={{ minWidth: 200 }} onClick={() => onLeft?.()}>Voltar ao início</button>
        </div>
      </div>
    </div>
  );
  if (left) return (
    <div className="vr-root">
      <div className="vr-center">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
          <div>Você saiu da sala.</div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="vr-join-btn" style={{ minWidth: 180 }}
              onClick={async () => { leftRef.current = false; await rejoinMyGroup(); setLeft(false); }}>Entrar novamente</button>
            {onLeft && <button className="vr-join-btn" style={{ minWidth: 140, background: "transparent", border: "1px solid var(--vr-border)" }} onClick={() => onLeft()}>Voltar ao início</button>}
          </div>
        </div>
      </div>
    </div>
  );
  if (!token || !livekitUrl) return <div className="vr-root"><div className="vr-center">Conectando…</div></div>;

  if (!joined) {
    return (
      <PreJoin
        title={roomTitle}
        name={displayName || "Você"}
        camOn={camOn} micOn={micOn}
        setCamOn={setCamOn} setMicOn={setMicOn}
        onJoin={() => setJoined(true)}
      />
    );
  }

  // Só conecta depois de saber a sala-destino (principal ou grupo). Evita entrar na
  // principal e ser movido em seguida — a troca derruba a sessão de mídia.
  if (!boResolved) return <div className="vr-root"><div className="vr-center">Entrando…</div></div>;

  const boCtx: BreakoutCtx = {
    active: breakout ? { groupId: breakout.groupId, groupName: breakout.groupName, endsAt: breakout.endsAt } : null,
    message: boMessage,
    identity: identity ?? undefined,
    displayName,
    isStaff: !!isStaff,
    enter: enterBreakout,
    leave: leaveBreakout,
  };

  return (
    <>
      <LiveKitRoom
        key={breakout ? `${breakout.groupId}:${boSeq}` : "main"}
        serverUrl={breakout?.url ?? livekitUrl}
        token={breakout?.token ?? token}
        connect
        video={camOn}
        audio={micOn}
        data-lk-theme="default"
        className="vr-root"
        onDisconnected={handleDisconnected}
        onConnected={() => { swapAtRef.current = 0; }}
      >
        <RoomShell roomId={roomId} roomTitle={roomTitle} isStaff={!!isStaff} inviteUrl={inviteUrl} senderName={displayName} identity={identity ?? undefined} breakout={boCtx} onLeaveRoom={requestLeave} />
        {identity && <RemoteControlEnforcer roomId={roomId} identity={identity} isStaff={!!isStaff} />}
        {isStaff && !breakout && identity && (
          <HostBroadcast roomId={roomId} identity={identity} displayName={displayName} />
        )}
        <RoomAudioRenderer />
        <AudioGate />
      </LiveKitRoom>
      {boChoices && <BreakoutChooser groups={boChoices} onPick={(g) => enterBreakout(g, null)} />}
    </>
  );
}

/* ---------------- Breakout: seletor (modo "os participantes escolhem") ------- */
function BreakoutChooser({ groups, onPick }: { groups: BreakoutGroup[]; onPick: (g: { id: string; name: string }) => void }) {
  return (
    <div className="vr-bo-chooser">
      <div className="vr-bo-chooser-card">
        <h3>Escolha um grupo</h3>
        <p className="vr-sub">O anfitrião abriu os grupos. Selecione em qual você quer entrar.</p>
        <div className="vr-bo-chooser-list">
          {groups.map((g) => (
            <button key={g.id} className="vr-bo-chooser-item" onClick={() => onPick({ id: g.id, name: g.name })}>
              <strong>{g.name}</strong>
              <span>{g.members.length} {g.members.length === 1 ? "pessoa" : "pessoas"}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------- Breakout: banner (dentro de um grupo / aviso do host) ------ */
function BreakoutBanner({ groupName, endsAt, message, onLeave }: { groupName: string | null; endsAt: string | null; message: string | null; onLeave: () => void }) {
  const [remain, setRemain] = useState<number | null>(null);
  useEffect(() => {
    if (!endsAt) { setRemain(null); return; }
    const end = new Date(endsAt).getTime();
    const tick = () => {
      const s = Math.max(0, Math.round((end - Date.now()) / 1000));
      setRemain(s);
      if (s <= 0) onLeave();
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [endsAt]);
  const mmss = remain != null ? `${Math.floor(remain / 60)}:${String(remain % 60).padStart(2, "0")}` : null;

  // Só aviso (host broadcast), sem estar em grupo.
  if (!groupName) return <div className="vr-bo-banner vr-bo-banner-msg">{message}</div>;

  return (
    <div className="vr-bo-banner">
      <span>Você está no <b>{groupName}</b>{mmss ? ` • volta em ${mmss}` : ""}</span>
      <div className="vr-bo-banner-right">
        {message && <span className="vr-bo-banner-note">{message}</span>}
        <button className="vr-bo-banner-btn" onClick={onLeave}>Voltar à sala principal</button>
      </div>
    </div>
  );
}

/* ---------------- Áudio: gate para Safari/mobile (autoplay bloqueado) -------- */
function AudioGate() {
  const room = useRoomContext();
  const [blocked, setBlocked] = useState(false);
  useEffect(() => {
    const update = () => setBlocked(!room.canPlaybackAudio);
    update();
    room.on(RoomEvent.AudioPlaybackStatusChanged, update);
    return () => { room.off(RoomEvent.AudioPlaybackStatusChanged, update); };
  }, [room]);
  if (!blocked) return null;
  return (
    <button className="vr-audio-gate" onClick={() => room.startAudio().catch(() => {})}>
      🔊 Toque para ativar o áudio
    </button>
  );
}

/* ---------------- Breakout: barra do host (flutuar entre os grupos) ---------- */
function BreakoutHostBar({ roomId, active, message, onEnter, onLeave }: {
  roomId: string;
  active: { groupId: string; groupName: string; endsAt: string | null } | null;
  message: string | null;
  onEnter: (g: { id: string; name: string }, endsAt: string | null) => void;
  onLeave: () => void;
}) {
  const sdk = useSDK();
  const [groups, setGroups] = useState<BreakoutGroup[]>([]);
  const [open, setOpen] = useState(false);
  const [endsAt, setEndsAt] = useState<string | null>(null);
  const [remain, setRemain] = useState<number | null>(null);

  useEffect(() => {
    const refresh = () => sdk.breakouts.state(roomId).then((s) => {
      setGroups(s.groups); setOpen(s.open); setEndsAt(s.ends_at);
    }).catch(() => {});
    refresh();
    return sdk.subscribe(roomId, (e) => { if (typeof e === "string" && e.startsWith("breakout")) refresh(); });
  }, [roomId]);

  useEffect(() => {
    if (!endsAt) { setRemain(null); return; }
    const end = new Date(endsAt).getTime();
    const tick = () => setRemain(Math.max(0, Math.round((end - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [endsAt]);

  if (!open) return message ? <div className="vr-bo-banner vr-bo-banner-msg">{message}</div> : null;
  const mmss = remain != null ? `${Math.floor(remain / 60)}:${String(remain % 60).padStart(2, "0")}` : null;

  return (
    <div className="vr-bo-hostbar">
      <span className="vr-bo-hostbar-label">Visitar:</span>
      <button className="vr-bo-chip" data-active={!active} onClick={onLeave}>Sala do facilitador</button>
      {groups.map((g) => (
        <button key={g.id} className="vr-bo-chip" data-active={active?.groupId === g.id}
          onClick={() => onEnter({ id: g.id, name: g.name }, endsAt)}>
          {g.name}<span className="vr-bo-chip-n">{g.members.length}</span>
        </button>
      ))}
      {mmss && <span className="vr-bo-hostbar-timer">⏱ {mmss}</span>}
      {message && <span className="vr-bo-hostbar-msg">{message}</span>}
    </div>
  );
}

/* ---------------- Broadcast do host para todos os grupos ---------------------
 *  Sufixo de identidade das conexões de fan-out do host. São participantes só-áudio
 *  (sem câmera) que NÃO devem aparecer nas grades nem na contagem de participantes. */
const BROADCAST_SUFFIX = "__bc";
// Desconexões dentro desta janela após uma troca de sala pertencem à transição
// (a sala antiga fecha, a nova conecta) — nunca são "o usuário saiu".
const SWAP_WINDOW_MS = 10000;
const isBroadcast = (id: string) => id.endsWith(BROADCAST_SUFFIX);
// Participante do egress (gravador headless) — não é uma pessoa, nunca vira tile.
const isEgress = (id: string) => id.startsWith("EG_");

/* HostBroadcast: publica o microfone do facilitador em TODAS as salas de grupo ao
 *  mesmo tempo — a "sala do facilitador". Montado dentro do <LiveKitRoom> apenas
 *  quando o host NÃO está visitando um grupo (gate `!breakout` em VideoRoom); ao
 *  entrar num grupo este componente desmonta e o cleanup direciona o áudio só para
 *  aquele grupo. Mantém uma conexão LiveKit crua por grupo, publish-only. */
function HostBroadcast({ roomId, identity, displayName }: { roomId: string; identity: string; displayName?: string }) {
  const sdk = useSDK();
  const { microphoneTrack, isMicrophoneEnabled } = useLocalParticipant();
  const srcTrack = microphoneTrack?.audioTrack?.mediaStreamTrack ?? null;
  const srcTrackId = srcTrack?.id ?? null;
  const micMuted = !isMicrophoneEnabled;

  type Entry = { room: Room; clone: MediaStreamTrack | null; srcId: string | null };
  const roomsRef = useRef<Map<string, Entry>>(new Map());
  const genRef = useRef(0);
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [open, setOpen] = useState(false);

  // Publica/atualiza o clone do mic numa sala, respeitando mute e troca de device.
  const syncMic = (entry: Entry) => {
    const lp = entry.room.localParticipant;
    if (!srcTrack || micMuted) {
      if (entry.clone) { try { lp.unpublishTrack(entry.clone, true); } catch { /* */ } entry.clone = null; entry.srcId = null; }
      return;
    }
    if (entry.clone && entry.srcId !== srcTrackId) {
      try { lp.unpublishTrack(entry.clone, true); } catch { /* */ }
      entry.clone = null; entry.srcId = null;
    }
    if (!entry.clone) {
      const clone = srcTrack.clone();
      entry.clone = clone; entry.srcId = srcTrackId;
      lp.publishTrack(clone, { source: Track.Source.Microphone, name: "host-broadcast" }).catch(() => { /* */ });
    }
  };

  const detach = (gid: string) => {
    const entry = roomsRef.current.get(gid);
    if (!entry) return;
    if (entry.clone) { try { entry.room.localParticipant.unpublishTrack(entry.clone, true); } catch { /* */ } }
    entry.room.disconnect();
    roomsRef.current.delete(gid);
  };
  const teardownAll = () => { for (const gid of [...roomsRef.current.keys()]) detach(gid); };

  // Estado dos grupos (aberto? quais?) — reflete abrir/fechar e add/remove de grupo.
  useEffect(() => {
    let alive = true;
    const refresh = () => sdk.breakouts.state(roomId).then((s) => {
      if (!alive) return;
      setOpen(s.open); setGroupIds(s.groups.map((g) => g.id));
    }).catch(() => { /* */ });
    refresh();
    const off = sdk.subscribe(roomId, (e) => { if (typeof e === "string" && e.startsWith("breakout")) refresh(); });
    return () => { alive = false; off(); };
  }, [roomId]);

  // Reconciliação: conecta nos grupos que faltam, desconecta os que sumiram.
  const groupKey = [...groupIds].sort().join(",");
  useEffect(() => {
    if (!open) { teardownAll(); return; }
    const gen = ++genRef.current;
    const wanted = new Set(groupIds);
    for (const gid of [...roomsRef.current.keys()]) if (!wanted.has(gid)) detach(gid);
    (async () => {
      for (const gid of groupIds) {
        if (roomsRef.current.has(gid)) continue;
        const room = new Room();
        const entry: Entry = { room, clone: null, srcId: null };
        roomsRef.current.set(gid, entry);   // reserva o slot antes do await (StrictMode/corridas)
        try {
          const t = await sdk.breakouts.token(roomId, gid, `${identity}${BROADCAST_SUFFIX}`, displayName);
          if (gen !== genRef.current) { room.disconnect(); roomsRef.current.delete(gid); return; }
          await room.connect(t.livekit_url, t.token, { autoSubscribe: false }); // publish-only
          if (gen !== genRef.current) { room.disconnect(); roomsRef.current.delete(gid); return; }
          syncMic(entry);
        } catch { roomsRef.current.delete(gid); }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, groupKey]);

  // Segue o mute do mic e trocas de microfone em todas as salas conectadas.
  useEffect(() => {
    for (const entry of roomsRef.current.values()) syncMic(entry);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srcTrackId, micMuted, groupKey]);

  // Teardown ao desmontar (entrar num grupo, sair da sala, fim da aula).
  useEffect(() => () => { genRef.current++; teardownAll(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

/* HostBreakoutOverview: o que o facilitador vê na "sala do facilitador" — só a lista
 *  dos grupos (nome + nº de alunos) com "Entrar e lecionar", e o indicador de que o
 *  áudio dele está indo para todos os grupos. Substitui a apresentação enquanto os
 *  grupos estão abertos e ele não entrou em nenhum. */
function HostBreakoutOverview({ roomId, onEnter }: {
  roomId: string;
  onEnter: (g: { id: string; name: string }, endsAt: string | null) => void;
}) {
  const sdk = useSDK();
  const { isMicrophoneEnabled } = useLocalParticipant();
  const [groups, setGroups] = useState<BreakoutGroup[]>([]);
  const [endsAt, setEndsAt] = useState<string | null>(null);

  useEffect(() => {
    const refresh = () => sdk.breakouts.state(roomId).then((s) => {
      setGroups(s.groups); setEndsAt(s.ends_at);
    }).catch(() => { /* */ });
    refresh();
    return sdk.subscribe(roomId, (e) => { if (typeof e === "string" && e.startsWith("breakout")) refresh(); });
  }, [roomId]);

  return (
    <div className="vr-fac-room">
      <div className="vr-fac-head">
        <span className="vr-fac-title">Sala do facilitador</span>
        <span className="vr-fac-cast" data-live={isMicrophoneEnabled || undefined}>
          {isMicrophoneEnabled ? "🎙 Falando para todos os grupos" : "🔇 Microfone desligado"}
        </span>
      </div>
      <div className="vr-fac-grid">
        {groups.length === 0 && <div className="vr-pbl-empty">Nenhum grupo aberto.</div>}
        {groups.map((g) => (
          <div className="vr-fac-card" key={g.id}>
            <div className="vr-fac-card-name">{g.name}</div>
            <div className="vr-fac-card-n">{g.members.length} {g.members.length === 1 ? "aluno" : "alunos"}</div>
            <button className="vr-fac-enter" onClick={() => onEnter({ id: g.id, name: g.name }, endsAt)}>Entrar e lecionar</button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- Pre-join ---------------- */
function PreJoin({ title, name, camOn, micOn, setCamOn, setMicOn, onJoin }: {
  title: string; name: string; camOn: boolean; micOn: boolean;
  setCamOn: (v: boolean) => void; setMicOn: (v: boolean) => void; onJoin: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    let cancelled = false;
    navigator.mediaDevices?.getUserMedia({ video: true, audio: true })
      .then((s) => {
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = s;
        if (videoRef.current) videoRef.current.srcObject = s;
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  useEffect(() => {
    streamRef.current?.getVideoTracks().forEach((t) => (t.enabled = camOn));
  }, [camOn]);
  useEffect(() => {
    streamRef.current?.getAudioTracks().forEach((t) => (t.enabled = micOn));
  }, [micOn]);

  return (
    <div className="vr-root">
      <div className="vr-prejoin">
        <div className="vr-prejoin-card">
          <div>
            <h2>{title || "Entrar na sala"}</h2>
            <p className="vr-sub">Você entrará como <b>{name}</b>. Ajuste sua câmera e microfone.</p>
          </div>
          <div className="vr-preview">
            {camOn
              ? <video ref={videoRef} autoPlay muted playsInline />
              : <span className="vr-preview-off">Câmera desligada</span>}
          </div>
          <div className="vr-prejoin-controls">
            <button className="vr-ctrl" data-off={!micOn} onClick={() => setMicOn(!micOn)} title="Microfone">
              {micOn ? I.mic : I.micOff}
            </button>
            <button className="vr-ctrl" data-off={!camOn} onClick={() => setCamOn(!camOn)} title="Câmera">
              {camOn ? I.cam : I.camOff}
            </button>
          </div>
          <button className="vr-join-btn" onClick={onJoin}>Entrar agora</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- In-room shell ---------------- */
export function RoomShell({ roomId, roomTitle, isStaff, inviteUrl, senderName, identity, learnerEmail, breakout, recorder = false, onLeaveRoom }: { roomId: string; roomTitle: string; isStaff: boolean; inviteUrl: string | null; senderName?: string; identity?: string; learnerEmail?: string; breakout: BreakoutCtx; recorder?: boolean; onLeaveRoom?: () => void }) {
  const sdk = useSDK();
  // O painel começa sempre fechado (chat/participantes) — o vídeo aparece inteiro.
  const [panel, setPanel] = useState<"chat" | "people" | "breakout" | "scorm" | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);   // Configurações = modal central
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [scorm, setScorm] = useState(false);
  const [pblRoster, setPblRoster] = useState<any | null>(null);   // status dos alunos (OpenPBL)
  const [plenaryQ, setPlenaryQ] = useState<{ list: string[]; total: number } | null>(null); // questões da plenária reveladas até agora (recebidas pelo aluno via dados)
  const [clock, setClock] = useState("");   // horário (HH:MM) mostrado ao lado do class-code no header do facilitador
  const [showBoard, setShowBoard] = useState(false);
  const [recording, setRecording] = useState(false);
  const [boardEdit, setBoardEdit] = useState(false);   // não-staff: pode editar o quadro?
  const participants = useParticipants().filter((p) => !isBroadcast(p.identity) && !isEgress(p.identity));
  const [brand, setBrand] = useState<Branding | null>(null);
  const [pubTitle, setPubTitle] = useState("");
  const [packageUrl, setPackageUrl] = useState<string | null>(null);  // URL do Pacote de Classe → QR code
  const [qrOpen, setQrOpen] = useState(false);
  const [roomDimensions, setRoomDimensions] = useState<string[]>([]);  // dimensões de risco da sala (cascata na Análise situacional)
  // Roteiro do episódio: é o CONTEÚDO do encontro exibido na área central — substituiu
  // o pacote SCORM de apresentação, que era transmitido por screen-share recortado.
  const [roteiro, setRoteiro] = useState<RoteiroSnapshot | null>(null);

  // ── Papéis de sessão: moderadores (poderes de host), controlador (dirige o
  //    sequenciador — "assumir controle") e câmera fixada na área de conteúdo. ──
  const [moderators, setModerators] = useState<string[]>([]);
  const [controller, setController] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const amModerator = !!identity && moderators.includes(identity);
  const amStaff = isStaff || amModerator;                             // anfitrião OU moderador
  const amController = controller ? controller === identity : isStaff; // sem controlador => host original

  // Convidado promovido a moderador autentica pelo guestSdk (X-User-*).
  useEffect(() => {
    if (identity) { guestAuth.id = identity; guestAuth.name = senderName || identity; }
  }, [identity, senderName]);

  const applyRoles = (r: { moderators?: string[]; controller?: string | null; pinned?: string | null }) => {
    if (Array.isArray(r.moderators)) setModerators(r.moderators);
    setController(r.controller ?? null);
    setPinned(r.pinned ?? null);
  };
  useEffect(() => {
    const load = () => sdk.roles.get(roomId).then(applyRoles).catch(() => {});
    load();
    return sdk.subscribe(roomId, (event, payload) => {
      if (event === "roles-updated") applyRoles(payload);
      else if (event === "__reconnected") load();
    });
  }, [roomId]);
  const setRole = (body: Parameters<typeof sdk.roles.set>[1]) =>
    sdk.roles.set(roomId, body).then((r: any) => applyRoles(r)).catch(() => {});

  const canEditBoard = amStaff || boardEdit;
  const room = useRoomContext();

  // Branding (logo/cor/nome) via endpoint público — funciona até no embed
  // cross-site, onde rooms.get (autenticado) não está disponível.
  useEffect(() => {
    sdk.rooms.publicInfo(roomId).then((r) => {
      setBrand((r.branding as Branding) || null);
      setPubTitle(r.title || "");
      setScorm(!!(r as any).scorm);
      setBoardEdit(!!(r as any).allow_whiteboard_edit);   // padrão da sala
      setPackageUrl((r as any).class_package_url || null);
      setRoomDimensions(Array.isArray((r as any).risk_dimensions) ? (r as any).risk_dimensions : []);
      setRoteiro(((r as any).roteiro as RoteiroSnapshot) || null);
      applyBranding(r.branding as Branding);
    }).catch(() => {});
  }, [roomId]);

  useEffect(() => {
    let firstLoad = true;
    const load = () => sdk.rooms.get(roomId).then((r) => {
      setShowBoard(!!r.whiteboard_active);
      setRecording(!!r.recording_enabled);
      // "Gravação" toggle at room creation → auto-start once when the host joins.
      // Só na 1ª carga (não numa reconexão do WS, senão reiniciaria a gravação).
      if (firstLoad && isStaff && !recorder && (r as any).auto_record && !r.recording_enabled) {
        setRecording(true);
        sdk.recording.start(roomId).catch(() => setRecording(false));
      }
      firstLoad = false;
    }).catch(() => {});
    load();
    return sdk.subscribe(roomId, (event, payload) => {
      if (event === "__reconnected") load();
      if (event === "whiteboard-toggle") setShowBoard(!!payload.active);
      if (event === "recording-started") setRecording(true);
      if (event === "recording-stopped") setRecording(false);
      // Permissão de editar o quadro (global ou específica deste usuário) muda ao vivo.
      if (event === "room-permissions" && typeof payload.allow_whiteboard_edit === "boolean")
        setBoardEdit(payload.allow_whiteboard_edit);
      if (event === "permissions-updated" && payload.user_id === identity && typeof payload.allow_whiteboard_edit === "boolean")
        setBoardEdit(payload.allow_whiteboard_edit);
    });
  }, [roomId, identity]);

  // OpenPBL: roster (bordas de status dos alunos + código) — só em salas scorm.
  useEffect(() => {
    if (!scorm) return;
    const load = () => sdk.openpbl.roster(roomId).then(setPblRoster).catch(() => {});
    load();
    const iv = setInterval(load, 10000);
    const off = sdk.subscribe(roomId, (event) => { if (event === "openpbl-class") load(); });
    return () => { clearInterval(iv); off(); };
  }, [scorm, roomId]);

  // Auto-gera o class-code ao ENTRAR (host + sala vinculada a uma atividade OpenPBL),
  // como o pacote PRESENTATION fazia ao abrir — não depende de abrir a aba OpenPBL.
  const autoClassRef = useRef(false);
  useEffect(() => {
    if (!scorm || !isStaff || autoClassRef.current) return;
    autoClassRef.current = true;
    (async () => {
      try {
        const st = await sdk.openpbl.classState(roomId);
        if (st.active) return;
        const r: any = await sdk.rooms.get(roomId);
        if (r.openpbl_activity_id) await sdk.openpbl.startClass(roomId, r.openpbl_activity_id);
      } catch { /* silencioso */ }
    })();
  }, [scorm, isStaff, roomId]);

  const toggleRecording = () => {
    if (recording) {
      setRecording(false);
      sdk.recording.stop(roomId).catch(() => setRecording(true));
    } else {
      setRecording(true);
      sdk.recording.start(roomId).catch(() => setRecording(false));
    }
  };

  const toggleBoard = () => {
    const next = !showBoard;
    setShowBoard(next);
    if (amStaff) sdk.whiteboard.toggle(roomId, next).catch(() => {});
  };

  // confirm() nativo é bloqueado em iframe cross-origin (embed) → modal in-app.
  const doEndRoom = () => { sdk.rooms.end(roomId).catch(() => {}); setConfirmEnd(false); };

  // Facilitador com a aula OpenPBL ativa: ganha a coluna esquerda (câmera + código
  // + apresentação). Sem a turma criada ainda, cai no layout comum de alunos.
  // Vê a área do facilitador (pacote/questões/gráfico + header) = qualquer host/moderador.
  const pblHost = !!(scorm && amStaff && pblRoster?.activity_id);
  const pblActive = !!(scorm && pblRoster?.activity_id);   // host OU aluno na aula OpenPBL

  // Sequenciamento do facilitador (botão verde ▶): estado da aula OpenPBL + etapa.
  const [pblClass, setPblClass] = useState<any | null>(null);
  useEffect(() => {
    if (!scorm) return;
    const load = () => sdk.openpbl.classState(roomId).then(setPblClass).catch(() => {});
    load();
    return sdk.subscribe(roomId, (event, payload) => {
      if (event === "openpbl-class") setPblClass(payload);
      // WS reconectou (após queda/deploy): re-busca a etapa atual, que pode ter mudado
      // enquanto o socket estava fora — é isso que evita o aluno travar numa etapa antiga.
      else if (event === "__reconnected") load();
    });
  }, [scorm, roomId]);
  const rawStage = pblClass?.stage as OpenPblStage;
  const pblStage: OpenPblStage = STEP_IDS.includes(rawStage) ? rawStage : "session_start";
  const curStep = stepDef(pblStage);
  // Visibilidade da ÁREA DE CONTEÚDO por etapa. Todo o conteúdo vem do ROTEIRO do
  // episódio e é renderizado nativamente — facilitador e aluno veem a MESMA tela:
  //  - até a plenária: os cards do roteiro da etapa (abertura, registro, sinopse…);
  //  - plenária (question): as QUESTÕES, reveladas uma a uma;
  //  - Análise situacional (situational): cascata dos RISCOS a avaliar;
  //  - a partir de "Liberar análise de riscos" (release_risks): GRÁFICO p/ host/moderador;
  //  - "Mostrar gráfico" (show_chart) em diante: GRÁFICO também para os alunos;
  //  - "Liberar feedback de interação" (release_feedback): tela SÓ do Feedback da
  //    interação — o gráfico sai, porque a atividade agora é outra.
  const showQuestionsArea = pblStage === "question";
  const showDimensions = pblStage === "situational";
  // Feedback da interação: última seção do roteiro. Tem tela própria, senão o gráfico
  // (que vale de release_risks em diante) cobriria a etapa e o texto nunca apareceria.
  const showFeedback = pblStage === "release_feedback" || pblStage === "done";
  const chartForStaff = !showFeedback && stepIndex(pblStage) >= stepIndex("release_risks");
  const chartForStudents = !showFeedback && stepIndex(pblStage) >= stepIndex("show_chart");
  const chartAvailable = chartForStaff;   // toggle do gráfico (host/moderador)

  const [chartHidden, setChartHidden] = useState(false);
  // Filtro da legenda do gráfico (séries ocultas) — SINCRONIZADO: o controlador aplica
  // e replica para os alunos por dados; o aluno só reflete (não interage).
  const [chartFilter, setChartFilter] = useState<string[]>([]);
  const toggleChartSeries = (name: string) =>
    setChartFilter((f) => (f.includes(name) ? f.filter((x) => x !== name) : [...f, name]));
  // Séries existentes no gráfico (reportadas por ele) — necessárias para começar a
  // etapa "Mostrar gráfico" com TUDO oculto.
  const [chartSeries, setChartSeries] = useState<string[]>([]);
  // Ao entrar em "Mostrar gráfico" o radar aparece zerado para os alunos: o
  // facilitador vai habilitando série por série na legenda. Roda uma vez por
  // entrada na etapa — sem a trava, cada série nova recarregada esconderia o que
  // ele acabou de mostrar.
  const zeradoRef = useRef(false);
  useEffect(() => {
    if (pblStage !== "show_chart") { zeradoRef.current = false; return; }
    if (recorder || zeradoRef.current || !chartSeries.length) return;
    zeradoRef.current = true;
    setChartFilter(chartSeries);
  }, [pblStage, chartSeries]);
  const [stageBusy, setStageBusy] = useState(false);
  // Cards já revelados na etapa atual. Vale para toda cascata que aparece um a um
  // (sinopse, questões orientadoras e questões da plenária).
  const [reveal, setReveal] = useState(0);
  // Espelho do que o controlador revelou — é assim que aluno e moderador acompanham.
  const [remoteReveal, setRemoteReveal] = useState<{ stage: string; count: number } | null>(null);

  // ── Conteúdo do encontro, lido do roteiro do episódio ──
  // Memoizado: `rLista` devolve um array novo a cada chamada e estas listas entram em
  // dependências de efeito (o heartbeat das questões reiniciaria a cada render).
  const roteiroQuestions = useMemo(() => rLista(roteiro, "questoesPlenaria"), [roteiro]);
  const roteiroSinopse = useMemo(
    () => [rTexto(roteiro, "sinopseParte1"), rTexto(roteiro, "sinopseParte2")].filter(Boolean),
    [roteiro],
  );
  const roteiroOrientadoras = useMemo(() => rLista(roteiro, "questoesOrientadoras"), [roteiro]);
  // Riscos a avaliar na Análise situacional. Vêm do roteiro; salas antigas (sem roteiro)
  // ainda caem nas dimensões do conjunto escolhido na criação.
  // Banner de fundo da apresentacao (roteiro do episodio). Chega ja como URL assinada:
  // o que fica guardado e a chave do S3, e o /public assina a cada carga da sala.
  const bannerFundo = rTexto(roteiro, "bannerFundo");
  const bannerProps = bannerFundo
    ? { "data-banner": "1", style: { ["--vr-banner" as any]: `url("${bannerFundo}")` } as React.CSSProperties }
    : {};

  const situationalItems = useMemo(() => {
    const riscos = rLista(roteiro, "riscos");
    return riscos.length ? riscos : roomDimensions;
  }, [roteiro, roomDimensions]);

  // ---- Class code (ao lado da etapa atual) + popup grande transmitido p/ a sala ----
  // Facilitador vê sempre; o aluno só enquanto o registro está aberto (e não oculto).
  // Clicar no chip copia e abre o popup; o facilitador transmite a abertura p/ todos
  // (LiveKit data). Para o aluno o popup ainda abre sozinho ao entrar no registro.
  const classCode: string | null = pblRoster?.code ?? null;
  const codeHiddenForStudents = !!pblRoster?.code_hidden;
  const registrationOpen = pblClass?.checking_open !== false;
  const studentCanSeeCode = registrationOpen && !codeHiddenForStudents;
  const [codeExpand, setCodeExpand] = useState(false);
  const [codeCopied, setCodeCopied] = useState(false);

  const broadcastCodeExpand = (open: boolean) => {
    try {
      const data = new TextEncoder().encode(JSON.stringify({ source: "webconf", type: "code-expand", expanded: open }));
      room?.localParticipant?.publishData(data, { reliable: true });
    } catch { /* */ }
  };
  const copyClassCode = async () => {
    if (!classCode) return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(classCode);
      else throw new Error("no-clipboard");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = classCode; ta.readOnly = true;
      ta.style.position = "fixed"; ta.style.top = "-9999px"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.focus(); ta.select();
      ta.setSelectionRange(0, ta.value.length);   // iOS precisa do range explícito
      try { document.execCommand("copy"); } catch { /* */ }
      document.body.removeChild(ta);
    }
    setCodeCopied(true); setTimeout(() => setCodeCopied(false), 1400);
  };
  // Clique no chip: copia + abre o popup. O facilitador transmite p/ todos presentes.
  const onCodeChipClick = () => { copyClassCode(); setCodeExpand(true); if (amStaff) broadcastCodeExpand(true); };
  const closeCodePopup = () => { setCodeExpand(false); if (amStaff) broadcastCodeExpand(false); };
  // Facilitador oculta/reexibe o code apenas para os ALUNOS (ele continua vendo).
  const toggleCodeForStudents = () => sdk.openpbl.setCodeVisible(roomId, !codeHiddenForStudents).catch(() => {});

  // Todos na sala recebem a abertura/fechamento do popup transmitida pelo facilitador.
  useEffect(() => {
    if (!room) return;
    const onData = (payload: Uint8Array) => {
      try {
        const m = JSON.parse(new TextDecoder().decode(payload));
        if (m?.source === "webconf" && m?.type === "code-expand") setCodeExpand(!!m.expanded);
        // Aluno recebe as questões reveladas da plenária por dados (sem screen-share).
        // Lista vazia = limpar (fora da etapa). Dedupe: o heartbeat reenvia a cada 3s.
        if (m?.source === "webconf" && m?.type === "plenary-questions") {
          const list: string[] = Array.isArray(m.list) ? m.list.map(String) : [];
          const total = m.total || list.length;
          setPlenaryQ((prev) => {
            if (!list.length) return prev ? null : prev;
            if (prev && prev.total === total && prev.list.join("") === list.join("")) return prev;
            return { list, total };
          });
        }
        // Quantos cards da etapa atual o facilitador já revelou (dedupe: reenviado a cada 3s).
        if (m?.source === "webconf" && m?.type === "stage-reveal" && typeof m.count === "number") {
          const next = { stage: String(m.stage || ""), count: Math.max(1, m.count) };
          setRemoteReveal((prev) =>
            prev && prev.stage === next.stage && prev.count === next.count ? prev : next);
        }
        // Filtro do gráfico aplicado pelo facilitador → replica aqui (dedupe: reenviado a cada 3s).
        if (m?.source === "webconf" && m?.type === "chart-filter" && Array.isArray(m.hidden)) {
          const h: string[] = m.hidden.map(String);
          setChartFilter((prev) => (prev.join("") === h.join("") ? prev : h));
        }
      } catch { /* */ }
    };
    room.on(RoomEvent.DataReceived, onData);
    return () => { room.off(RoomEvent.DataReceived, onData); };
  }, [room]);

  // Estado global dos grupos (breakout aberto?) — p/ as etapas Abrir/Encerrar grupos.
  const [breakoutOpen, setBreakoutOpen] = useState(false);
  useEffect(() => {
    if (!scorm) return;
    const load = () => sdk.breakouts.state(roomId).then((s) => setBreakoutOpen(!!s.open)).catch(() => {});
    load();
    return sdk.subscribe(roomId, (event, payload) => {
      if (event === "__reconnected") load();
      else if (event === "breakout-open") setBreakoutOpen(true);
      else if (event === "breakout-close") setBreakoutOpen(false);
      else if (event === "breakout-state") setBreakoutOpen(!!payload?.open);
    });
  }, [scorm, roomId]);

  // Toda troca de etapa recomeça a revelação do zero.
  useEffect(() => { setReveal(0); }, [pblStage]);

  const goToStep = async (id: OpenPblStage) => {
    try { setPblClass(await sdk.openpbl.setStage(roomId, id)); } catch { /* */ }
  };

  // Total de questões da plenária: quantas o roteiro do episódio trouxer (o padrão
  // vale só para salas sem roteiro).
  const plenaryTotal = roteiroQuestions.length || PLENARY_QUESTIONS;

  // Cards da etapa atual que aparecem um a um.
  const revealItems = pblStage === "synopsis" ? roteiroSinopse
    : pblStage === "groups" ? roteiroOrientadoras
      : pblStage === "question" ? roteiroQuestions
        : pblStage === "situational" ? situationalItems
          : [];
  // Quem conduz usa o próprio contador; os demais seguem o que ele transmite.
  const shownCount = amController
    ? reveal + 1
    // Com os grupos abertos as 3 questões já foram todas reveladas (é o que libera a
    // divisão). Dentro da sub-sala o aluno pode não receber o aviso do controlador,
    // então essa condição garante que ele veja o material completo da discussão.
    : (pblStage === "groups" && breakoutOpen) ? revealItems.length
      : (remoteReveal?.stage === pblStage ? remoteReveal.count : 1);

  // Rótulo do botão sequencial (▶): SEMPRE o que o próximo clique vai fazer.
  //
  // Nas etapas em cascata isso muda ao longo da etapa. Enquanto há card a revelar, o
  // clique revela — o rótulo é a ação da etapa com o contador. Revelados todos, o
  // clique já executa a etapa SEGUINTE, e antes o botão continuava anunciando a
  // etapa atual (ex.: "Análise situacional (5/5)" quando o clique liberava o
  // questionário de riscos).
  const faltaRevelar = revealItems.length > 1 && reveal + 1 < revealItems.length;
  const proxima = STEPS[Math.min(stepIndex(pblStage) + 1, STEPS.length - 1)];
  // Etapas cujo efeito já rodou na ENTRADA (liberação dos questionários) ou cujo
  // clique dispara o efeito da etapa seguinte: o botão anuncia a PRÓXIMA ação, senão
  // repetiria um "Liberar…" que já aconteceu.
  const anunciaProxima = pblStage === "closing"
    || pblStage === "release_risks" || pblStage === "release_feedback";
  const seqLabel = pblStage === "groups" && breakoutOpen
    ? "Encerrar os grupos"
    : faltaRevelar
      ? `${curStep.action} (${reveal + 1}/${revealItems.length})`
      // "groups" é a exceção: terminada a revelação, o clique ainda executa a AÇÃO da
      // própria etapa (abrir as salas) em vez de avançar.
      : (revealItems.length > 1 && pblStage !== "groups") || anunciaProxima
        ? proxima.action
        : curStep.action;

  // Class-code só é liberado (mostrado ao facilitador) DEPOIS de clicar em "Iniciar o
  // registro" — ou seja, a partir da etapa de "Encerrar o registro" (registro aberto).
  const codeReleased = !!classCode && stepIndex(pblStage) >= stepIndex("registration_close");
  // Código no header (esquerda): facilitador após iniciar o registro; aluno enquanto o
  // registro está aberto e não oculto. O header do aluno espelha o do facilitador.
  const showBrandCode = !!classCode && (amStaff ? codeReleased : studentCanSeeCode);

  // Relógio (HH:MM) no header do facilitador, ao lado do class-code. Atualiza a cada 20s.
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setClock(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`);
    };
    tick();
    const id = setInterval(tick, 20000);
    return () => clearInterval(id);
  }, []);

  // Questões REVELADAS até agora (cascata): do roteiro do episódio, da 1ª até a atual.
  const revealedQuestions = pblStage === "question" ? roteiroQuestions.slice(0, Math.max(1, shownCount)) : [];

  // O controlador transmite as questões já reveladas: o aluno renderiza a MESMA cascata.
  // Reenvia a cada 3s enquanto na etapa, para quem entrar depois. Fora da etapa, envia
  // lista vazia (limpa no aluno).
  useEffect(() => {
    if (recorder || !amController || !room) return;   // gravador só espelha; controlador transmite
    const inQ = pblStage === "question";
    const send = () => {
      // Só transmite com a conexão LiveKit pronta — senão publishData rejeita com
      // "PC manager is closed" (durante reconexão) e polui o console de erros.
      if (room.state !== ConnectionState.Connected) return;
      try {
        const list = inQ ? roteiroQuestions.slice(0, reveal + 1) : [];
        const data = new TextEncoder().encode(JSON.stringify({
          source: "webconf", type: "plenary-questions", list, total: plenaryTotal,
        }));
        room.localParticipant?.publishData(data, { reliable: true })?.catch(() => {});
      } catch { /* */ }
    };
    send();
    if (!inQ) return;
    const id = setInterval(send, 3000);
    return () => clearInterval(id);
  }, [amController, room, pblStage, reveal, roteiroQuestions, plenaryTotal]);

  // Progresso da revelação: o controlador transmite quantos cards já apareceram, para
  // aluno e moderador verem exatamente a mesma tela. Reenvia a cada 3s (quem entra no
  // meio da etapa pega o estado atual).
  useEffect(() => {
    if (recorder || !amController || !room || revealItems.length < 2) return;
    const send = () => {
      if (room.state !== ConnectionState.Connected) return;
      try {
        const data = new TextEncoder().encode(JSON.stringify({
          source: "webconf", type: "stage-reveal", stage: pblStage, count: reveal + 1,
        }));
        room.localParticipant?.publishData(data, { reliable: true })?.catch(() => {});
      } catch { /* */ }
    };
    send();
    const id = setInterval(send, 3000);
    return () => clearInterval(id);
  }, [amController, room, pblStage, reveal, revealItems.length]);

  // Filtro do gráfico: o controlador transmite as séries ocultas → o gráfico do aluno
  // fica sincronizado. Reenvia a cada 3s enquanto o gráfico está no ar (quem entra
  // depois já pega o filtro atual).
  useEffect(() => {
    if (recorder || !amController || !room || !chartForStaff) return;
    const send = () => {
      if (room.state !== ConnectionState.Connected) return;
      try {
        const data = new TextEncoder().encode(JSON.stringify({
          source: "webconf", type: "chart-filter", hidden: chartFilter,
        }));
        room.localParticipant?.publishData(data, { reliable: true })?.catch(() => {});
      } catch { /* */ }
    };
    send();
    const id = setInterval(send, 3000);
    return () => clearInterval(id);
  }, [amController, room, chartForStaff, chartFilter]);

  // Botão sequencial: executa a AÇÃO da etapa atual e avança para a próxima.
  // O conteúdo de cada etapa (sinopse, questões, riscos) vem do ROTEIRO do episódio e
  // é renderizado aqui mesmo — não há mais pacote externo para avançar em paralelo.
  const runStep = async () => {
    setStageBusy(true);
    const id = pblStage;
    const idx = stepIndex(id);
    const next = STEP_IDS[Math.min(idx + 1, STEP_IDS.length - 1)];
    try {
      switch (id) {
        case "session_start":
          if (!pblClass?.active && pblRoster?.activity_id) await sdk.openpbl.startClass(roomId, pblRoster.activity_id).catch(() => {});
          await goToStep(next);
          break;
        case "registration_open":
          // Registro abre por padrão ao iniciar a aula; aqui só avança a etapa.
          await goToStep(next);
          break;
        case "registration_close":
          await sdk.openpbl.closeRegistration(roomId).catch(() => {});
          await sdk.openpbl.syncGroups(roomId).catch(() => {});
          await goToStep(next);
          break;
        case "synopsis":
          // Sinopse revelada card a card; só depois do último segue para o aquecimento.
          if (reveal + 1 < roteiroSinopse.length) { setReveal(reveal + 1); break; }
          await goToStep(next);
          break;
        case "groups":
          // As questões orientadoras aparecem uma a uma ANTES de dividir os grupos —
          // é com elas em tela que a turma vai discutir nas salas.
          if (reveal + 1 < roteiroOrientadoras.length) { setReveal(reveal + 1); break; }
          if (!breakoutOpen) {
            // Divide os grupos (API OpenPBL) e abre as salas com contagem de 10 min.
            // NÃO avança de etapa: durante a discussão a tela continua sendo a do
            // Aquecimento — antes o cursor pulava para a plenária e os alunos viam,
            // dentro do grupo, um conteúdo que só deveria aparecer depois.
            await sdk.openpbl.syncGroups(roomId).catch(() => {});
            await sdk.breakouts.open(roomId, 600).catch(() => {});
            break;
          }
          // Grupos abertos: encerra as salas e só então segue para a plenária.
          await sdk.breakouts.close(roomId).catch(() => {});
          await goToStep(next);
          break;
        case "plenary":
          // Todos voltam à sala principal para a discussão em plenária.
          if (breakoutOpen) await sdk.breakouts.close(roomId).catch(() => {});
          await goToStep(next);
          break;
        case "question": {
          // Plenária: cada clique revela mais uma questão do roteiro (cascata), e a lista
          // revelada é transmitida por dados para os alunos verem a mesma tela.
          // 1ª questão: inicia a gravação em BACKGROUND (o egress pode demorar a responder;
          // NÃO pode bloquear o avanço do sequenciador — era isso que travava o botão).
          if (reveal === 0 && !recording) { setRecording(true); sdk.recording.start(roomId).catch(() => setRecording(false)); }
          const n = reveal + 1;
          setReveal(n);
          if (n >= plenaryTotal) await goToStep("situational");
          break;
        }
        case "situational":
          // Os riscos aparecem um a um; revelado o último, o clique JÁ libera o
          // questionário e entra na etapa. Antes a liberação só acontecia ao SAIR
          // dela — ou seja, um clique depois do botão anunciar "Liberar…", o que
          // fazia o questionário abrir só quando o botão já dizia "Mostrar gráfico".
          if (reveal + 1 < situationalItems.length) { setReveal(reveal + 1); break; }
          await sdk.openpbl.release(roomId, "risks").catch(() => {});
          await goToStep(next);
          break;
        case "release_risks":
          // Questionário já liberado ao entrar aqui; este clique só passa a mostrar
          // o gráfico também para os alunos.
          await goToStep(next);
          break;
        case "show_chart":
          // Passa a exibir o gráfico também para os alunos (só muda a etapa).
          await goToStep(next);
          break;
        case "closing":
          if (recording) { setRecording(false); await sdk.recording.stop(roomId).catch(() => setRecording(true)); }
          // Mesma correção do questionário de riscos: libera as percepções ao ENTRAR
          // na etapa de feedback, e não ao sair dela.
          await sdk.openpbl.release(roomId, "perceptions").catch(() => {});
          await goToStep(next);
          break;
        case "release_feedback":
          await goToStep(next);
          break;
        case "done":
          // Última tarefa do sequenciador: abre o confirm de ENCERRAR A SALA (não avança).
          setConfirmEnd(true);
          break;
      }
    } finally { setStageBusy(false); }
  };

  return (
    <>
      <header className="vr-header">
        <div className="vr-brand">
          {brand?.logo_url
            ? <img className="vr-logo vr-logo-img" src={brand.logo_url} alt="" />
            : <div className="vr-logo">V</div>}
          {/* Na aula OpenPBL (facilitador OU aluno): em vez do nome da sala, mostra o
              horário e o class-code (mesmo header para todos). O olho de ocultar o
              código é exclusivo do host/moderador; o código em si respeita a
              visibilidade de cada papel (showBrandCode). */}
          {pblActive ? (
            <div className="vr-brandmeta">
              <span className="vr-clock">{clock}</span>
              {showBrandCode && (
                <>
                  <span className="vr-brandmeta-sep">|</span>
                  {/* Class-code como TEXTO puro (mesma fonte do relógio) — clicável
                      (copia + amplia) com o ícone ao lado. */}
                  <button type="button" className="vr-code-plain" onClick={onCodeChipClick} title="Clique para copiar e ampliar o código">
                    <span className="vr-clock">{codeCopied ? "Copiado!" : classCode}</span>
                    <span className="vr-code-plain-ico" aria-hidden>{I.copy}</span>
                  </button>
                  {amStaff && (
                    <button
                      type="button" className="vr-code-plain-eye" onClick={toggleCodeForStudents}
                      title={codeHiddenForStudents ? "Mostrar o código para os alunos" : "Ocultar o código para os alunos"}
                    >
                      {codeHiddenForStudents ? I.eyeOff : I.eye}
                    </button>
                  )}
                </>
              )}
            </div>
          ) : (
            <div className="vr-title">{roomTitle || pubTitle || brand?.product_name || "Sala de vídeo"}</div>
          )}
        </div>

        {/* Centro: SOMENTE a atividade atual — IGUAL para facilitador e aluno (o
            class-code foi para a esquerda; o ▶ é só do controlador, na direita). */}
        {pblActive && <ActivityBar stage={pblStage} head={curStep.head} />}

        {/* PROGRESSO: só nas etapas em que a turma está respondendo algo. Fora
            delas o número não significa nada e só ocuparia a tela. */}
        {pblActive && pblStage === "release_risks" && (
          <ProgressoDasRespostas
            feitos={pblRoster?.progresso?.riscos ?? 0}
            total={pblRoster?.progresso?.alunos ?? 0}
            oque="responderam os riscos"
          />
        )}
        {pblActive && pblStage === "release_feedback" && (
          <ProgressoDasRespostas
            feitos={pblRoster?.progresso?.pares ?? 0}
            total={pblRoster?.progresso?.alunos ?? 0}
            oque="avaliaram os colegas"
          />
        )}

        {/* A PERGUNTA DA CADÊNCIA, para a sala inteira. Fica fora do bloco do
            host: quem vota é a turma, e o host vê o mesmo cartão para saber o
            que está sendo perguntado (ele não vota -- tem o botão).

            `presentes` vem de `progresso.alunos`, não da contagem da lista: a
            lista traz quem já entrou nesta sala algum dia (o backend nunca
            fecha `left_at`), e o cartão diria "3 de 47" numa turma de 12 --
            sendo que 47 não é o número que a cadência apura. Ver `_presentes`. */}
        {pblActive && pblClass?.vote_ends_at && (
          <CartaoDoVoto
            roomId={roomId}
            fechaEm={pblClass.vote_ends_at}
            meuVoto={identity ? (pblClass.votes || {})[identity] : undefined}
            votos={Object.keys(pblClass.votes || {}).length}
            presentes={pblRoster?.progresso?.alunos ?? 0}
          />
        )}

        {/* Canto superior direito: controles da chamada (antes eram uma pílula
            centralizada no rodapé), cronômetro/contagem e Encerrar sala. */}
        <div className="vr-header-right">
          {/* Sequenciador do facilitador (Encerrar Registro / ▶ / etc.) + toggle do
              gráfico — movidos do centro para a direita, junto dos controles. */}
          {/* A CHAVE DA AUTOMAÇÃO. Automático é o padrão; este botão é o
              freio de mão -- o host assume quando a cadência vai mal, sem
              precisar de deploy. Só o controlador, como o resto do
              sequenciador. */}
          {pblHost && (amController || recorder) && pblActive && (
            <button
              className="vr-actbar-ghost"
              data-auto={pblClass?.auto_mode !== false || undefined}
              title={pblClass?.auto_mode !== false
                ? "A sala está avançando sozinha. Clique para assumir o controle."
                : "Você está conduzindo. Clique para devolver à condução automática."}
              onClick={async () => {
                try {
                  setPblClass(await sdk.openpbl.setCadencia(
                    roomId, pblClass?.auto_mode === false));
                } catch { /* o estado volta no próximo polling */ }
              }}
            >
              {pblClass?.auto_mode !== false ? "Automático" : "Manual"}
            </button>
          )}
          {pblHost && chartAvailable && (
            <button className="vr-actbar-ghost" onClick={() => setChartHidden((h) => !h)} title="Mostrar/ocultar o gráfico de riscos">
              {chartHidden ? "Mostrar gráfico" : "Ocultar gráfico"}
            </button>
          )}
          {/* Só o CONTROLADOR dirige o sequenciador. Outros host/moderadores veem
              "Assumir controle" (evita dois apresentando ao mesmo tempo). */}
          {pblHost && !amController && !recorder && (
            <button className="vr-seq-label" title="Assumir o controle da apresentação/sequenciador"
              onClick={() => identity && setRole({ set_controller: true, controller: identity })}>
              Assumir controle
            </button>
          )}
          {pblHost && (amController || recorder) && (
            <div className="vr-seq" data-danger={pblStage === "done" || undefined}>
              {/* Só exibe a etapa atual — avançar é exclusividade do botão ao lado,
                  para não disparar a ação sem querer ao ler o rótulo. */}
              <span className="vr-seq-label" title={seqLabel}>
                {stageBusy ? "…" : seqLabel}
              </span>
              {/* Tooltip = a MESMA ação anunciada no rótulo: o texto genérico de antes
                  não dizia o que o clique ia disparar. */}
              <button className="vr-seq-go" onClick={runStep} disabled={stageBusy} title={seqLabel}>
                {I.playTri}
              </button>
            </div>
          )}
          <ControlBar
            isStaff={amStaff}
            scorm={scorm}
            panel={panel}
            setPanel={setPanel}
            onOpenSettings={() => setSettingsOpen(true)}
            settingsActive={settingsOpen}
            peopleCount={participants.length}
            boardActive={showBoard}
            onToggleBoard={toggleBoard}
            recording={recording}
            onToggleRecording={toggleRecording}
            showQr={!!packageUrl}
            onQr={() => setQrOpen(true)}
            onLeaveRoom={onLeaveRoom}
          />
          <div className="vr-meta">
            {recording && <span className="vr-rec">REC</span>}
            {/* Encerrar sala: fora do OpenPBL, botão dedicado. No OpenPBL ele vira a
                ÚLTIMA tarefa do sequenciador (etapa "done"). */}
            {amStaff && !pblHost && (
              <button className="vr-end-btn" onClick={() => setConfirmEnd(true)} title="Encerrar a sala para todos">Encerrar sala</button>
            )}
          </div>
        </div>
      </header>

      {breakout.isStaff
        ? <BreakoutHostBar roomId={roomId} active={breakout.active} message={breakout.message} onEnter={breakout.enter} onLeave={breakout.leave} />
        : (breakout.active || breakout.message) && (
          <BreakoutBanner
            groupName={breakout.active?.groupName ?? null}
            endsAt={breakout.active?.endsAt ?? null}
            message={breakout.message}
            onLeave={breakout.leave}
          />
        )}

      {/* Coluna própria à esquerda (câmera do facilitador + class code no topo,
          apresentação abaixo) — IGUAL para host e aluno. O aluno recebe a
          apresentação transmitida (screen-share) na MESMA posição do iframe do host. */}
      <div className="vr-stage" data-pbl={scorm && !pblActive ? "1" : undefined}>
        {/* Durante os grupos, o facilitador NÃO vê a apresentação — só os grupos. */}
        {pblActive && !(amStaff && breakoutOpen) && (
          <aside className="vr-pbl-side">
            <PblPanelHeader roster={pblRoster} localIsStaff={amStaff} localIdentity={identity} pinned={pinned} />
            {amStaff ? (
              chartForStaff ? (
                // "Liberar análise de riscos" em diante: SÓ o gráfico (ocultável).
                !chartHidden ? (
                  <div className="vr-pbl-present-big">
                    <RiskChart roomId={roomId} canFilter showPending
                      hiddenSeries={chartFilter} onToggleSeries={toggleChartSeries}
                      onSeries={setChartSeries} />
                  </div>
                ) : null
              ) : showDimensions ? (
                // Análise situacional: cascata dos RISCOS a avaliar (roteiro do episódio).
                <div className="vr-pbl-present-big" {...bannerProps}><RiskDimensions roomId={roomId} dims={situationalItems} shown={shownCount} /></div>
              ) : showQuestionsArea ? (
                <div className="vr-pbl-present-big" {...bannerProps}>
                  {revealedQuestions.length ? (
                    <QuestionCascade items={revealedQuestions} total={plenaryTotal}
                      label="Questões para reflexão" progress emphasize
                      intro={rIntroQuestoes(roteiro)} />
                  ) : (
                    <div className="vr-pbl-question">
                      <div className="vr-pbl-question-waiting">
                        Nenhuma questão no roteiro deste episódio.
                        <span>Preencha as questões da plenária em Gerenciar produção → Roteiro da Videoconferência.</span>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                // Demais etapas: a tela do roteiro correspondente.
                <div className="vr-pbl-present-big" {...bannerProps}><RoteiroStage stage={pblStage} roteiro={roteiro} shown={shownCount} /></div>
              )
            ) : pblStage === "session_start" ? (
              // Pré-atividades: SÓ o facilitador vê a abertura/roteiro. Para o aluno a
              // área de apresentação fica limpa até o facilitador iniciar a sessão.
              <div className="vr-pbl-present-big" />
            ) : chartForStudents ? (
              // "Mostrar gráfico" em diante: o aluno também vê o gráfico — segue o filtro
              // do facilitador e não vê a contagem de pendentes.
              <div className="vr-pbl-present-big">
                <RiskChart roomId={roomId} hiddenSeries={chartFilter} />
              </div>
            ) : showDimensions ? (
              // Análise situacional: aluno vê a MESMA cascata dos riscos.
              <div className="vr-pbl-present-big" {...bannerProps}><RiskDimensions roomId={roomId} dims={situationalItems} shown={shownCount} /></div>
            ) : showQuestionsArea ? (
              // Aluno na plenária: as questões reveladas chegam por dados (o facilitador
              // comanda o ritmo), e a cascata é a mesma.
              plenaryQ?.list?.length ? (
                <div className="vr-pbl-present-big" {...bannerProps}>
                  <QuestionCascade items={plenaryQ.list} total={plenaryQ.total}
                    label="Questões para reflexão" progress emphasize
                    intro={rIntroQuestoes(roteiro)} />
                </div>
              ) : null
            ) : chartForStaff ? (
              // release_risks (antes de "Mostrar gráfico"): o aluno está respondendo no
              // celular — mostra as instruções da Análise situacional, não o gráfico.
              <div className="vr-pbl-present-big" {...bannerProps}><RoteiroStage stage={pblStage} roteiro={roteiro} shown={shownCount} /></div>
            ) : (
              // Demais etapas: o aluno vê exatamente a mesma tela do facilitador.
              <div className="vr-pbl-present-big" {...bannerProps}><RoteiroStage stage={pblStage} roteiro={roteiro} shown={shownCount} /></div>
            )}
          </aside>
        )}
        <div className="vr-grid-wrap">
          {amStaff && breakoutOpen && !breakout.active
            ? <HostBreakoutOverview roomId={roomId} onEnter={breakout.enter} />
            : scorm
              ? <OpenPblStudentsGrid roomId={roomId} roster={pblRoster} localIsStaff={amStaff} localIdentity={identity} sideScreen={pblActive} />
              : <VideoGrid />}
          {showBoard && (
            <div className="vr-wb-overlay">
              <Suspense fallback={<div className="vr-center">Carregando quadro…</div>}>
                <Whiteboard roomId={roomId} canEdit={canEditBoard} isHost={amStaff} />
              </Suspense>
            </div>
          )}
          {/* Chat/Participantes: overlay glass DENTRO da área dos alunos — o leve
              desfoque fica só sobre os alunos; a apresentação e o facilitador (coluna
              à esquerda / topo) permanecem 100% visíveis. */}
          {(panel === "chat" || panel === "people") && (
            <aside className="vr-panel vr-panel-overlay">
              {scorm && !pblActive && <PblPanelHeader roster={pblRoster} localIsStaff={amStaff} localIdentity={identity} pinned={pinned} />}
              <div className="vr-tabs">
                <button className="vr-tab" data-active={panel === "chat"} onClick={() => setPanel("chat")}>Chat</button>
                <button className="vr-tab" data-active={panel === "people"} onClick={() => setPanel("people")}>
                  Participantes ({participants.length})
                </button>
              </div>
              <div className="vr-panel-body">
                {panel === "chat" && <RoomChat roomId={roomId} senderName={senderName} channel={breakout.active?.groupId} channelLabel={breakout.active?.groupName} />}
                {panel === "people" && (
                  <PeoplePanel
                    roomId={roomId} isStaff={amStaff} inviteUrl={inviteUrl}
                    roster={pblRoster} moderators={moderators} controller={controller}
                    pinned={pinned} localIdentity={identity} onSetRole={setRole}
                  />
                )}
              </div>
            </aside>
          )}
        </div>
        {panel && (panel === "breakout" || panel === "scorm") && amStaff && (
          // Seção dedicada (host): SUBSTITUI o painel, in-flow (empurra a grade).
          <aside className="vr-panel">
            <div className="vr-panel-head">
              <span className="vr-panel-title">{panel === "breakout" ? "Grupos" : "OpenPBL"}</span>
              <button className="vr-panel-x" onClick={() => setPanel("chat")} title="Voltar ao chat" aria-label="Voltar">✕</button>
            </div>
            <div className="vr-panel-body">
              {panel === "breakout" && (
                <Suspense fallback={<div className="vr-center" style={{ padding: 32 }}>Carregando…</div>}>
                  <BreakoutPanel
                    roomId={roomId} identity={identity} displayName={senderName}
                    activeGroupId={breakout.active?.groupId ?? null}
                    onVisit={breakout.enter} onLeaveVisit={breakout.leave}
                  />
                </Suspense>
              )}
              {panel === "scorm" && scorm && <ScormPanel roomId={roomId} />}
            </div>
          </aside>
        )}
      </div>

      {settingsOpen && amStaff && (
        <div className="vr-sheet-backdrop" onClick={() => setSettingsOpen(false)}>
          <div className="vr-sheet" onClick={(e) => e.stopPropagation()}>
            <div className="vr-sheet-head">
              <h3>Configurações</h3>
              <button className="vr-sheet-close" onClick={() => setSettingsOpen(false)} aria-label="Fechar">✕</button>
            </div>
            <div className="vr-sheet-body">
              <RoomSettings roomId={roomId} />
            </div>
          </div>
        </div>
      )}

      {confirmEnd && (
        <div className="vr-modal-backdrop" onClick={() => setConfirmEnd(false)}>
          <div className="vr-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Encerrar a sala?</h3>
            <p>Isso desconecta todos os participantes e finaliza a sessão para todos.</p>
            <div className="vr-modal-actions">
              <button className="vr-modal-btn" onClick={() => setConfirmEnd(false)}>Cancelar</button>
              <button className="vr-modal-btn vr-modal-btn-danger" onClick={doEndRoom}>Encerrar sala</button>
            </div>
          </div>
        </div>
      )}

      {/* QR code do Pacote de Classe: o aluno escaneia (celular) ou clica em "Abrir
          pacote" (navegador). Gerado da URL informada na criação da sala. */}
      {qrOpen && packageUrl && (
        <div className="vr-modal-backdrop" onClick={() => setQrOpen(false)}>
          <div className="vr-modal vr-qr-modal" onClick={(e) => e.stopPropagation()}>
            <button className="vr-sheet-close" onClick={() => setQrOpen(false)} aria-label="Fechar">✕</button>
            <h3>Pacote da atividade</h3>
            <p>Aponte a câmera do celular para o QR code para abrir o pacote.</p>
            <div className="vr-qr-code">
              <QRCodeSVG value={packageUrl} size={240} includeMargin level="M" />
            </div>
            <a className="vr-modal-btn vr-modal-btn-primary" href={packageUrl} target="_blank" rel="noopener noreferrer">
              Abrir pacote no navegador
            </a>
          </div>
        </div>
      )}

      {/* Popup grande do class code — abre ao clicar no chip (facilitador transmite
          p/ todos) e, para o aluno, automaticamente ao entrar no registro. O aluno
          não vê o popup se o facilitador tiver ocultado o código para a turma. */}
      {pblActive && classCode && codeExpand && (amStaff || !codeHiddenForStudents) && (
        <div className="vr-sheet-backdrop" onClick={closeCodePopup}>
          <div className="vr-pbl-code-big" onClick={(e) => e.stopPropagation()}>
            <button className="vr-sheet-close vr-pbl-big-x" onClick={closeCodePopup} aria-label="Fechar">✕</button>
            <span className="vr-pbl-code-label">Class code</span>
            <button type="button" className="vr-pbl-code-huge" onClick={copyClassCode} title="Clique para copiar">{classCode}</button>
            <span className="vr-pbl-code-hint">{codeCopied ? "Copiado! ✓" : "toque para copiar"}</span>
          </div>
        </div>
      )}
    </>
  );
}

function VideoGrid() {
  const tracks = useTracks(
    [{ source: Track.Source.Camera, withPlaceholder: true }, { source: Track.Source.ScreenShare, withPlaceholder: false }],
    { onlySubscribed: false },
  );

  // Spotlight: se alguém compartilha tela, ela ocupa tudo, os demais somem e a
  // câmera de quem compartilha (o facilitador) vira um box pequeno sobreposto.
  const screen = tracks.find((t) => t.source === Track.Source.ScreenShare && t.publication);
  if (screen) {
    const sharerCam = tracks.find(
      (t) => t.source === Track.Source.Camera && t.participant.identity === screen.participant.identity,
    );
    return (
      <div className="vr-spotlight">
        <ParticipantTile trackRef={screen} className="vr-spotlight-main" />
        {sharerCam && (
          <div className="vr-spotlight-pip">
            <ParticipantTile trackRef={sharerCam} />
          </div>
        )}
      </div>
    );
  }

  const cams = tracks.filter((t) => t.source === Track.Source.Camera && !isBroadcast(t.participant.identity) && !isEgress(t.participant.identity));
  return (
    <GridLayout tracks={cams} style={{ height: "100%" }}>
      <TileComSinal />
    </GridLayout>
  );
}

/* ── Roteiro da Videoconferência: leitura e renderização ──────────────────────
 *
 * O conteúdo do encontro (sinopse, questões, riscos e os textos fixos de cada
 * seção) vem congelado na sala, montado pelo CustomerApp a partir do roteiro do
 * episódio. Antes isso era um pacote SCORM embutido por iframe e transmitido aos
 * alunos por screen-share recortado; agora a própria sala É a apresentação, então
 * facilitador e aluno renderizam exatamente a mesma tela.
 */

/** Campo de texto do roteiro (vazio se ausente). */
function rTexto(r: RoteiroSnapshot | null, name: string): string {
  const v = r?.campos?.[name];
  return typeof v === "string" ? v.trim() : "";
}

/** Campo de lista do roteiro, já sem os itens em branco que o formulário permite. */
function rLista(r: RoteiroSnapshot | null, name: string): string[] {
  const v = r?.campos?.[name];
  return Array.isArray(v) ? v.map((x) => String(x || "").trim()).filter(Boolean) : [];
}

/** Textos fixos de uma seção do roteiro (iguais em todo episódio). */
function rBlocos(r: RoteiroSnapshot | null, key: string): RoteiroBlocoFixo[] {
  return r?.secoes?.find((s) => s.key === key)?.blocosFixos ?? [];
}

/** Título de uma seção — vem do snapshot (`schema.ts` é a fonte única), não do código. */
function rTitulo(r: RoteiroSnapshot | null, key: string): string {
  return r?.secoes?.find((s) => s.key === key)?.titulo ?? "";
}

/** Dos blocos fixos da plenária, o 1º ("o objetivo da discussão") abre a etapa da
 *  plenária e os seguintes explicam a DINÂMICA das questões — estes pertencem à tela
 *  "Questões para reflexão". Salas sem roteiro (ou com um bloco só) não têm intro. */
function rIntroQuestoes(r: RoteiroSnapshot | null): RoteiroBlocoFixo[] {
  return rBlocos(r, "plenaria").slice(1);
}

/** Blocos de texto fixo de uma seção — o "corpo" da tela de cada etapa. */
function RoteiroBlocos({ blocos }: { blocos: RoteiroBlocoFixo[] }) {
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
function RoteiroStage({ stage, roteiro, shown = 1 }: {
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

  // Demais etapas: seção do roteiro correspondente.
  const secao = stage === "registration_open" || stage === "registration_close" ? "abertura"
    : stage === "synopsis" ? "revisitando"
      : stage === "groups" ? "aquecimento"
        : stage === "plenary" ? "plenaria"
          : stage === "release_risks" ? "analise"
            : "feedback";   // closing (o gráfico costuma cobrir esta etapa)
  // Na plenária só entra o 1º bloco (o objetivo). Os seguintes descrevem a dinâmica
  // das questões e abrem a etapa "Questões para reflexão" (ver `rIntroQuestoes`).
  const blocos = stage === "plenary" ? rBlocos(roteiro, secao).slice(0, 1) : rBlocos(roteiro, secao);

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

/** Sequenciador do facilitador — "ETAPAS E ATIVIDADES DO ENCONTRO". Um único botão
 *  sequencial percorre a lista: cada clique executa a AÇÃO da etapa (e manda um
 *  "next" ao pacote, best-effort) e avança para a próxima. `head` = título da fase
 *  (a "atividade atual" exibida). */
interface StepDef { id: OpenPblStage; action: string; head: string; }
const STEPS: StepDef[] = [
  { id: "session_start",      action: "Iniciar a sessão",                     head: "Abertura" },
  { id: "registration_open",  action: "Iniciar o registro",                   head: "Registro de Presença" },
  { id: "registration_close", action: "Encerrar o registro",                  head: "Registro de Presença" },
  { id: "synopsis",           action: "Revisitar a situação-problema",        head: "Situação-problema" },
  { id: "groups",             action: "Divisão em grupos",                    head: "Aquecimento" },
  // `head` = nome da seção do roteiro que está NA TELA (docx "VIDEOCONFERÊNCIA
  // INTEGRADA"). Em plenary/question a tela mostra a seção "Discussão em Plenária" —
  // antes o rótulo dizia "Aquecimento"/"Plenária" e não batia com o texto exibido.
  { id: "plenary",            action: "Discussão em plenária",                head: "Discussão em Plenária" },
  { id: "question",           action: "Questões para reflexão",                head: "Discussão em Plenária" },
  { id: "situational",        action: "Análise situacional",                  head: "Análise situacional" },
  { id: "release_risks",      action: "Liberar análise individual de riscos", head: "Análise situacional" },
  { id: "show_chart",         action: "Mostrar gráfico",                      head: "Análise situacional" },
  { id: "closing",            action: "Encerramento",                         head: "Análise situacional" },
  { id: "release_feedback",   action: "Liberar feedback de interação",        head: "Feedback e encerramento" },
  { id: "done",               action: "Encerrar a sala",                      head: "Encerramento" },
];
const STEP_IDS = STEPS.map((s) => s.id);
const stepIndex = (id: OpenPblStage) => STEP_IDS.indexOf(id);
const stepDef = (id: OpenPblStage): StepDef => STEPS.find((s) => s.id === id) ?? STEPS[0];
const PLENARY_QUESTIONS = 5;   // "Questão para reflexão" repete 5× antes de "Análise situacional"

/** Chip do class-code que vive ao lado da etapa atual (barra do facilitador e faixa
 *  do aluno). Clicar copia o código e abre o popup grande. O facilitador ainda pode
 *  ocultar/reexibir o código para os alunos (ícone de olho). */
function ClassCodeChip({ code, copied, closed, onClick, onToggleHidden, hiddenForStudents }: {
  code: string; copied: boolean; closed: boolean;
  onClick: () => void; onToggleHidden?: () => void; hiddenForStudents?: boolean;
}) {
  return (
    <div className="vr-code-chip-wrap">
      <button type="button" className="vr-code-chip" onClick={onClick} title="Clique para copiar e ampliar o código">
        <span className="vr-code-chip-cap" data-copied={copied || undefined}>{copied ? "Copiado!" : "Class code"}</span>
        <span className="vr-code-chip-val">{code}</span>
        <span className="vr-code-chip-ico" aria-hidden>{I.copy}</span>
      </button>
      {onToggleHidden && (
        <button
          type="button" className="vr-code-chip-eye" onClick={onToggleHidden}
          title={hiddenForStudents ? "Mostrar o código para os alunos" : "Ocultar o código para os alunos"}
        >
          {hiddenForStudents ? I.eyeOff : I.eye}
        </button>
      )}
      {closed && <span className="vr-code-chip-closed">registro encerrado</span>}
    </div>
  );
}

/** Centro do header do facilitador: SOMENTE o nome da atividade atual + progresso.
 *  O class-code foi para a esquerda (marca) e o botão ▶ para a direita (controles). */
function ActivityBar({ stage, head }: { stage: OpenPblStage; head: string }) {
  const step = stepIndex(stage);
  return (
    <div className="vr-actbar">
      <div className="vr-actbar-info">
        <span className="vr-actbar-name">{head}</span>
        {step >= 0 && (
          <div className="vr-actbar-prog" aria-hidden>
            <i style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
          </div>
        )}
      </div>
    </div>
  );
}

/* Séries do radar. Paleta categórica escolhida PARA O FUNDO ESCURO da sala: a antiga
 * (Ant Design, feita para fundo branco) reprovava em contraste e em separação para
 * daltonismo sobre `--vr-bg`. Ordem fixa — a cor segue a série, não a posição, então
 * filtrar pela legenda não repinta as que sobraram. */
const RISK_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

/** Quebra um rótulo em até 2 linhas (por palavra), elipsando o excedente. */
function wrapText(text: string, max: number): string[] {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const t = cur ? `${cur} ${w}` : w;
    if (t.length <= max || !cur) cur = t;
    else { lines.push(cur); cur = w; }
  }
  if (cur) lines.push(cur);
  return lines;   // sem corte: o nome da dimensão aparece inteiro (quebra em quantas linhas precisar)
}

/** Gráfico do Questionário de Riscos — radar agregado por grupo, atualizando a
 *  cada 5s (mesmo dado do gráfico do chat do pacote). */
function RiskChart({ roomId, canFilter = false, showPending = false, hiddenSeries = [], onToggleSeries, onSeries }: {
  roomId: string;
  /** Quem controla a sessão filtra pela legenda; o aluno só segue o filtro (mas explora o gráfico). */
  canFilter?: boolean;
  /** Quantos alunos ainda faltam responder — informação de condução, só para o facilitador. */
  showPending?: boolean;
  /** Filtro da legenda — sincronizado: o do facilitador replica no gráfico do aluno. */
  hiddenSeries?: string[]; onToggleSeries?: (name: string) => void;
  /** Nomes das séries disponíveis — a sala precisa deles para começar tudo oculto. */
  onSeries?: (names: string[]) => void;
}) {
  const sdk = useSDK();
  const [chart, setChart] = useState<any | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "wait" | "nodim">("loading");

  useEffect(() => {
    let alive = true;
    const load = () =>
      sdk.openpbl.riskChart(roomId).then((r) => {
        if (!alive) return;
        if (r.available && r.chart) { setChart(r.chart); setStatus("ok"); }
        else if (r.reason === "no_dimensions_id") setStatus("nodim");
        else setStatus((s) => (s === "ok" ? "ok" : "wait"));   // mantém o último gráfico bom
      }).catch(() => { if (alive) setStatus((s) => (s === "ok" ? "ok" : "wait")); });
    load();
    const iv = setInterval(load, 5000);
    return () => { alive = false; clearInterval(iv); };
  }, [roomId]);

  // Séries montadas ANTES dos early-returns: os nomes são publicados por efeito
  // (`onSeries`) e hook não pode ficar depois de um return condicional.
  const series = useMemo(() => {
    const out: { name: string; color: string; values: number[] }[] = [];
    if (!chart) return out;
    if (Array.isArray(chart.baseGrades) && chart.baseGrades.length) out.push({ name: "Base do Curador", color: RISK_COLORS[0], values: chart.baseGrades });
    if (Array.isArray(chart.classAverage) && chart.classAverage.length) out.push({ name: "Média da Turma", color: RISK_COLORS[1], values: chart.classAverage });
    (chart.groups || []).forEach((g: any, i: number) => {
      out.push({ name: g.name || `Grupo ${i + 1}`, color: RISK_COLORS[(i + 2) % RISK_COLORS.length], values: g.grades || [] });
    });
    return out;
  }, [chart]);

  const serieNames = series.map((x) => x.name).join("|");
  useEffect(() => { onSeries?.(serieNames ? serieNames.split("|") : []); }, [serieNames]);

  if (status === "nodim")
    return <div className="vr-chart-msg">Selecione o <b>conjunto de dimensões</b> na criação da sala para exibir o gráfico de riscos.</div>;
  if (!chart)
    return <div className="vr-chart-msg">{status === "loading" ? "Carregando gráfico…" : "Aguardando as respostas dos alunos…"}</div>;

  const dims: string[] = chart.dimensions || [];

  const total = chart.total || 0;
  const completed = chart.completed || 0;          // respondeu TODAS as dimensões
  const pending = Math.max(0, total - completed);
  return (
    <div className="vr-chart-wrap">
      <div className="vr-chart-title">
        Radar de Riscos
        {/* Contagem só no gráfico do facilitador — o aluno não precisa ver quem falta. */}
        {showPending && (
          <span className="vr-chart-sub"> · {completed} concluíram · <b className="vr-chart-pending">{pending} faltam</b></span>
        )}
      </div>
      <RadarSvg dims={dims} series={series} max={12} answered={chart.answered || []} total={total}
        canFilter={canFilter} hidden={hiddenSeries} onToggle={onToggleSeries} />
    </div>
  );
}

/** Cascata de cards revelados progressivamente — usada nas questões da plenária e
 *  nas dimensões de risco (Análise situacional). Facilitador e aluno renderizam o
 *  MESMO componente (o aluno recebe a lista por dados), então a UI/animação fica num
 *  só lugar. `progress` mostra os passos (●) no cabeçalho e `emphasize` realça o card
 *  mais recente — ambos fazem sentido só na revelação progressiva (plenária). */
function QuestionCascade({ items, total, label, icon, progress = false, emphasize = false, inline = false, intro }: {
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

/** Cascata dos RISCOS a avaliar (etapa "Análise situacional"). Vêm do roteiro do
 *  episódio; em salas antigas, das dimensões escolhidas na criação — e, na falta das
 *  duas, do /risk-chart. Usa o MESMO componente/CSS/animação das questões da
 *  plenária (QuestionCascade com progress + emphasize). */
function RiskDimensions({ roomId, dims: roomDims, shown = 1 }: {
  roomId: string; dims?: string[];
  /** Quantos riscos já foram revelados pelo facilitador. */
  shown?: number;
}) {
  const sdk = useSDK();
  const [fetched, setFetched] = useState<string[]>([]);
  const hasRoomDims = !!(roomDims && roomDims.length);
  useEffect(() => {
    if (hasRoomDims) return;   // veio da criação da sala → não depende de aluno
    let alive = true;
    const load = () => sdk.openpbl.riskChart(roomId).then((r: any) => {
      const d = r?.chart?.dimensions;
      if (alive && Array.isArray(d) && d.length) setFetched(d);
    }).catch(() => {});
    load();
    const iv = setInterval(load, 5000);
    return () => { alive = false; clearInterval(iv); };
  }, [roomId, hasRoomDims]);
  const dims = hasRoomDims ? (roomDims as string[]) : fetched;
  return dims.length ? (
    // Mesma animação/CSS das questões da plenária: mesmo componente e mesmas flags
    // (progress + emphasize) → cards idênticos, com dots e realce do último.
    <QuestionCascade items={dims.slice(0, shown)} total={dims.length}
      label="Principais riscos" progress emphasize />
  ) : (
    <div className="vr-pbl-question">
      <div className="vr-pbl-question-waiting">Carregando dimensões de risco…</div>
    </div>
  );
}

function RadarSvg({ dims, series, max, answered, total, canFilter = false, hidden = [], onToggle }: {
  dims: string[]; series: { name: string; color: string; values: number[] }[]; max: number;
  answered: number[]; total: number;
  /** Legenda clicável — só quem controla a sessão filtra; o aluno explora o gráfico
   *  (hover/tooltip) mas apenas SEGUE o filtro aplicado pelo facilitador. */
  canFilter?: boolean;
  /** Séries ocultas — estado SINCRONIZADO (o filtro do facilitador replica no aluno). */
  hidden?: string[]; onToggle?: (name: string) => void;
}) {
  const N = dims.length;
  const [hover, setHover] = useState<number | null>(null);
  const hiddenSet = new Set(hidden);
  const vis = series.filter((s) => !hiddenSet.has(s.name));
  if (N < 3) return <div className="vr-chart-msg">Dimensões insuficientes para o radar.</div>;
  // Canvas de referência só para posicionar: o viewBox final é recortado no conteúdo
  // (ver `vb` abaixo), então estas medidas não deixam sobra na tela.
  const W = 460, H = 380, cx = W / 2, cy = H / 2, R = 116;
  const angle = (i: number) => (Math.PI * 2 * i) / N - Math.PI / 2;
  const point = (i: number, v: number): [number, number] => {
    const r = (Math.max(0, Math.min(max, v)) / max) * R;
    return [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))];
  };
  const poly = (vals: number[]) => dims.map((_, i) => point(i, vals[i] ?? 0).join(",")).join(" ");
  // Anéis de 2 em 2 (0 → max), cada um rotulado com o seu valor.
  const RING_STEP = 2;
  const rings: number[] = [];
  for (let v = RING_STEP; v <= max + 0.001; v += RING_STEP) rings.push(v);

  // Rótulo de cada dimensão: posição calculada uma vez só, porque também é ela que
  // define os limites reais do desenho (abaixo).
  const labels = dims.map((d, i) => {
    const lx = cx + (R + 10) * Math.cos(angle(i));
    const ly = cy + (R + 10) * Math.sin(angle(i));
    const anchor = Math.abs(lx - cx) < 12 ? "middle" : lx > cx ? "start" : "end";
    const lines = wrapText(d, 16);
    const rows = lines.length + 1;                        // + a linha do contador
    // O bloco cresce SEMPRE afastando-se do centro: acima do eixo ele sobe (senão a
    // última linha desce em cima do anel e da sua escala), abaixo ele desce, e nas
    // laterais fica centrado no vértice.
    const y0 = ly < cy - 8 ? ly - (rows - 1) * 11
      : ly > cy + 8 ? ly
        : ly - ((rows - 1) * 11) / 2;
    return { lx, ly, anchor, lines, rows, y0 } as const;
  });

  // viewBox colado no desenho: o polígono nunca preenche o retângulo (ainda mais com
  // nº ímpar de dimensões), e a faixa morta que sobra empurraria a legenda e o tooltip
  // para longe do gráfico. Aqui a caixa é a união do radar com os rótulos.
  let x0 = cx - R, x1 = cx + R, yA = cy - R, yB = cy + R;
  labels.forEach((L) => {
    const w = Math.max(...L.lines.map((l) => l.length), 9) * 4.7;   // ~largura do texto
    const lx0 = L.anchor === "middle" ? L.lx - w / 2 : L.anchor === "start" ? L.lx : L.lx - w;
    x0 = Math.min(x0, lx0); x1 = Math.max(x1, lx0 + w);
    yA = Math.min(yA, L.y0 - 8); yB = Math.max(yB, L.y0 + (L.rows - 1) * 11 + 4);
  });
  const PAD = 4;
  const vb = `${x0 - PAD} ${yA - PAD} ${x1 - x0 + PAD * 2} ${yB - yA + PAD * 2}`;
  return (
    <div className="vr-radar">
      <svg viewBox={vb} className="vr-radar-svg" onMouseLeave={() => setHover(null)}>
        {rings.map((v, ri) => (
          <polygon key={ri} className="vr-radar-ring" points={dims.map((_, i) => point(i, v).join(",")).join(" ")} />
        ))}
        {/* escala: valor de cada anel, lido no eixo de cima */}
        {rings.map((v, ri) => {
          const [rx, ry] = point(0, v);
          return <text key={`rv${ri}`} className="vr-radar-ringval" x={rx + 4} y={ry + 3}>{v}</text>;
        })}
        {labels.map(({ lx, anchor, lines: nameLines, y0 }, i) => {
          const [ax, ay] = point(i, max);
          return (
            <g key={i}>
              <line className={hover === i ? "vr-radar-axis on" : "vr-radar-axis"} x1={cx} y1={cy} x2={ax} y2={ay} />
              <text className={hover === i ? "vr-radar-label on" : "vr-radar-label"} x={lx} y={y0} textAnchor={anchor}>
                {nameLines.map((ln, k) => <tspan key={k} x={lx} dy={k === 0 ? 0 : 11}>{ln}</tspan>)}
                <tspan x={lx} dy={11} className="vr-radar-count">{answered[i] ?? 0}/{total} resp.</tspan>
              </text>
            </g>
          );
        })}
        {vis.map((s, si) => (
          <polygon key={si} className="vr-radar-series" points={poly(s.values)}
            style={{ stroke: s.color, fill: s.color, fillOpacity: hover === null ? 0.12 : 0.06 }} />
        ))}
        {/* vértice destacado na dimensão sob o mouse */}
        {hover !== null && vis.map((s, si) => {
          const [px, py] = point(hover, s.values[hover] ?? 0);
          // O anel do vértice é a cor do FUNDO (classe → var CSS): separa marcadores
          // sobrepostos de séries diferentes. Fixo em branco, ele brilhava no escuro.
          return <circle key={`pt${si}`} className="vr-radar-pt" cx={px} cy={py} r={4} fill={s.color} />;
        })}
        {/* áreas invisíveis por dimensão (hover) — o aluno também explora o gráfico */}
        {dims.map((_, i) => {
          const [ex, ey] = point(i, max);
          return <line key={`hit${i}`} x1={cx} y1={cy} x2={ex} y2={ey} stroke="transparent" strokeWidth={34}
            style={{ cursor: "pointer" }} onMouseEnter={() => setHover(i)} />;
        })}
      </svg>
      {/* Slot fixo entre o radar e a legenda: o tooltip sempre sai AQUI, nunca por cima
          do gráfico. O espaço fica reservado mesmo sem hover, senão o radar redimensiona
          a cada passada do mouse. */}
      <div className="vr-radar-tipslot">
        {hover !== null && (
          <div className="vr-radar-tip">
            <div className="vr-radar-tip-h">{dims[hover]}</div>
            <div className="vr-radar-tip-a">{answered[hover] ?? 0}/{total} responderam</div>
            {vis.map((s) => (
              <div key={s.name} className="vr-radar-tip-row">
                <i style={{ background: s.color }} /><span className="vr-radar-tip-n">{s.name}</span>
                <b>{(s.values[hover] ?? 0).toFixed(1)}</b>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="vr-radar-legend">
        {series.map((s) => (canFilter ? (
          <button key={s.name} type="button" className="vr-radar-leg" data-off={hiddenSet.has(s.name) || undefined}
            onClick={() => onToggle?.(s.name)} title="Clique para mostrar/ocultar esta série (replica para os alunos)">
            <i style={{ background: s.color }} />{s.name}
          </button>
        ) : (
          // Aluno: legenda informativa (sem clique), refletindo o filtro do facilitador.
          <span key={s.name} className="vr-radar-leg" data-static="1" data-off={hiddenSet.has(s.name) || undefined}>
            <i style={{ background: s.color }} />{s.name}
          </span>
        )))}
      </div>
    </div>
  );
}

/** Nº de colunas que faz os `count` tiles preencherem melhor o container.
 *  Sem isto o grid usa uma largura mínima fixa: com muitos alunos ele estoura
 *  em linhas e vira uma pilha rolável em vez de distribuir no espaço livre. */
const TILE_RATIO = 16 / 10;
const TILE_GAP = 6;   // precisa casar com o `gap` de .vr-pbl-students (room.css)

function useFittedCols(count: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [cols, setCols] = useState(1);

  useEffect(() => {
    const el = ref.current;
    if (!el || count === 0) return;
    const compute = () => {
      const { width: W, height: H } = el.getBoundingClientRect();
      if (W <= 0 || H <= 0) return;
      let best = 1;
      let bestSide = 0;
      for (let c = 1; c <= count; c++) {
        const rows = Math.ceil(count / c);
        const tw = (W - TILE_GAP * (c - 1)) / c;
        const th = (H - TILE_GAP * (rows - 1)) / rows;
        // lado útil do tile respeitando 16:10 — o maior vence
        const side = Math.min(tw, th * TILE_RATIO);
        if (side > bestSide) { bestSide = side; best = c; }
      }
      setCols(best);
    };
    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, [count]);

  return { ref, cols };
}

/** Grade dos ALUNOS (área principal, à direita) com borda de status:
 *  🟢 dentro do pacote · 🔴 fora · badge ✓ = registrou presença com o class-code.
 *  O facilitador e o código ficam no header do painel (PblPanelHeader). */
/** Qualidade de conexão do participante, reagindo ao evento do LiveKit.
 *  Usa a propriedade `connectionQuality` + ParticipantEvent — API estável do
 *  livekit-client (não depende de componente do components-react). */
function useConnQuality(participant?: { connectionQuality?: ConnectionQuality; on: Function; off: Function }) {
  const [q, setQ] = useState<ConnectionQuality>(
    (participant?.connectionQuality as ConnectionQuality) ?? ConnectionQuality.Unknown);
  useEffect(() => {
    if (!participant) return;
    const update = () => setQ((participant.connectionQuality as ConnectionQuality) ?? ConnectionQuality.Unknown);
    update();
    participant.on(ParticipantEvent.ConnectionQualityChanged, update);
    return () => { participant.off(ParticipantEvent.ConnectionQualityChanged, update); };
  }, [participant]);
  return q;
}

/** Barrinhas de sinal (3 níveis) no canto do frame. Verde = boa, âmbar = média,
 *  vermelho = ruim/perdida. Some quando o LiveKit ainda não mediu (Unknown). */
function SignalBars({ participant }: { participant?: any }) {
  const q = useConnQuality(participant);
  if (q === ConnectionQuality.Unknown) return null;
  const nivel = q === ConnectionQuality.Excellent ? 3 : q === ConnectionQuality.Good ? 2 : q === ConnectionQuality.Poor ? 1 : 0;
  const rotulo = nivel === 3 ? "Conexão boa" : nivel === 2 ? "Conexão média" : nivel === 1 ? "Conexão ruim" : "Sem conexão";
  return (
    <span className="vr-sig" data-nivel={nivel} title={rotulo} aria-label={rotulo}>
      <i /><i /><i />
    </span>
  );
}

/** Tile da grade comum + barrinhas. O GridLayout clona este filho para cada track e
 *  passa o track por contexto — daí lermos o participante de lá. */
function TileComSinal() {
  const ref = useMaybeTrackRefContext();
  return (
    <div className="vr-tile-sig">
      <ParticipantTile />
      <SignalBars participant={ref?.participant} />
    </div>
  );
}

/* ── Progresso das respostas ──────────────────────────────────────────────────
 *
 * Quantos da turma já responderam o Questionário de Riscos (etapa
 * `release_risks`) e quantos já avaliaram os pares (`release_feedback`).
 *
 * ## Por que ele existe agora, e não antes
 *
 * Com um facilitador humano, "todo mundo terminou?" era uma pergunta que
 * alguém fazia em voz alta. Com a cadência decidindo sozinha, esse número é o
 * único sinal de que a sala está prestes a avançar com metade da turma pela
 * metade -- e é por ele que quem supervisiona decide assumir o manual antes,
 * em vez de descobrir depois.
 *
 * Aparece para TODOS, não só para o host: numa etapa com prazo, saber que
 * faltam três pessoas é informação de quem está esperando, não privilégio de
 * quem conduz.
 */
function ProgressoDasRespostas({ feitos, total, oque }: {
  feitos: number; total: number; oque: string;
}) {
  // Sem alunos não há progresso a mostrar — e `0 de 0` com a barra cheia (ou
  // vazia) afirmaria algo sobre uma turma que não existe.
  if (!total) return null;
  const pct = Math.round((feitos / total) * 100);
  return (
    <div className="vr-prog" title={`${feitos} de ${total} ${oque}`}>
      <span className="vr-prog__rotulo">{oque}</span>
      <span className="vr-prog__barra">
        <i style={{ width: `${pct}%` }} data-cheio={feitos >= total || undefined} />
      </span>
      <span className="vr-prog__num">{feitos}/{total}</span>
    </div>
  );
}

/* ── Cadência: "podemos seguir?" ──────────────────────────────────────────────
 *
 * O cartão que substitui a pessoa perguntando "todo mundo terminou?". Aparece
 * quando o tempo da etapa esgota e vale 15 segundos.
 *
 * ## Quem não vota conta como "não"
 *
 * Está escrito no cartão, e não só no servidor. Um voto cujo peso o eleitor
 * desconhece não é um voto -- e aqui o silêncio é a opção MAIS forte: basta
 * metade da turma não clicar para o encontro ficar onde está.
 *
 * ## O relógio é do SERVIDOR
 *
 * A contagem na tela desce a partir de `vote_ends_at`, que vem pronto. Contar
 * 15 a partir do momento em que o cartão apareceu daria um prazo diferente
 * para cada aluno, conforme a latência -- e quem recebesse o estado atrasado
 * veria a janela fechar antes da conta dele acabar.
 */
function CartaoDoVoto({ roomId, fechaEm, meuVoto, votos, presentes }: {
  roomId: string;
  fechaEm: string;
  meuVoto: boolean | undefined;
  votos: number;
  presentes: number;
}) {
  const sdk = useSDK();
  const [enviando, setEnviando] = useState(false);
  const [restam, setRestam] = useState(() =>
    Math.max(0, Math.ceil((new Date(fechaEm).getTime() - Date.now()) / 1000)));

  useEffect(() => {
    const t = setInterval(() => {
      setRestam(Math.max(0, Math.ceil((new Date(fechaEm).getTime() - Date.now()) / 1000)));
    }, 250);
    return () => clearInterval(t);
  }, [fechaEm]);

  if (restam <= 0) return null;

  const votar = async (sim: boolean) => {
    setEnviando(true);
    /* Falhar em silêncio é aceitável AQUI, e só aqui: não votar já tem um
       significado definido ("não"), então um erro de rede leva ao mesmo lugar
       que o aluno teria chegado ficando quieto. Um alerta no meio da aula
       custaria mais que o que informaria. */
    try { await sdk.openpbl.votar(roomId, sim); } catch { /* vale como não */ }
    setEnviando(false);
  };

  return (
    <div className="vr-voto" role="dialog" aria-label="Podemos seguir?">
      <div className="vr-voto__topo">
        <span className="vr-voto__titulo">Podemos seguir?</span>
        <span className="vr-voto__relogio" aria-live="off">{restam}s</span>
      </div>

      {meuVoto === undefined ? (
        <>
          <div className="vr-voto__botoes">
            <button type="button" className="vr-voto__sim" disabled={enviando}
                    onClick={() => votar(true)}>Sim, pode seguir</button>
            <button type="button" className="vr-voto__nao" disabled={enviando}
                    onClick={() => votar(false)}>Ainda não</button>
          </div>
          {/* O PESO DO SILÊNCIO, dito antes de o aluno decidir não clicar. */}
          <p className="vr-voto__aviso">Quem não responder conta como “ainda não”.</p>
        </>
      ) : (
        <p className="vr-voto__meu">
          Você respondeu <strong>{meuVoto ? "sim" : "ainda não"}</strong>.
          Aguardando a turma.
        </p>
      )}

      {/* Progresso sem revelar o VOTO de ninguém: quantos responderam, não o
          que cada um respondeu. Numa sala com câmera aberta, saber quem votou
          não é anônimo -- saber o quê seria constrangimento. */}
      <p className="vr-voto__placar">{votos} de {presentes} já responderam</p>
    </div>
  );
}

/* ── Avaliação de desempenho na plenária ──────────────────────────────────────
 *
 * O facilitador clica com o botão DIREITO na câmera do aluno e dá a nota ali
 * mesmo. Trocar de tela no meio da plenária — abrir outra aba, procurar o aluno
 * numa lista, voltar — é a diferença entre a avaliação acontecer e não
 * acontecer: a janela em que ele lembra do que o aluno acabou de fazer dura
 * segundos.
 *
 * A nota vale para a PARTICIPAÇÃO, que é uma só. Quando ele dá 4 ("destacada"),
 * o menu pergunta em QUAL critério — porque um 4 vale 4 só nesse critério e 3
 * nos outros. Sem essa pergunta, um único destaque levantaria os cinco eixos
 * juntos e o radar do aluno deixaria de mostrar onde ele é forte, que é a única
 * coisa que um radar serve para mostrar.
 */
const NOTAS_DE_PARTICIPACAO: { valor: 1 | 2 | 3 | 4; rotulo: string; ajuda: string }[] = [
  { valor: 4, rotulo: "Participação DESTACADA", ajuda: "destacou-se em um critério" },
  { valor: 3, rotulo: "Participação pró-ativa", ajuda: "participou espontaneamente" },
  { valor: 2, rotulo: "Participação reativa", ajuda: "participou quando chamado" },
  { valor: 1, rotulo: "Participação resistente", ajuda: "não participou mesmo chamado" },
];

function MenuAvaliacao({ roomId, alvo, criterios, onFechar }: {
  roomId: string;
  alvo: { identity: string; nome: string; x: number; y: number };
  criterios: string[];
  onFechar: () => void;
}) {
  const sdk = useSDK();
  // `null` = escolhendo a nota; 4 = escolhendo o critério do destaque.
  const [etapa, setEtapa] = useState<null | 4>(null);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");

  // Fecha ao clicar fora ou com Esc. Sem isto o menu fica preso sobre a câmera
  // do aluno — tapando justamente quem o facilitador está avaliando.
  useEffect(() => {
    const sair = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      onFechar();
    };
    document.addEventListener("mousedown", sair);
    document.addEventListener("keydown", sair);
    return () => {
      document.removeEventListener("mousedown", sair);
      document.removeEventListener("keydown", sair);
    };
  }, [onFechar]);

  async function enviar(nota: 1 | 2 | 3 | 4, destaque: number | null) {
    setSalvando(true);
    setErro("");
    try {
      await sdk.openpbl.avaliarDesempenho(roomId, { identity: alvo.identity, nota, destaque });
      onFechar();
    } catch (e: any) {
      /* O ERRO FICA NA TELA, e o menu não fecha. Um clique que não gravou e
         sumiu faria o facilitador avaliar a turma inteira achando que
         registrou — e ninguém descobriria até o aluno não ver nota nenhuma. */
      setErro(String(e?.message || e) || "não foi possível registrar");
      setSalvando(false);
    }
  }

  return (
    <div
      className="vr-aval-menu"
      style={{ left: alvo.x, top: alvo.y }}
      onMouseDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
      role="menu"
      aria-label={`Avaliar ${alvo.nome}`}
    >
      <div className="vr-aval-menu__titulo">
        {etapa === 4 ? "Destacou-se em qual critério?" : `Avaliar ${alvo.nome}`}
      </div>

      {etapa !== 4 && NOTAS_DE_PARTICIPACAO.map((n) => (
        <button
          key={n.valor}
          type="button"
          className="vr-aval-menu__item"
          disabled={salvando}
          onClick={() => (n.valor === 4 ? setEtapa(4) : enviar(n.valor, null))}
        >
          <span className="vr-aval-menu__rotulo">{n.rotulo}</span>
          <span className="vr-aval-menu__ajuda">{n.ajuda}</span>
        </button>
      ))}

      {etapa === 4 && (
        <>
          {criterios.map((c, i) => (
            <button key={c + i} type="button" className="vr-aval-menu__item"
                    disabled={salvando} onClick={() => enviar(4, i)}>
              <span className="vr-aval-menu__rotulo">{c}</span>
            </button>
          ))}
          {/* SEM CRITÉRIO é uma escolha legítima, não um erro: o facilitador
              pode achar que o aluno se destacou sem saber dizer em quê, e
              obrigá-lo a escolher um produziria um destaque inventado. */}
          <button type="button" className="vr-aval-menu__item vr-aval-menu__item--fraco"
                  disabled={salvando} onClick={() => enviar(4, null)}>
            <span className="vr-aval-menu__rotulo">Sem critério específico</span>
            <span className="vr-aval-menu__ajuda">vale 3 em todos os eixos</span>
          </button>
          <button type="button" className="vr-aval-menu__voltar"
                  disabled={salvando} onClick={() => setEtapa(null)}>← voltar</button>
        </>
      )}

      {erro && <div className="vr-aval-menu__erro">{erro}</div>}
    </div>
  );
}

function OpenPblStudentsGrid({ roomId, roster, localIsStaff, localIdentity, strip, sideScreen }: { roomId: string; roster: any | null; localIsStaff: boolean; localIdentity?: string; strip?: boolean; sideScreen?: boolean }) {
  const tracks = useTracks(
    [{ source: Track.Source.Camera, withPlaceholder: true }, { source: Track.Source.ScreenShare, withPlaceholder: false }],
    { onlySubscribed: false },
  );

  // Screen-share de OUTRO participante = o professor transmitindo a apresentação.
  // Em aula OpenPBL (`sideScreen`) a transmissão vai para a coluna esquerda
  // (.vr-pbl-side), então aqui a grade mostra só os alunos.
  const screen = !strip && !sideScreen && tracks.find(
    (t) => t.source === Track.Source.ScreenShare && t.publication && !t.participant.isLocal,
  );

  const byId: Record<string, any> = {};
  (roster?.students || []).forEach((s: any) => { byId[s.identity] = s; });
  const isHostTile = (identity: string) =>
    byId[identity]?.is_staff ?? (identity === localIdentity && localIsStaff);

  const studentTiles = tracks.filter((t) => t.source === Track.Source.Camera && !isHostTile(t.participant.identity) && !isBroadcast(t.participant.identity) && !isEgress(t.participant.identity));

  // O strip é uma faixa horizontal rolável; só a grade cheia se ajusta ao espaço.
  const { ref: gridRef, cols } = useFittedCols(strip ? 0 : studentTiles.length);

  const sdk = useSDK();
  const [avaliando, setAvaliando] = useState<{ identity: string; nome: string; x: number; y: number } | null>(null);
  const [criterios, setCriterios] = useState<string[]>([]);

  /* Os critérios são buscados UMA vez, e só para o facilitador: eles vêm do
     template do Encontro e não mudam durante uma plenária. Buscar na abertura
     de cada menu seria uma chamada ao elearn por clique direito. */
  useEffect(() => {
    if (!localIsStaff || criterios.length) return;
    let vivo = true;
    sdk.openpbl.criteriosDesempenho(roomId)
      .then((r: { criterios: string[] }) => { if (vivo) setCriterios(r?.criterios || []); })
      .catch(() => { /* sem nomes o menu ainda avalia; só não oferece destaque */ });
    return () => { vivo = false; };
  }, [roomId, localIsStaff, criterios.length, sdk]);

  const grid = (
    <div
      ref={gridRef}
      className={strip ? "vr-pbl-students vr-pbl-students--strip" : "vr-pbl-students"}
      style={strip ? undefined : { gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {studentTiles.length === 0 && <div className="vr-pbl-empty">Aguardando alunos…</div>}
      {studentTiles.map((t) => {
        const st = byId[t.participant.identity];
        return (
          <div
            key={`${t.participant.identity}-st`}
            className="vr-pbl-tile"
            data-pkg={st?.in_package ? "in" : "out"}
            /* SÓ O FACILITADOR, e só sobre aluno. Esconder o menu do aluno não
               é segurança — a rota exige host no servidor —, é não oferecer a
               ele uma porta que vai bater na cara. */
            onContextMenu={localIsStaff ? (e) => {
              e.preventDefault();
              /* A posição é LIMITADA aqui, e não no CSS: o menu tem
                 tamanho conhecido e o clique pode ser na borda da tela — sem
                 isto ele abre metade fora da janela, que é onde ficam as
                 câmeras das pontas numa turma cheia. */
              const LARG = 300, ALT = 280;
              setAvaliando({
                identity: t.participant.identity,
                nome: (t.participant.name || "").trim() || "este aluno",
                x: Math.min(e.clientX, Math.max(8, window.innerWidth - LARG - 8)),
                y: Math.min(e.clientY, Math.max(8, window.innerHeight - ALT - 8)),
              });
            } : undefined}
            title={localIsStaff ? "Botão direito: avaliar participação" : undefined}
          >
            <ParticipantTile trackRef={t} />
            <SignalBars participant={t.participant} />
            {st?.registered && <span className="vr-pbl-reg" title="Registrado na sessão (class-code inserido)">✓</span>}
          </div>
        );
      })}
      {avaliando && (
        <MenuAvaliacao
          roomId={roomId}
          alvo={avaliando}
          criterios={criterios}
          onFechar={() => setAvaliando(null)}
        />
      )}
    </div>
  );

  // Professor transmitindo → o aluno vê a apresentação à ESQUERDA (mesmo container
  // e tamanho que o professor vê o iframe) e os alunos à direita, espelhando o layout.
  if (screen) {
    return (
      <div className="vr-pbl-main">
        <div className="vr-pbl-present-big">
          <ParticipantTile trackRef={screen} className="vr-present-share" />
        </div>
        <div className="vr-pbl-students-col">{grid}</div>
      </div>
    );
  }

  return grid;
}

/** Header do painel (OpenPBL): câmera do facilitador destacada. O class-code saiu
 *  daqui e passou a viver ao lado da etapa atual (ver ClassCodeChip / popup). */
function PblPanelHeader({ roster, localIsStaff, localIdentity, pinned }: { roster: any | null; localIsStaff: boolean; localIdentity?: string; pinned?: string | null }) {
  const tracks = useTracks([{ source: Track.Source.Camera, withPlaceholder: true }], { onlySubscribed: false });

  const byId: Record<string, any> = {};
  (roster?.students || []).forEach((s: any) => { byId[s.identity] = s; });
  const isHostTile = (identity: string) =>
    byId[identity]?.is_staff ?? (identity === localIdentity && localIsStaff);
  // Câmera na área de conteúdo: a FIXADA (pinned) quando definida; senão, o anfitrião.
  // O egress (gravador) NUNCA é candidato: como não está no roster, o fallback
  // `identity === localIdentity` o elegeria como host e a gravação mostrava o tile
  // vazio do próprio gravador no lugar da câmera do facilitador.
  const pinnedTrack = pinned ? tracks.find((t) => t.participant.identity === pinned) : null;
  const hostTrack = pinnedTrack
    || tracks.find((t) => !isEgress(t.participant.identity) && isHostTile(t.participant.identity));

  if (!hostTrack) return null;
  // Só o primeiro nome sobre a câmera — o nome completo continua no painel de
  // participantes. A label nativa do LiveKit é ocultada por CSS (.vr-pbl-head-cam
  // .lk-participant-metadata) e este chip a substitui, tapando o mínimo do rosto.
  const firstName = (hostTrack.participant.name || "").trim().split(/\s+/)[0] || "";
  return (
    <div className="vr-pbl-head" data-wide="1">
      <div className="vr-pbl-head-cam">
        <ParticipantTile trackRef={hostTrack} />
        <SignalBars participant={hostTrack.participant} />
        {firstName && <span className="vr-pbl-head-name">{firstName}</span>}
      </div>
    </div>
  );
}

function PeoplePanel({ roomId, isStaff, inviteUrl, roster, moderators, controller, pinned, localIdentity, onSetRole }: {
  roomId: string; isStaff: boolean; inviteUrl: string | null;
  roster?: any | null; moderators?: string[]; controller?: string | null; pinned?: string | null;
  localIdentity?: string; onSetRole?: (body: any) => void;
}) {
  const sdk = useSDK();
  const participants = useParticipants().filter((p) => !isBroadcast(p.identity) && !isEgress(p.identity));
  const [copied, setCopied] = useState(false);
  // Estado local do que o host bloqueou por participante (true = bloqueado).
  const [blocked, setBlocked] = useState<Record<string, { screen?: boolean }>>({});

  const mods = moderators || [];
  const byId: Record<string, any> = {};
  (roster?.students || []).forEach((s: any) => { byId[s.identity] = s; });
  // Host/moderador = staff no roster OU promovido. Só esses podem ser fixados/controlar.
  const isHostOrMod = (id: string) => !!byId[id]?.is_staff || mods.includes(id) || (id === localIdentity && isStaff);
  const isMod = (id: string) => mods.includes(id);

  const mod = (id: string, action: string) => sdk.rooms.moderate(roomId, action, { user_id: id }).catch(() => {});
  const setPerm = (id: string, key: "screen_share", allow: boolean) => {
    sdk.rooms.setPermissions(roomId, id, { [`allow_${key}`]: allow }).catch(() => {});
    setBlocked((b) => ({ ...b, [id]: { ...b[id], screen: !allow } }));
  };
  // confirm() nativo não funciona no embed (iframe cross-origin) → ação direta.
  const kick = (id: string, _nm: string) => mod(id, "force-kick");

  return (
    <>
      {isStaff && inviteUrl && (
        <div className="vr-invite">
          <label>Link de convite</label>
          <div className="vr-invite-row">
            <input readOnly value={inviteUrl} onFocus={(e) => e.currentTarget.select()} />
            <button className="vr-send" onClick={() => { navigator.clipboard?.writeText(inviteUrl); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
              {copied ? "✓" : "Copiar"}
            </button>
          </div>
        </div>
      )}
      {isStaff && <LobbyPanel roomId={roomId} />}
      <div className="vr-people">
        {participants.map((p) => {
          const nm = p.name || p.identity;
          const screenBlocked = !!blocked[p.identity]?.screen;
          return (
            <div className="vr-person" key={p.sid}>
              <div className="vr-person-top">
                <div className="vr-avatar">{nm.slice(0, 1).toUpperCase()}</div>
                <span className="vr-person-name">{nm} {p.isLocal && <span className="vr-you">(você)</span>}</span>
                <span className={p.isMicrophoneEnabled ? "" : "vr-muted"}>{p.isMicrophoneEnabled ? I.mic : I.micOff}</span>
              </div>
              {isStaff && !p.isLocal && (
                <div className="vr-person-ctrls">
                  <button className="vr-mini" onClick={() => mod(p.identity, "force-mute")} title="Mutar microfone">Mutar</button>
                  <button className="vr-mini" onClick={() => mod(p.identity, "force-camera-off")} title="Desligar câmera">Câmera</button>
                  <button className="vr-mini" data-on={!screenBlocked} onClick={() => setPerm(p.identity, "screen_share", screenBlocked)} title="Permitir/bloquear compartilhar tela">
                    {screenBlocked ? "Liberar tela" : "Bloquear tela"}
                  </button>
                  <button className="vr-mini vr-mini-danger" onClick={() => kick(p.identity, nm)} title="Remover da sala">Remover</button>
                  {/* Papéis: moderador (poderes de host), fixar câmera e passar controle. */}
                  <button className="vr-mini" data-on={isMod(p.identity) || undefined}
                    onClick={() => onSetRole?.(isMod(p.identity) ? { remove_moderator: p.identity } : { add_moderator: p.identity })}
                    title="Moderador tem os mesmos poderes do anfitrião">
                    {isMod(p.identity) ? "Remover moderador" : "Tornar moderador"}
                  </button>
                  {isHostOrMod(p.identity) && (
                    <button className="vr-mini" data-on={pinned === p.identity || undefined}
                      onClick={() => onSetRole?.({ set_pinned: true, pinned: pinned === p.identity ? null : p.identity })}
                      title="Fixar a webcam desta pessoa na área de conteúdo">
                      {pinned === p.identity ? "Fixada ✓" : "Fixar na tela"}
                    </button>
                  )}
                  {isHostOrMod(p.identity) && controller !== p.identity && (
                    <button className="vr-mini"
                      onClick={() => onSetRole?.({ set_controller: true, controller: p.identity })}
                      title="Passar o controle do sequenciador/apresentação para esta pessoa">
                      Dar controle
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

/* ---------------- Room settings (host) ---------------- */
function RoomSettings({ roomId }: { roomId: string }) {
  const sdk = useSDK();
  const [p, setP] = useState({ allow_mic: true, allow_camera: true, allow_screen_share: true, allow_whiteboard_edit: false });

  useEffect(() => {
    sdk.rooms.get(roomId).then((r: any) => setP({
      allow_mic: r.allow_mic, allow_camera: r.allow_camera,
      allow_screen_share: r.allow_screen_share, allow_whiteboard_edit: r.allow_whiteboard_edit,
    })).catch(() => {});
    return sdk.subscribe(roomId, (e, payload) => { if (e === "room-permissions") setP((prev) => ({ ...prev, ...payload })); });
  }, [roomId]);

  const toggle = (key: keyof typeof p) => {
    const next = !p[key];
    setP((prev) => ({ ...prev, [key]: next }));
    sdk.rooms.setRoomPermissions(roomId, { [key]: next }).catch(() => {});
  };

  const row = (key: keyof typeof p, label: string, sub: string) => (
    <div className="vr-setrow">
      <div><div className="vr-setrow-l">{label}</div><div className="vr-setrow-s">{sub}</div></div>
      <button className="tg" data-on={p[key]} onClick={() => toggle(key)} aria-pressed={p[key]} />
    </div>
  );

  return (
    <div className="vr-settings">
      <p className="vr-settings-hint">Permissões padrão dos participantes durante a chamada. Aplica a todos (você, anfitrião, não é afetado) e vale para quem entrar depois.</p>
      {row("allow_mic", "Microfone", "Participantes podem falar")}
      {row("allow_camera", "Câmera", "Participantes podem abrir a câmera")}
      {row("allow_screen_share", "Compartilhar tela", "Participantes podem compartilhar a tela")}
      {row("allow_whiteboard_edit", "Editar quadro", "Participantes podem desenhar no quadro")}
    </div>
  );
}

/* ---------------- OpenPBL / SCORM (host) ---------------- */
const SCORM_STATUS: Record<string, string> = {
  "ativo": "no pacote", "concluido": "concluído", "saiu": "saiu do pacote",
  "nao-abriu": "não abriu", "erro": "—",
};

/** Aula OpenPBL ao vivo: gera o class-code aqui dentro (substitui o pacote
 *  PRESENTATION do facilitador), libera questionários e encerra o registro. */
function ClassControl({ roomId }: { roomId: string }) {
  const sdk = useSDK();
  const [cls, setCls] = useState<any | null>(null);
  const [activityId, setActivityId] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sentChat, setSentChat] = useState(false);
  const [groupInfo, setGroupInfo] = useState<string | null>(null);

  useEffect(() => {
    sdk.openpbl.classState(roomId).then(setCls).catch(() => setCls({ active: false }));
    return sdk.subscribe(roomId, (event, payload) => {
      if (event === "openpbl-class") setCls(payload);
    });
  }, [roomId]);

  const groupMsg = (n: number) =>
    n > 0 ? `${n} grupo(s) criado(s) — veja/abra na aba Grupos.`
          : "Nenhum grupo retornado ainda. Se alunos acabaram de entrar, sincronize em instantes.";

  // Encerrar registro: a API OpenPBL monta os grupos; o backend já reflete nos
  // breakouts. Aqui confirmamos a contagem (e cobre alunos que entraram no fim).
  const closeReg = async () => {
    setBusy("close"); setErr(null); setGroupInfo(null);
    try {
      setCls(await sdk.openpbl.closeRegistration(roomId));
      const res = await sdk.openpbl.syncGroups(roomId);
      setGroupInfo(groupMsg(res.groups));
    } catch (e: any) { setErr(e?.message?.slice(0, 180) || "Falha ao encerrar"); }
    finally { setBusy(null); }
  };

  const resync = async () => {
    setBusy("resync"); setErr(null);
    try { const res = await sdk.openpbl.syncGroups(roomId); setGroupInfo(groupMsg(res.groups)); }
    catch (e: any) { setErr(e?.message?.slice(0, 180) || "Falha ao sincronizar"); }
    finally { setBusy(null); }
  };

  const run = async (key: string, fn: () => Promise<any>) => {
    setBusy(key); setErr(null);
    try { setCls(await fn()); }
    catch (e: any) { setErr(e?.message?.slice(0, 180) || "Falha na operação"); }
    finally { setBusy(null); }
  };

  const start = () => {
    const a = activityId.trim();
    if (!a) { setErr("Informe o ID da atividade (courseActivityId)."); return; }
    run("start", () => sdk.openpbl.startClass(roomId, a));
  };
  const sendCode = () => {
    if (!cls?.presentation_code) return;
    sdk.chat.send(roomId, `Código da sessão: ${cls.presentation_code} — digite no seu pacote OpenPBL para registrar presença.`).catch(() => {});
    setSentChat(true); setTimeout(() => setSentChat(false), 2500);
  };

  if (cls === null) return <div className="vr-scorm-empty">Carregando…</div>;

  if (!cls.active) {
    return (
      <div className="vr-class-ctl">
        <div className="vr-class-head">Aula OpenPBL</div>
        <p className="vr-scorm-hint">Gere o código da sessão direto daqui — sem precisar abrir o pacote de apresentação.</p>
        <div className="vr-scorm-relay-row">
          <input value={activityId} onChange={(e) => setActivityId(e.target.value)}
            placeholder="ID da atividade (courseActivityId)"
            onKeyDown={(e) => { if (e.key === "Enter") start(); }} />
          <button onClick={start} disabled={busy === "start"}>{busy === "start" ? "Gerando…" : "Iniciar aula"}</button>
        </div>
        {err && <p className="vr-class-err">{err}</p>}
      </div>
    );
  }

  return (
    <div className="vr-class-ctl">
      <div className="vr-class-head">Aula OpenPBL</div>
      <div className="vr-class-code-box">
        <span className="vr-class-code-label">Código da sessão</span>
        <span className="vr-class-code">{cls.presentation_code}</span>
        <button className="vr-mini" onClick={sendCode}>{sentChat ? "Enviado ✓" : "Enviar no chat"}</button>
      </div>
      <div className="vr-class-actions">
        <button className="vr-class-btn" data-done={cls.released_dimensions}
          disabled={busy !== null || cls.released_dimensions}
          onClick={() => run("risks", () => sdk.openpbl.release(roomId, "risks"))}>
          {cls.released_dimensions ? "✓ Riscos liberado" : busy === "risks" ? "Liberando…" : "Liberar Questionário de Riscos"}
        </button>
        <button className="vr-class-btn" data-done={cls.released}
          disabled={busy !== null || cls.released}
          onClick={() => run("perceptions", () => sdk.openpbl.release(roomId, "perceptions"))}>
          {cls.released ? "✓ Percepções liberado" : busy === "perceptions" ? "Liberando…" : "Liberar Questionário de Percepções"}
        </button>
        <button className="vr-class-btn vr-class-btn-danger" data-done={!cls.checking_open}
          disabled={busy !== null || !cls.checking_open}
          onClick={closeReg}>
          {!cls.checking_open ? "✓ Registro encerrado" : busy === "close" ? "Encerrando…" : "Encerrar registro"}
        </button>
        {!cls.checking_open && (
          <button className="vr-class-btn" disabled={busy !== null} onClick={resync}>
            {busy === "resync" ? "Sincronizando…" : "Sincronizar grupos"}
          </button>
        )}
      </div>
      {groupInfo && <p className="vr-class-ok">{groupInfo}</p>}
      {(cls.group_codes?.length ?? 0) > 0 && (
        <div className="vr-class-groups">
          <span className="vr-class-code-label">Códigos dos grupos</span>
          <div className="vr-class-group-list">
            {cls.group_codes.map((g: string, i: number) => (
              <span key={g} className="vr-class-group-chip" title={`Grupo ${i + 1}`}>{i + 1}: {g}</span>
            ))}
          </div>
        </div>
      )}
      {err && <p className="vr-class-err">{err}</p>}
    </div>
  );
}

/** Chat do facilitador — responde os alunos que escrevem pelo chat do pacote. */
function FacilitatorChat({ roomId }: { roomId: string }) {
  const sdk = useSDK();
  const [convs, setConvs] = useState<any[]>([]);
  const [open, setOpen] = useState<any | null>(null);
  const [msgs, setMsgs] = useState<any[]>([]);
  const [text, setText] = useState("");
  const [unavailable, setUnavailable] = useState(false);

  const loadConvs = () => sdk.openpbl.chat.conversations(roomId).then((c) => setConvs(Array.isArray(c) ? c : [])).catch(() => setUnavailable(true));
  const loadMsgs = (conv: any) => sdk.openpbl.chat.messages(roomId, conv.id).then((m) => setMsgs(Array.isArray(m) ? m : [])).catch(() => {});

  useEffect(() => {
    loadConvs();
    const iv = setInterval(() => { loadConvs(); }, 8000);
    return () => clearInterval(iv);
  }, [roomId]);
  useEffect(() => {
    if (!open) return;
    loadMsgs(open);
    const iv = setInterval(() => loadMsgs(open), 5000);
    return () => clearInterval(iv);
  }, [open?.id]);

  const reply = async () => {
    const t = text.trim();
    if (!t || !open) return;
    setText("");
    await sdk.openpbl.chat.reply(roomId, open.id, t).catch(() => {});
    loadMsgs(open);
  };

  if (unavailable) return null;   // chat não configurado no servidor — esconde a seção

  return (
    <div className="vr-fchat">
      <div className="vr-class-head">Chat dos alunos (pacote)</div>
      {!open ? (
        convs.length === 0
          ? <div className="vr-scorm-empty">Nenhuma conversa ainda. Quando um aluno escrever pelo pacote, aparece aqui.</div>
          : (
            <div className="vr-fchat-list">
              {convs.map((c) => (
                <button key={c.id} className="vr-fchat-conv" onClick={() => { setOpen(c); setMsgs([]); }}>
                  <span className="vr-fchat-name">{c.student_name || c.student_email}</span>
                  <span className="vr-fchat-meta">{c.course_id?.slice(0, 18)}{(c.unread ?? 0) > 0 ? ` • ${c.unread} nova(s)` : ""}</span>
                </button>
              ))}
            </div>
          )
      ) : (
        <div className="vr-fchat-thread">
          <div className="vr-fchat-thread-head">
            <button className="vr-mini" onClick={() => setOpen(null)}>← Conversas</button>
            <span className="vr-fchat-name">{open.student_name || open.student_email}</span>
          </div>
          <div className="vr-fchat-msgs">
            {msgs.map((m) => (
              <div key={m.id} className="vr-fchat-msg" data-teacher={m.sender === "teacher"}>
                <span>{m.content}</span>
              </div>
            ))}
            {msgs.length === 0 && <div className="vr-scorm-empty">Sem mensagens.</div>}
          </div>
          <div className="vr-scorm-relay-row">
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Responder ao aluno…"
              onKeyDown={(e) => { if (e.key === "Enter") reply(); }} />
            <button onClick={reply}>Enviar</button>
          </div>
        </div>
      )}
    </div>
  );
}


function LessonDots({ s, order }: { s: any; order: string[] }) {
  if (!order.length) return null;
  const done = new Set<string>(s.done_lessons || []);
  return (
    <div className="vr-scorm-dots" title={`${s.lessons_done}/${order.length} lições concluídas`}>
      {order.map((lid, i) => (
        <span key={lid} className="vr-scorm-dot" data-done={done.has(lid)}
          title={`Lição ${i + 1}${done.has(lid) ? " — concluída" : ""}`} />
      ))}
    </div>
  );
}

function StudentRow({ s, order }: { s: any; order: string[] }) {
  return (
    <div className="vr-scorm-row" data-warn={s.status === "nao-abriu"}>
      <div className="vr-scorm-rowtop">
        <div className="vr-scorm-who"><b>{s.name}</b><span>{s.email}</span></div>
        <div className="vr-scorm-meta">
          <span className="vr-scorm-badge" data-st={s.status}>{SCORM_STATUS[s.status] || s.status}</span>
          {s.completed && <span className="vr-scorm-done" title="Concluiu o pacote">✓</span>}
        </div>
      </div>
      {s.status !== "nao-abriu" && <LessonDots s={s} order={order} />}
    </div>
  );
}

function StudentList({ students, loading, order }: { students: any[]; loading: boolean; order: string[] }) {
  if (loading) return <div className="vr-scorm-empty">Carregando…</div>;
  if (students.length === 0) return <div className="vr-scorm-empty">Nenhum aluno com e-mail identificado. Ative “Pedir e-mail” no convite da sala.</div>;
  return <div className="vr-scorm-list">{students.map((s) => <StudentRow key={s.email} s={s} order={order} />)}</div>;
}

function ScormPanel({ roomId }: { roomId: string }) {
  const sdk = useSDK();
  const [students, setStudents] = useState<any[]>([]);
  const [order, setOrder] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const load = () => sdk.rooms.scormProgress(roomId)
    .then((r: any) => { setStudents(r.students || []); setOrder(r.lessons || []); })
    .catch(() => {}).finally(() => setLoading(false));
  useEffect(() => { load(); const iv = setInterval(load, 20000); return () => clearInterval(iv); }, [roomId]);
  const notOpened = students.filter((s) => s.status === "nao-abriu").length;

  const warn = !loading && students.length > 0 && notOpened > 0
    ? <div className="vr-scorm-warn">⚠ {notOpened} de {students.length} ainda não abriram o pacote</div> : null;
  const legend = order.length > 0
    ? <div className="vr-scorm-legend">Cada bolinha = uma lição; verde quando o aluno conclui.</div> : null;

  return (
    <div className="vr-scorm">
      <ClassControl roomId={roomId} />
      <FacilitatorChat roomId={roomId} />
      <div className="vr-scorm-progress">
        <div className="vr-scorm-head">
          <span>Progresso dos alunos</span>
          <div className="vr-scorm-actions">
            <button className="vr-mini" onClick={() => setExpanded(true)} title="Abrir em popup">⤢ Expandir</button>
            <button className="vr-mini" onClick={load}>Atualizar</button>
          </div>
        </div>
        {warn}{legend}
        <StudentList students={students} loading={loading} order={order} />
      </div>

      {expanded && (
        <div className="vr-scorm-overlay" onClick={() => setExpanded(false)}>
          <div className="vr-scorm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="vr-scorm-modal-head">
              <h3>Progresso dos alunos — OpenPBL</h3>
              <div className="vr-scorm-actions">
                <button className="vr-mini" onClick={load}>Atualizar</button>
                <button className="vr-mini" onClick={() => setExpanded(false)}>Fechar ✕</button>
              </div>
            </div>
            <div className="vr-scorm-modal-body">
              {warn}{legend}
              <StudentList students={students} loading={loading} order={order} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- Controls ---------------- */
function ControlBar({ isStaff, scorm, panel, setPanel, onOpenSettings, settingsActive, peopleCount, boardActive, onToggleBoard, recording, onToggleRecording, showQr, onQr, onLeaveRoom }: {
  isStaff: boolean; scorm: boolean; panel: string | null;
  setPanel: (p: "chat" | "people" | "breakout" | "scorm" | null) => void;
  onOpenSettings: () => void; settingsActive: boolean;
  peopleCount: number; boardActive: boolean; onToggleBoard: () => void;
  recording: boolean; onToggleRecording: () => void;
  showQr?: boolean; onQr?: () => void; onLeaveRoom?: () => void;
}) {
  const mic = useTrackToggle({ source: Track.Source.Microphone });
  const cam = useTrackToggle({ source: Track.Source.Camera });
  const room = useRoomContext();

  // Barra enxuta: microfone, câmera, chat, pacote (QR) e sair.
  return (
    <div className="vr-controls">
      <Ctrl label="Microfone" icon={mic.enabled ? I.mic : I.micOff} title={mic.enabled ? "Desligar microfone" : "Ligar microfone"}
        off={!mic.enabled} disabled={mic.pending} onClick={() => mic.toggle()} />
      <Ctrl label="Câmera" icon={cam.enabled ? I.cam : I.camOff} title={cam.enabled ? "Desligar câmera" : "Ligar câmera"}
        off={!cam.enabled} disabled={cam.pending} onClick={() => cam.toggle()} />

      <div className="vr-sep" />

      <Ctrl label="Chat" icon={I.chat} active={panel === "chat"}
        onClick={() => setPanel(panel === "chat" ? null : "chat")} />
      {showQr && (
        <Ctrl label="Código" icon={I.qr} title="Abrir o código (QR) do pacote da atividade"
          onClick={() => onQr?.()} />
      )}

      <div className="vr-sep" />

      <Ctrl label="Sair" icon={I.phone} leave onClick={() => { void room.disconnect(); onLeaveRoom?.(); }} />
    </div>
  );
}

/** Botão da barra: ícone com a descrição embaixo (igual ao mockup). */
function Ctrl({ label, icon, onClick, title, disabled, off, active, leave, className }: {
  label: string; icon: ReactNode; onClick: () => void;
  title?: string; disabled?: boolean; off?: boolean; active?: boolean; leave?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={`vr-ctrl${className ? ` ${className}` : ""}`}
      onClick={onClick}
      disabled={disabled}
      title={title ?? label}
      data-off={off || undefined}
      data-active={active || undefined}
      data-leave={leave || undefined}
    >
      <span className="vr-ctrl-ico">{icon}</span>
      <span className="vr-ctrl-lbl">{label}</span>
    </button>
  );
}

/* ---------------- helpers ---------------- */
function useElapsed() {
  const [t, setT] = useState("00:00");
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => {
      const s = Math.floor((Date.now() - start) / 1000);
      const mm = String(Math.floor(s / 60)).padStart(2, "0");
      const ss = String(s % 60).padStart(2, "0");
      const hh = Math.floor(s / 3600);
      setT(hh > 0 ? `${String(hh).padStart(2, "0")}:${mm}:${ss}` : `${mm}:${ss}`);
    }, 1000);
    return () => clearInterval(id);
  }, []);
  return t;
}

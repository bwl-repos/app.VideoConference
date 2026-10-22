/**
 * Video Rooms SDK — thin client for the FastAPI backend.
 *
 * Usage in a host app:
 *   const sdk = createVideoRoomsSDK({
 *     apiBase: "https://your-backend",
 *     wsBase:  "wss://your-backend",
 *     headers: () => ({
 *       "X-User-Id":   currentUser.id,
 *       "X-User-Name": currentUser.name,
 *       "X-User-Role": currentUser.role,
 *     }),
 *   });
 */

export type Headers = Record<string, string>;

export interface SDKOptions {
  apiBase: string;
  wsBase?: string;
  headers?: () => Headers;
  /**
   * "include" envia o cookie de sessão mesmo quando o apiBase está em outra
   * origem (dev: :5173 → :8000). Só use nas rotas autenticadas do portal: uma
   * requisição credenciada é rejeitada pelo navegador se o backend responder
   * `Access-Control-Allow-Origin: *`, como acontece no embed/convidado.
   */
  credentials?: RequestCredentials;
}

export interface Room {
  id: string;
  room_id: string;
  title: string;
  description?: string | null;
  owner_id: string;
  status: string;
  max_participants: number;
  is_public: boolean;
  auto_record: boolean;
  lobby_enabled: boolean;
  lobby_timer_title?: string | null;
  lobby_timer_seconds: number;
  lobby_bg_video?: string | null;
  lobby_auto_admit: boolean;
  guest_token?: string | null;
  allow_camera: boolean;
  allow_mic: boolean;
  allow_screen_share: boolean;
  allow_whiteboard_edit: boolean;
  whiteboard_active: boolean;
  recording_enabled: boolean;
  recording_url?: string | null;
  external_ref?: string | null;
  openpbl_activity_id?: string | null;
  scheduled_at?: string | null;
  ended_at?: string | null;
  created_at: string;
}

export interface GuestRoomInfo {
  id: string;
  title: string;
  status: string;
  lobby_enabled: boolean;
  lobby_timer_title?: string | null;
  lobby_timer_seconds: number;
  lobby_bg_video?: string | null;
  lobby_auto_admit: boolean;
  created_at?: string | null;
  branding?: Record<string, any>;
  tenant_name?: string | null;
}

export interface TokenResponse {
  token: string;
  livekit_url: string;
  identity: string;
}

export interface OpenPblRosterEntry {
  identity: string;
  name: string;
  is_staff: boolean;
  in_package: boolean | null;   // null p/ staff (não se aplica)
  registered: boolean;
}

export interface OpenPblClass {
  active: boolean;
  activity_id?: string;
  presentation_code?: string;
  class_course_id?: string;
  group_codes?: string[];
  facilitator_email?: string;
  facilitator_name?: string;
  checking_open?: boolean;
  released_dimensions?: boolean;   // gate Riscos
  released?: boolean;              // gate Percepções
  code_hidden?: boolean;
  stage?: OpenPblStage;            // sequenciamento do ▶
}

/**
 * Roteiro da Videoconferência do episódio, congelado na criação da sala.
 *
 * É o CONTEÚDO do encontro — sinopse, questões e riscos — que a sala renderiza
 * nativamente (antes vinha do pacote SCORM de apresentação). Montado pelo
 * CustomerApp a partir de `roteiro/schema.ts` + do que foi preenchido no modal de
 * gerenciar produção; aqui só é lido.
 */
export interface RoteiroBlocoFixo { titulo?: string; paragrafos: string[]; lista?: boolean }
export interface RoteiroSnapshot {
  episodio?: { id?: string; titulo?: string };
  /** Campos variáveis por nome (ver schema.ts): texto ou lista de textos. */
  campos?: Record<string, string | string[]>;
  /** Textos fixos por seção, na ordem do roteiro. */
  secoes?: Array<{ key: string; titulo: string; blocosFixos: RoteiroBlocoFixo[] }>;
}

/** Etapas do sequenciador do facilitador (espelham "ETAPAS E ATIVIDADES DO ENCONTRO"). */
export type OpenPblStage =
  | "session_start"       // Iniciar a sessão
  | "registration_open"   // Iniciar o registro
  | "amplify_code"        // Amplia código da sessão
  | "registration_close"  // Encerrar o registro
  | "synopsis"            // Revisitando a situação-problema (sinopse do episódio)
  | "groups"              // Divisão em grupos
  | "plenary"             // Discussão em plenária
  | "question"            // Questão para reflexão (×5)
  | "situational"         // Análise situacional
  | "release_risks"       // Liberar análise individual de riscos
  | "show_chart"          // Mostrar gráfico (também para os alunos)
  | "closing"             // Encerramento
  | "release_feedback"    // Liberar feedback de interação
  | "done";               // Encontro concluído

export interface BreakoutMember { identity: string; display_name: string }
export interface BreakoutGroup {
  id: string;
  name: string;
  room_name: string;
  position: number;
  members: BreakoutMember[];
}
export interface BreakoutState {
  open: boolean;
  ends_at: string | null;
  mode: "auto" | "manual" | "self";
  groups: BreakoutGroup[];
}
export interface BreakoutToken {
  token: string;
  livekit_url: string;
  identity: string;
  room_name: string;
  group_name: string;
}

export function createVideoRoomsSDK(opts: SDKOptions) {
  const wsBase = opts.wsBase ?? opts.apiBase.replace(/^http/, "ws");

  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(`${opts.apiBase}${path}`, {
      ...init,
      credentials: opts.credentials,
      headers: {
        "Content-Type": "application/json",
        ...(opts.headers?.() ?? {}),
        ...(init.headers ?? {}),
      },
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json();
  }

  return {
    rooms: {
      list: () => call<Room[]>("/api/rooms"),
      get: (id: string) => call<Room>(`/api/rooms/${id}`),
      byGuestToken: (token: string) =>
        call<GuestRoomInfo>(`/api/rooms/by-guest-token/${token}`),
      branding: (slug: string) =>
        call<{ name: string | null; branding: Record<string, any> }>(`/api/rooms/branding/${slug}`),
      publicInfo: (id: string) =>
        call<{
          title: string; branding: Record<string, any>; tenant_name: string | null;
          require_email?: boolean; allow_whiteboard_edit?: boolean; scorm?: boolean;
          lobby_enabled?: boolean; lobby_timer_title?: string | null;
          lobby_timer_seconds?: number; lobby_bg_video?: string | null; lobby_auto_admit?: boolean;
          class_package_url?: string | null; created_at?: string | null;
          risk_dimensions?: string[] | null;
          roteiro?: RoteiroSnapshot | null;
        }>(`/api/rooms/${id}/public`),
      create: (body: Partial<Room>) =>
        call<Room>("/api/rooms", { method: "POST", body: JSON.stringify(body) }),
      end: (id: string) => call(`/api/rooms/${id}/end`, { method: "POST" }),
      setPermissions: (id: string, target: string, perms: Record<string, boolean>) =>
        call(`/api/rooms/${id}/participants/${target}/permissions`, {
          method: "POST", body: JSON.stringify(perms),
        }),
      setRoomPermissions: (id: string, perms: Record<string, boolean>) =>
        call(`/api/rooms/${id}/permissions`, { method: "PUT", body: JSON.stringify(perms) }),
      scormProgress: (id: string) =>
        call<{ scorm: boolean; since?: string; count?: number; students: any[] }>(`/api/rooms/${id}/scorm/progress`),
      moderate: (id: string, action: string, target: Record<string, any>) =>
        call(`/api/rooms/${id}/moderation/${action}`, {
          method: "POST", body: JSON.stringify(target),
        }),
      syncBooking: (b: { external_ref: string; title: string; scheduled_at: string; owner_id: string; lobby_enabled?: boolean }) =>
        call<Room>("/api/rooms/bookings/sync", { method: "POST", body: JSON.stringify(b) }),
    },
    token: {
      issue: (body: { room_id: string; guest_token?: string; speaker_invite_id?: string; display_name?: string; email?: string }) =>
        call<TokenResponse>("/api/token", { method: "POST", body: JSON.stringify(body) }),
    },
    chat: {
      list: (roomId: string, channel?: string) =>
        call<Array<{ id: string; sender_id: string; sender_name: string; message: string; channel?: string | null; created_at: string }>>(
          `/api/rooms/${roomId}/chat${channel ? `?channel=${encodeURIComponent(channel)}` : ""}`,
        ),
      send: (roomId: string, message: string, sender_name?: string, channel?: string) =>
        call(`/api/rooms/${roomId}/chat`, {
          method: "POST", body: JSON.stringify({ message, sender_name, channel }),
        }),
    },
    lobby: {
      list: (roomId: string) => call<any[]>(`/api/rooms/${roomId}/lobby`),
      join: (roomId: string, display_name: string, participant_type: "user" | "guest" | "speaker" = "user") =>
        call(`/api/rooms/${roomId}/lobby/join`, {
          method: "POST", body: JSON.stringify({ display_name, participant_type }),
        }),
      decide: (roomId: string, lobbyId: string, admit: boolean) =>
        call(`/api/rooms/${roomId}/lobby/${lobbyId}/decision`, {
          method: "POST", body: JSON.stringify({ admit }),
        }),
    },
    invites: {
      createSpeaker: (roomId: string, body: any) =>
        call(`/api/rooms/${roomId}/invites/speaker`, {
          method: "POST", body: JSON.stringify(body),
        }),
      list: (roomId: string) => call<any[]>(`/api/rooms/${roomId}/invites`),
      revokeSpeaker: (roomId: string, inviteId: string) =>
        call(`/api/rooms/${roomId}/invites/speaker/${inviteId}`, { method: "DELETE" }),
    },
    whiteboard: {
      get: (roomId: string) => call<{ id: string; state: any; updated_at: string }>(`/api/rooms/${roomId}/whiteboard`),
      save: (roomId: string, state: any) =>
        call(`/api/rooms/${roomId}/whiteboard`, { method: "PUT", body: JSON.stringify(state) }),
      toggle: (roomId: string, active: boolean) =>
        call(`/api/rooms/${roomId}/whiteboard/toggle`, {
          method: "POST", body: JSON.stringify({ active }),
        }),
    },
    backgrounds: {
      list: () =>
        call<Array<{ key: string; name: string; size: number; url: string }>>("/api/backgrounds"),
      upload: async (file: File) => {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetch(`${opts.apiBase}/api/backgrounds`, {
          method: "POST",
          credentials: opts.credentials,
          headers: { ...(opts.headers?.() ?? {}) }, // no Content-Type → browser sets multipart boundary
          body: fd,
        });
        if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
        return res.json() as Promise<{ key: string; name: string; url: string }>;
      },
    },
    roles: {
      /** Papéis da sessão: moderadores, controlador (sequenciador) e câmera fixada. */
      get: (roomId: string) =>
        call<{ moderators: string[]; controller: string | null; pinned: string | null }>(`/api/rooms/${roomId}/roles`),
      set: (roomId: string, body: {
        add_moderator?: string; remove_moderator?: string;
        set_controller?: boolean; controller?: string | null;
        set_pinned?: boolean; pinned?: string | null;
      }) => call(`/api/rooms/${roomId}/roles`, { method: "POST", body: JSON.stringify(body) }),
    },
    openpbl: {
      /** Estado da aula OpenPBL da sala (class-code, gates, registro). */
      classState: (roomId: string) => call<OpenPblClass>(`/api/rooms/${roomId}/openpbl`),
      /** Gera o class-code + turma (replica o pacote PRESENTATION). */
      startClass: (roomId: string, activity_id: string, facilitator_email?: string) =>
        call<OpenPblClass>(`/api/rooms/${roomId}/openpbl/start`, {
          method: "POST", body: JSON.stringify({ activity_id, facilitator_email }),
        }),
      /** Libera questionário: "risks" (Riscos/dimensões) ou "perceptions" (Percepções). */
      release: (roomId: string, gate: "risks" | "perceptions") =>
        call<OpenPblClass>(`/api/rooms/${roomId}/openpbl/release`, {
          method: "POST", body: JSON.stringify({ gate }),
        }),
      closeRegistration: (roomId: string) =>
        call<OpenPblClass>(`/api/rooms/${roomId}/openpbl/close-registration`, { method: "POST" }),
      groups: (roomId: string) => call<any[]>(`/api/rooms/${roomId}/openpbl/groups`),
      /** Os critérios de desempenho, na ORDEM — o índice aqui é o `destaque`
       *  que `avaliarDesempenho` manda de volta. Reordenar trocaria os eixos. */
      criteriosDesempenho: (roomId: string) =>
        call<{ criterios: string[] }>(`/api/rooms/${roomId}/openpbl/criterios`),
      /** A nota de participação do aluno na plenária, dada pelo facilitador no
       *  menu de contexto da câmera. `destaque` só é usado com nota 4: um 4
       *  vale 4 apenas no critério apontado, e 3 nos outros. */
      avaliarDesempenho: (roomId: string, body: { identity: string; nota: 1 | 2 | 3 | 4; destaque?: number | null }) =>
        call<{ ok: boolean; avaliado: string; nota: number; destaque: number | null }>(
          `/api/rooms/${roomId}/openpbl/avaliar`,
          { method: "POST", body: JSON.stringify(body) }),
      /** (Re)cria os breakouts a partir dos grupos montados pela API OpenPBL. */
      syncGroups: (roomId: string) =>
        call<{ ok: boolean; groups: number }>(`/api/rooms/${roomId}/openpbl/sync-groups`, { method: "POST" }),
      /** Move o cursor da etapa do facilitador (botão verde ▶). */
      setStage: (roomId: string, stage: OpenPblStage) =>
        call<OpenPblClass>(`/api/rooms/${roomId}/openpbl/stage`, {
          method: "POST", body: JSON.stringify({ stage }),
        }),
      /** Dados do gráfico radar do Questionário de Riscos — agregado pelos grupos
       *  da webconf (respostas individuais) + contagem de quem respondeu por dimensão. */
      riskChart: (roomId: string) =>
        call<{ available: boolean; reason?: string; chart?: { dimensions: string[]; baseGrades: number[]; classAverage: number[]; groups: { name: string; grades: number[]; size: number }[]; answered: number[]; total: number } }>(
          `/api/rooms/${roomId}/openpbl/risk-chart`),
      /** Status por participante p/ bordas dos tiles (verde=no pacote, vermelho=fora)
       *  + badge de registrado. Público — todo cliente da sala faz polling. */
      roster: (roomId: string) =>
        call<{ code: string | null; activity_id: string | null; facilitator_email: string | null; facilitator_name: string | null; checking_open: boolean | null; code_hidden: boolean; students: OpenPblRosterEntry[] }>(
          `/api/rooms/${roomId}/openpbl/roster`),
      /** Facilitador oculta/reexibe o card do class-code para todos. */
      setCodeVisible: (roomId: string, hidden: boolean) =>
        call<OpenPblClass>(`/api/rooms/${roomId}/openpbl/code-visibility`, {
          method: "POST", body: JSON.stringify({ hidden }),
        }),
      chat: {
        conversations: (roomId: string) =>
          call<any[]>(`/api/rooms/${roomId}/openpbl/chat/conversations`),
        messages: (roomId: string, convId: string) =>
          call<any[]>(`/api/rooms/${roomId}/openpbl/chat/conversations/${convId}/messages`),
        reply: (roomId: string, convId: string, content: string) =>
          call(`/api/rooms/${roomId}/openpbl/chat/conversations/${convId}/reply`, {
            method: "POST", body: JSON.stringify({ content }),
          }),
      },
    },
    breakouts: {
      state: (roomId: string) => call<BreakoutState>(`/api/rooms/${roomId}/breakouts`),
      create: (roomId: string, body: { count: number; names?: string[]; mode: "auto" | "manual" | "self" }) =>
        call<BreakoutState>(`/api/rooms/${roomId}/breakouts`, { method: "POST", body: JSON.stringify(body) }),
      assign: (roomId: string, identity: string, group_id: string | null, display_name?: string) =>
        call(`/api/rooms/${roomId}/breakouts/assign`, {
          method: "POST", body: JSON.stringify({ identity, group_id, display_name }),
        }),
      open: (roomId: string, duration_seconds?: number) =>
        call<BreakoutState>(`/api/rooms/${roomId}/breakouts/open`, {
          method: "POST", body: JSON.stringify({ duration_seconds }),
        }),
      close: (roomId: string) =>
        call(`/api/rooms/${roomId}/breakouts/close`, { method: "POST" }),
      message: (roomId: string, text: string) =>
        call(`/api/rooms/${roomId}/breakouts/message`, { method: "POST", body: JSON.stringify({ text }) }),
      token: (roomId: string, group_id: string, identity: string, display_name?: string) =>
        call<BreakoutToken>(`/api/rooms/${roomId}/breakouts/token`, {
          method: "POST", body: JSON.stringify({ group_id, identity, display_name }),
        }),
    },
    recording: {
      start: (roomId: string) =>
        call(`/api/rooms/${roomId}/recording/start`, { method: "POST" }),
      stop: (roomId: string) =>
        call(`/api/rooms/${roomId}/recording/stop`, { method: "POST" }),
      get: (roomId: string) =>
        call<{ recording_enabled: boolean; progress: string | null; url: string | null }>(
          `/api/rooms/${roomId}/recording`,
        ),
    },
    /**
     * WebSocket: subscribes to every room event (chat, lobby, whiteboard, moderation, recording).
     * Returns an unsubscribe function.
     */
    subscribe(roomId: string, onEvent: (event: string, payload: any) => void): () => void {
      // Reconecta sozinho: sem isto, qualquer queda do socket (blip de rede, timeout de
      // conexão ociosa, restart do backend a cada deploy) parava as atualizações em
      // silêncio — o cliente ficava preso no último estado recebido. Ao (re)conectar,
      // emite o evento sintético "__reconnected" para o consumidor RE-SINCRONIZAR os
      // estados que possa ter perdido durante a queda (ex.: a etapa da aula).
      let ws: WebSocket | null = null;
      let closed = false;
      let first = true;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const connect = () => {
        if (closed) return;
        ws = new WebSocket(`${wsBase}/ws/rooms/${roomId}`);
        ws.onopen = () => { if (!first) onEvent("__reconnected", null); first = false; };
        ws.onmessage = (e) => {
          try {
            const { event, payload } = JSON.parse(e.data);
            onEvent(event, payload);
          } catch {}
        };
        ws.onclose = () => { if (!closed) timer = setTimeout(connect, 2000); };
        ws.onerror = () => { try { ws?.close(); } catch {} };
      };
      connect();
      return () => { closed = true; if (timer) clearTimeout(timer); try { ws?.close(); } catch {} };
    },

    /**
     * Bidirectional channel: like subscribe(), but also lets the client SEND
     * events that the backend relays to everyone else in the room (exclude=sender).
     * Used for low-latency whiteboard deltas. Messages sent before the socket
     * opens are queued.
     */
    connect(
      roomId: string,
      onEvent: (event: string, payload: any) => void,
    ): { send: (event: string, payload: any) => void; close: () => void } {
      const ws = new WebSocket(`${wsBase}/ws/rooms/${roomId}`);
      const queue: string[] = [];
      ws.onopen = () => { queue.forEach((m) => ws.send(m)); queue.length = 0; };
      ws.onmessage = (e) => {
        try {
          const { event, payload } = JSON.parse(e.data);
          onEvent(event, payload);
        } catch {}
      };
      return {
        send(event: string, payload: any) {
          const m = JSON.stringify({ event, payload });
          if (ws.readyState === WebSocket.OPEN) ws.send(m);
          else queue.push(m);
        },
        close() { ws.close(); },
      };
    },
  };
}

export type VideoRoomsSDK = ReturnType<typeof createVideoRoomsSDK>;

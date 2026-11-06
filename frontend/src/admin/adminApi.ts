// Admin API client. Auth is an httpOnly cookie set by the server on /login —
// no token is ever stored in JS (XSS-safe). Requests are same-origin with credentials.
const base = import.meta.env.VITE_API_BASE || "";

/** A requisição crua, para o que não é JSON.
 *
 * Existe por causa de um único caso: a prévia da voz devolve `audio/mpeg` no
 * corpo. `adminApi` sempre faz `res.json()`, e um `<audio>` precisa dos bytes.
 * Mora aqui para a URL base e a política de cookie ficarem num lugar só. */
export function adminFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${base}/api/admin${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
}

export async function adminApi<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${base}/api/admin${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (!res.ok) {
    let msg = `${res.status}`;
    try { msg = (await res.json()).detail ?? msg; } catch { /* ignore */ }
    throw new Error(typeof msg === "string" ? msg : "erro");
  }
  return res.json();
}

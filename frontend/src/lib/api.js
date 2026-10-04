// API & WebSocket client — same-origin by design.
//
// In development Vite proxies /api and /ws to the FastAPI container, and in
// production nginx does the same (see vite.config.js and docker/frontend/nginx.conf).
// Deriving the base from window.location therefore needs no environment variable and no
// rebuild to point the app at another host: same-origin also removes CORS from the
// picture entirely, and keeps the JWT out of the WebSocket URL.

const API_BASE = `${window.location.origin}/api/v1`;
const WS_BASE = `${window.location.origin.replace(/^http/, 'ws')}/ws/fleet`;

const TOKEN_KEY = 'fdt.token';
const USER_KEY = 'fdt.user';

// Credentials used only until an explicit sign-in happens. The seeded demo accounts are
// a documented fixture of this project (docs/01 §7), not a secret; a real deployment
// signs in through the login form and the token below is never used.
const DEMO_CREDENTIALS = { username: 'commander', password: 'commander123' };

let currentToken = sessionStorage.getItem(TOKEN_KEY);
let currentUser = readStoredUser();
let loginPromise = null;
let activeWs = null;
let reconnectTimer = null;
let reconnectAttempt = 0;
let stopped = false;

const listeners = new Set();

/** Subscribe to auth-state changes so the navbar badge reflects the real user. */
export function onAuthChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function readStoredUser() {
  try {
    return JSON.parse(sessionStorage.getItem(USER_KEY) || 'null');
  } catch {
    return null;
  }
}

function emitAuth() {
  for (const fn of listeners) fn(currentUser);
}

function setSession(token, user) {
  currentToken = token;
  currentUser = user;
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
  if (user) sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  else sessionStorage.removeItem(USER_KEY);
  emitAuth();
}

export function getUser() {
  return currentUser;
}

export function logout() {
  setSession(null, null);
}

export async function login(username, password) {
  const creds = username ? { username, password } : DEMO_CREDENTIALS;
  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(creds),
    });
    if (!res.ok) throw new Error(`login failed: HTTP ${res.status}`);
    const data = await res.json();
    setSession(data.access_token, data.user);
    return { token: currentToken, user: currentUser };
  } catch (err) {
    console.warn('[API] login failed:', err);
    setSession(null, null);
    return null;
  }
}

/** Single in-flight login, so a burst of parallel calls does not race on the token. */
async function ensureToken() {
  if (currentToken) return currentToken;
  if (!loginPromise) {
    loginPromise = login().finally(() => {
      loginPromise = null;
    });
  }
  await loginPromise;
  return currentToken;
}

async function request(path, { method = 'GET', body, retry = true } = {}) {
  const token = await ensureToken();
  if (!token) return { ok: false, status: 0, body: null };

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  // The JWT has a TTL. On expiry every subsequent call would silently return null
  // forever, because the token was never cleared — so clear it and let the one
  // in-flight retry re-authenticate.
  if (res.status === 401 && retry) {
    setSession(null, null);
    return request(path, { method, body, retry: false });
  }

  const payload = res.status === 204 ? null : await res.json().catch(() => null);
  return { ok: res.ok, status: res.status, body: payload };
}

export async function fetchAircraftList() {
  try {
    const { ok, body } = await request('/aircraft');
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchAircraftList failed:', err);
    return null;
  }
}

export async function fetchAircraftDetail(codeOrId) {
  try {
    const { ok, body } = await request(`/aircraft/${encodeURIComponent(codeOrId)}`);
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchAircraftDetail failed:', err);
    return null;
  }
}

export async function fetchFleetSummary() {
  try {
    const { ok, body } = await request('/fleet/summary');
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchFleetSummary failed:', err);
    return null;
  }
}

/**
 * Aircraft x part health matrix.
 *
 * This is the endpoint that makes the health heatmap real. The grid used to be
 * computed in the browser from a hardcoded wear curve, so every cell was invented
 * locally and had no relationship to the model or the database.
 */
export async function fetchHeatmap() {
  try {
    const { ok, body } = await request('/fleet/heatmap');
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchHeatmap failed:', err);
    return null;
  }
}

/** Worst parts across the fleet, with the action, spare, agency and turnaround. */
export async function fetchFleetActions(limit = 5) {
  try {
    const { ok, body } = await request(`/fleet/actions?limit=${limit}`);
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchFleetActions failed:', err);
    return null;
  }
}

/** One row per aircraft: worst part, action, due dates, spare status, agency, work order. */
export async function fetchSchedule() {
  try {
    const { ok, body } = await request('/maintenance/schedule');
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchSchedule failed:', err);
    return null;
  }
}

/**
 * Engine detail for one aircraft: per-module health, RUL, top sensors by real
 * z-score, the engine spare, and the last N cycles of history.
 */
export async function fetchEngineDetail(codeOrId, window = 60) {
  try {
    const { ok, body } = await request(
      `/aircraft/${encodeURIComponent(codeOrId)}/engine?window=${window}`,
    );
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchEngineDetail failed:', err);
    return null;
  }
}

/** Part detail: health, action, technical records, spare, agency, back-in-service breakdown. */
export async function fetchPartDetail(codeOrId, part) {
  try {
    const { ok, body } = await request(
      `/aircraft/${encodeURIComponent(codeOrId)}/parts/${encodeURIComponent(part)}`,
    );
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchPartDetail failed:', err);
    return null;
  }
}

export async function fetchAlerts() {
  try {
    const { ok, body } = await request('/alerts?limit=50');
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] fetchAlerts failed:', err);
    return null;
  }
}

/**
 * Acknowledge a live alert.
 * @param {number} alertId numeric id from the backend — the path parameter is typed int,
 *   so a UI-side synthetic key cannot be sent.
 */
export async function postAcknowledgeAlert(alertId, note = null) {
  try {
    const { ok, body } = await request(`/alerts/${alertId}/ack`, {
      method: 'POST',
      body: { note },
    });
    return ok ? body : null;
  } catch (err) {
    console.warn('[API] postAcknowledgeAlert failed:', err);
    return null;
  }
}

/**
 * Raise a work order.
 *
 * `due_date` is required by WorkOrderCreate and `priority` is a three-value literal —
 * the previous payload omitted the date and sent "urgent", so every call was a 422 and
 * nothing was ever persisted. The due date is derived from the part's RUL so the order
 * lands where the maintenance plan expects it.
 */
export async function postCreateWorkOrder(aircraftCode, partCode, rul, notes = 'Raised from the Digital Twin') {
  const dueInDays = Number.isFinite(rul) ? Math.max(1, Math.min(180, Math.ceil(rul))) : 30;
  const dueDate = new Date(Date.now() + dueInDays * 86400000).toISOString().slice(0, 10);
  const priority = Number.isFinite(rul) && rul <= 20 ? 'high' : 'medium';

  try {
    const { ok, status, body } = await request('/work-orders', {
      method: 'POST',
      body: { aircraft: aircraftCode, part: partCode, due_date: dueDate, priority, notes },
    });
    if (!ok) {
      console.warn(`[API] work order rejected: HTTP ${status}`, body);
      return null;
    }
    return body;
  } catch (err) {
    console.warn('[API] postCreateWorkOrder failed:', err);
    return null;
  }
}

export function startLiveFleetSocket(onEvent, onStatus) {
  stopped = false;
  activeWs?.close();
  activeWs = null;
  clearTimeout(reconnectTimer);

  async function connect() {
    if (stopped) return;
    const token = await ensureToken();
    if (!token) {
      onStatus?.(false);
      scheduleReconnect(connect);
      return;
    }

    try {
      // Browsers cannot set headers on a WebSocket handshake, so the JWT necessarily
      // travels in the query string. It is short-lived, and the endpoint additionally
      // origin-checks the connection.
      const ws = new WebSocket(
        `${WS_BASE}?token=${encodeURIComponent(token)}`,
      );
      activeWs = ws;

      ws.onopen = () => {
        reconnectAttempt = 0;
        // keep-alive: the server answers `ping` with `pong`, which doubles as proof
        // the stream is live rather than merely open.
        ws.send(JSON.stringify({ type: 'ping', payload: {} }));
        onStatus?.(true);
      };

      ws.onmessage = (event) => {
        try {
          onEvent?.(JSON.parse(event.data));
        } catch (e) {
          console.error('[WS] malformed frame:', e);
        }
      };

      ws.onclose = (event) => {
        onStatus?.(false);
        activeWs = null;
        // 4401 unauthorized: the session is gone, so drop it before retrying or the
        // loop would reconnect forever with a token the server rejects.
        if (event.code === 4401) setSession(null, null);
        scheduleReconnect(connect);
      };

      ws.onerror = () => ws.close();
    } catch (e) {
      console.warn('[WS] connection error:', e);
      onStatus?.(false);
      scheduleReconnect(connect);
    }
  }

  connect();

  return () => {
    stopped = true;
    clearTimeout(reconnectTimer);
    activeWs?.close();
    activeWs = null;
  };
}

/** Exponential backoff with jitter, capped — a fixed 3 s retry storm-hammers a cold API. */
function scheduleReconnect(connect) {
  reconnectAttempt += 1;
  const delay = Math.min(30000, 1000 * 2 ** (reconnectAttempt - 1)) + Math.random() * 500;
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, delay);
}
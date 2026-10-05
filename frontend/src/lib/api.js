// API & WebSocket client — same-origin by design.
//
// In development Vite proxies /api and /ws to the FastAPI container, and in
// production nginx does the same (see vite.config.js and docker/frontend/nginx.conf).
// Deriving the base from window.location therefore needs no environment variable and no
// rebuild to point the app at another host.

const API_BASE = `${window.location.origin}/api/v1`;
const WS_BASE = `${window.location.origin.replace(/^http/, 'ws')}/ws/fleet`;

let activeWs = null;
let reconnectTimer = null;
let reconnectAttempt = 0;
let liveFilter = null;
let stopped = false;

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

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

  function connect() {
    if (stopped) return;

    try {
      const ws = new WebSocket(WS_BASE);
      activeWs = ws;

      ws.onopen = () => {
        reconnectAttempt = 0;
        // keep-alive: the server answers `ping` with `pong`, which doubles as proof
        // the stream is live rather than merely open.
        ws.send(JSON.stringify({ type: 'ping', payload: {} }));
        // Subscriptions live only in the server's per-connection memory, so a reconnect
        // starts from "everything" again. Re-assert whatever this client asked for,
        // otherwise a filter silently stops filtering after one dropped connection.
        if (liveFilter?.length) {
          ws.send(JSON.stringify({ type: 'subscribe', payload: { aircraft: liveFilter } }));
        }
        onStatus?.(true);
      };

      ws.onmessage = (event) => {
        try {
          onEvent?.(JSON.parse(event.data));
        } catch (e) {
          console.error('[WS] malformed frame:', e);
        }
      };

      ws.onclose = () => {
        onStatus?.(false);
        activeWs = null;
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

/**
 * Restrict this socket to a subset of the fleet, or pass `null` for everything.
 *
 * Applied immediately when a socket is open and remembered for the next `onopen`, since
 * the server holds the filter per connection. Events that name no aircraft — alerts being
 * acknowledged, spares reserved, bookings — are fleet-wide and always delivered.
 */
export function setLiveFleetFilter(codes) {
  liveFilter = codes?.length ? [...codes] : null;
  if (activeWs?.readyState === WebSocket.OPEN) {
    activeWs.send(JSON.stringify(
      liveFilter
        ? { type: 'subscribe', payload: { aircraft: liveFilter } }
        : { type: 'unsubscribe', payload: { aircraft: [] } },
    ));
  }
}

/** Exponential backoff with jitter, capped — a fixed 3 s retry storm-hammers a cold API. */
function scheduleReconnect(connect) {
  reconnectAttempt += 1;
  const delay = Math.min(30000, 1000 * 2 ** (reconnectAttempt - 1)) + Math.random() * 500;
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, delay);
}

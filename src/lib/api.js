// API & WebSocket client connecting Frontend to FastAPI + PostgreSQL backend.

const API_BASE = 'http://127.0.0.1:8000/api/v1';
const WS_BASE = 'ws://127.0.0.1:8000/ws/fleet';

let currentToken = null;
let currentUser = null;
let activeWs = null;
let reconnectTimer = null;

export async function login(username = 'commander', password = 'commander123') {
  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) throw new Error(`Login failed with status ${res.status}`);
    const data = await res.json();
    currentToken = data.access_token;
    currentUser = data.user;
    return { token: currentToken, user: currentUser };
  } catch (err) {
    console.warn('[API] Login failed:', err);
    return null;
  }
}

export async function fetchAircraftList() {
  if (!currentToken) await login();
  try {
    const res = await fetch(`${API_BASE}/aircraft`, {
      headers: { Authorization: `Bearer ${currentToken}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn('[API] fetchAircraftList error:', err);
    return null;
  }
}

export async function fetchAircraftDetail(codeOrId) {
  if (!currentToken) await login();
  try {
    const res = await fetch(`${API_BASE}/aircraft/${codeOrId}`, {
      headers: { Authorization: `Bearer ${currentToken}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn('[API] fetchAircraftDetail error:', err);
    return null;
  }
}

export async function fetchFleetSummary() {
  if (!currentToken) await login();
  try {
    const res = await fetch(`${API_BASE}/fleet/summary`, {
      headers: { Authorization: `Bearer ${currentToken}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn('[API] fetchFleetSummary error:', err);
    return null;
  }
}

export async function postAcknowledgeAlert(alertId) {
  if (!currentToken) await login();
  try {
    const res = await fetch(`${API_BASE}/alerts/${alertId}/acknowledge`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${currentToken}`,
        'Content-Type': 'application/json',
      },
    });
    return res.ok;
  } catch (err) {
    console.warn('[API] postAcknowledgeAlert error:', err);
    return false;
  }
}

export async function postCreateWorkOrder(aircraftCode, partCode, notes = 'Triggered from Digital Twin') {
  if (!currentToken) await login();
  try {
    const res = await fetch(`${API_BASE}/maintenance/work-orders`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${currentToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        aircraft: aircraftCode,
        part: partCode,
        priority: 'urgent',
        notes,
      }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.warn('[API] postCreateWorkOrder error:', err);
    return null;
  }
}

export function startLiveFleetSocket(onEvent, onStatus) {
  if (activeWs) {
    activeWs.close();
    activeWs = null;
  }
  clearTimeout(reconnectTimer);

  async function connect() {
    if (!currentToken) {
      await login();
    }
    if (!currentToken) {
      if (onStatus) onStatus(false);
      reconnectTimer = setTimeout(connect, 3000);
      return;
    }

    try {
      const wsUrl = `${WS_BASE}?token=${encodeURIComponent(currentToken)}`;
      const ws = new WebSocket(wsUrl);
      activeWs = ws;

      ws.onopen = () => {
        if (onStatus) onStatus(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (onEvent) onEvent(data);
        } catch (e) {
          console.error('[WS] Parse error:', e);
        }
      };

      ws.onclose = () => {
        if (onStatus) onStatus(false);
        activeWs = null;
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (e) {
      console.warn('[WS] Connection exception:', e);
      if (onStatus) onStatus(false);
      reconnectTimer = setTimeout(connect, 3000);
    }
  }

  connect();

  return () => {
    clearTimeout(reconnectTimer);
    if (activeWs) {
      activeWs.close();
      activeWs = null;
    }
  };
}

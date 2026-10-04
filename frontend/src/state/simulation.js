import { fleet, resolve } from '../data/fleet.js';
import { clamp } from '../lib/math.js';
import { scr } from '../lib/screening.js';
import { app, emit, setBackendStatus } from './store.js';
import { applyHealthEvent, refreshFleet, startServerState } from './server.js';
import { startLiveFleetSocket, fetchAlerts } from '../lib/api.js';

// Pull the open alerts once on connect so the Alerts panel can acknowledge against real
// backend ids immediately, instead of waiting for the next WS push (which may be minutes
// away if no aircraft crosses a risk band).
function hydrateAlerts() {
  fetchAlerts().then((res) => {
    if (!res || !Array.isArray(res.items)) return;
    app.serverAlerts = res.items;
    emit();
  }).catch(() => {});
}

// Local tick used only when the backend is unreachable, so the console still moves.
// Nothing here touches the server-backed fields: `lib/health.js` falls back to its own
// arithmetic only while an aircraft has no server values, so this stays an offline
// crutch rather than a second source of truth racing the real one.
function fallbackTick() {
  if (scr.on) return;
  app.cycle++;
  fleet.forEach((e) => {
    if (e.rul != null) return;                  // server-backed: leave it alone
    const d = clamp((e._offlineWear ?? 0.3) + 0.0035 + Math.random() * 0.002, 0, 0.99);
    e._offlineWear = d;
    e.hist.push({ cycle: e._offlineCycle = (e._offlineCycle ?? 0) + 1, health: clamp(1 - d, 0, 1) });
    if (e.hist.length > 61) e.hist.shift();
    if (d >= 0.99) { e._offlineWear = 0.05; e.hist = e.hist.map(() => 0.95); }
  });
  emit();
}

// Record where the newest prediction came from. A fallback tick while the backend is
// connected used to be indistinguishable from a model-backed one: a healthy engine's
// linear guess is roughly right, so `rul = 125 - cycle` looked like a real number.
function trackModel(payload) {
  const m = payload && payload.model;
  if (!m) return;
  const prev = app.model;
  app.model = {
    version: m.version ?? null,
    fallback: !!m.fallback,
    degraded: !!m.degraded,
    reason: m.reason ?? null,
    staleTicks: m.fallback ? (prev.fallback ? prev.staleTicks + 1 : 1) : 0,
  };
}

export function startSimulation() {
  let fallbackTimer = null;
  const stopServerState = startServerState();

  // 1. Initial snapshot, then the socket for live values
  const stopSocket = startLiveFleetSocket(
    (event) => {
      if (!event || !event.type) return;

      if (event.type === 'cycle.tick') {
        // The replay publishes one cycle.tick per aircraft, not one per fleet pass
        // (replay.py advances every aircraft inside a single tick), so the last one to
        // arrive was whichever aircraft happened to be processed last. The navbar showed
        // that as "the fleet cycle", which was meaningless. Leave the cycle counter to
        // the per-aircraft `current_cycle` the API reports instead of inventing a fleet
        // cycle from an event that does not describe one.
        return;
      } else if (event.type === 'health.updated') {
        trackModel(event.payload);
        if (applyHealthEvent(event.payload || {})) emit();
      } else if (event.type === 'alert.raised') {
        const a = event.payload;
        if (a && a.id) {
          if (!app.serverAlerts) app.serverAlerts = [];
          if (!app.serverAlerts.some((x) => x.id === a.id)) {
            app.serverAlerts.unshift(a);
          }
          emit();
        }
      }
    },
    (connected) => {
      setBackendStatus(connected);
      if (connected) {
        if (fallbackTimer) {
          clearInterval(fallbackTimer);
          fallbackTimer = null;
        }
        // Re-read the authoritative values rather than trusting whatever the offline
        // fallback happened to leave behind.
        refreshFleet().then((ok) => { if (ok) emit(); }).catch(() => {});
        hydrateAlerts();
      } else if (!fallbackTimer && !app.apiReachable) {
        // Only fall back to inventing data when the read API is unreachable too. A
        // refused WebSocket on its own — an origin outside the allowlist closes it with
        // 4408 — used to be enough to start this timer, so the console quietly showed
        // a fabricated fleet while every real number was one poll away.
        fallbackTimer = setInterval(fallbackTick, 1200);
        app.model = { version: null, fallback: true, degraded: true,
                      reason: 'backend disconnected', staleTicks: 0 };
        emit();
      }
    }
  );

  return () => {
    stopSocket();
    stopServerState();
    if (fallbackTimer) clearInterval(fallbackTimer);
  };
}

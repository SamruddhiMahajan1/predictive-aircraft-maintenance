import { fleet } from '../data/fleet.js';
import { clamp } from '../lib/math.js';
import { scr } from '../lib/screening.js';
import { app, emit, setBackendStatus } from './store.js';
import { startLiveFleetSocket, fetchAircraftList, fetchAlerts } from '../lib/api.js';

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

// Local fallback tick in case backend is offline.
function fallbackTick() {
  if (scr.on) return;
  app.cycle++;
  fleet.forEach((e) => {
    e.d = clamp(e.d + 0.0035 + Math.random() * 0.002, 0, 0.99);
    e.hist.push(clamp(1 - e.d + (Math.random() - 0.5) * 0.02));
    if (e.hist.length > 61) e.hist.shift();
    if (e.d >= 0.99) { e.d = 0.05; e.hist = e.hist.map(() => 0.95); }
  });
  emit();
}

export function startSimulation() {
  let fallbackTimer = null;

  // 1. Initial snapshot from FastAPI backend
  fetchAircraftList().then((res) => {
    if (res && res.items && Array.isArray(res.items)) {
      res.items.forEach((item) => {
        const e = fleet.find((f) => f.id === item.code || f.id === item.name);
        if (e) {
          if (item.engine_health != null) {
            e.d = clamp(1 - item.engine_health, 0, 0.99);
          }
          if (item.rul != null) {
            e.serverRul = item.rul;
          }
        }
      });
      emit();
    }
  }).catch(() => {});

  // 2. Real-time WebSocket connection to backend
  const stopSocket = startLiveFleetSocket(
    (event) => {
      if (!event || !event.type) return;

      if (event.type === 'cycle.tick') {
        if (event.payload && event.payload.cycle != null) {
          app.cycle = event.payload.cycle;
          emit();
        }
      } else if (event.type === 'health.updated') {
        const { aircraft, health, rul } = event.payload || {};
        const e = fleet.find((f) => f.id === aircraft);
        if (e) {
          if (health != null) {
            e.d = clamp(1 - health, 0, 0.99);
            e.hist.push(clamp(health, 0, 1));
            if (e.hist.length > 61) e.hist.shift();
          }
          if (rul != null) {
            e.serverRul = rul;
          }
          emit();
        }
      } else if (event.type === 'alert.raised') {
        const a = event.payload;
        if (a && a.id) {
          const key = (a.aircraft_id - 1) + ':' + (a.part === 'engine' ? 'eng' : a.part);
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
        hydrateAlerts();
      } else {
        if (!fallbackTimer) {
          fallbackTimer = setInterval(fallbackTick, 1200);
        }
      }
    }
  );

  return () => {
    stopSocket();
    if (fallbackTimer) clearInterval(fallbackTimer);
  };
}

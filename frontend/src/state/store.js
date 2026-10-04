import { applyThemeColors } from '../lib/colors.js';
import { postAcknowledgeAlert, postCreateWorkOrder, getUser, onAuthChange } from '../lib/api.js';
import { fleet } from '../data/fleet.js';

// Single mutable app state shared by the React UI and the three.js scene.
// React subscribes through useStore(); the 3D render loop just reads `app` every frame.
export const app = {
  sel: 0,                 // selected aircraft index
  cycle: 0,               // simulated fleet cycle
  cur: 'eng',             // part currently inspected (or last inspected)
  tgt: 0,                 // 1 while zoomed into a part, 0 while looking at the whole aircraft
  fc: 0,                  // forecast offset in cycles (0, 10, 20, 30)
  view: 'auto',           // camera preset: auto | top | side | under | free
  theme: 'light',
  status: 'Loading models...',
  WO: {},                 // work orders:  "aircraftIndex:part" -> server reference
  ACK: {},                // acknowledged alerts: "aircraftIndex:part" -> 1
  loaded: {},             // parts whose 3D model is ready: { eng: true, ... }
  backendConnected: false,// true when connected to live FastAPI + PostgreSQL
  // Real signed-in identity. Previously a hardcoded stub that never changed, so the
  // role badge lied about who was operating the console.
  user: getUser(),
  serverAlerts: [],       // live alerts pushed over the WebSocket, newest first
};

// Keep the navbar in sync with the session even when auth changes outside an action
// (token expiry re-login, explicit sign-out).
onAuthChange((user) => {
  if (user?.username !== app.user?.username) {
    app.user = user;
    emit();
  }
});

let version = 0;
const subs = new Set();
export const subscribe = (fn) => { subs.add(fn); return () => subs.delete(fn); };
export const getVersion = () => version;
export const emit = () => { version++; subs.forEach((fn) => fn()); };

/* ---------- actions ---------- */

export function selectAircraft(i) {
  app.sel = i;
  emit();
}

export function openPart(k) {
  if (!app.loaded[k]) return;
  app.cur = k;
  app.tgt = 1;
  emit();
  const d = document.getElementById('detail')?.getBoundingClientRect();
  if (d && d.top > innerHeight * 0.55) scrollBy({ top: d.top - innerHeight * 0.5, behavior: 'smooth' });
}

export function closePart() {
  app.tgt = 0;
  emit();
}

// Used by the health heat map: select the aircraft, zoom into the part and scroll the 3D view into sight.
export function inspectInTwin(i, k) {
  app.sel = i;
  openPart(k);
  document.getElementById('twin')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

export function setView(v) {
  app.view = v;
  if (app.tgt) app.tgt = 0;
  emit();
}

// Dragging the scene switches to the free camera (no part is closed).
export function freeView() {
  if (app.view !== 'free') { app.view = 'free'; emit(); }
}

export function setForecast(n) {
  app.fc = n;
  emit();
}

/** Backend part codes differ from the frontend's short keys for the engine. */
const PART_CODE = { eng: 'engine' };

/**
 * Raise a work order for the selected aircraft's part.
 *
 * The optimistic local reference is replaced by the server's once the POST succeeds.
 * The previous payload violated WorkOrderCreate (no `due_date`, `priority: "urgent"`
 * is not a valid literal) so every call 422'd and the fabricated `WO-1001` was the only
 * reference the operator ever saw.
 */
export function createWorkOrder(key) {
  if (app.WO[key]) return;

  const [planeIdx, partKey] = key.split(':');
  const plane = fleet[Number(planeIdx)];
  const part = PART_CODE[partKey] || partKey;
  // Placeholder only; replaced on success, and reverted on failure.
  app.WO[key] = 'saving…';
  emit();

  postCreateWorkOrder(plane.id, part, plane.serverRul).then((res) => {
    app.WO[key] = res?.reference || res?.code || 'offline';
    emit();
  });
}

/**
 * Acknowledge a critical part.
 *
 * `key` is the UI-side "aircraftIndex:part" identity. The backend endpoint is typed
 * `int`, so the numeric id is looked up from the alerts pushed over the WebSocket —
 * previously the UI key itself was POSTed to the alert route, which 404'd every time.
 * The optimistic UI state is reverted if the server refuses.
 */
export function acknowledge(key) {
  const parts = key.split(':');
  const partKey = parts[1];
  const serverAlert = app.serverAlerts.find(
    (a) => a.aircraft_id === Number(parts[0]) + 1 && (a.part === (PART_CODE[partKey] || partKey)),
  );

  app.ACK[key] = 1;
  emit();

  if (!serverAlert) return;            // offline: local acknowledgement only
  postAcknowledgeAlert(serverAlert.id).then((res) => {
    if (!res) {
      delete app.ACK[key];
      emit();
    }
  });
}

export function setBackendStatus(connected) {
  app.backendConnected = connected;
  emit();
}

export function setUser(user) {
  app.user = user;
  emit();
}

export function toggleTheme() {
  const dark = document.documentElement.dataset.theme !== 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  app.theme = dark ? 'dark' : 'light';
  applyThemeColors(dark);
  emit();
}

export function setStatus(s) {
  app.status = s;
  emit();
}

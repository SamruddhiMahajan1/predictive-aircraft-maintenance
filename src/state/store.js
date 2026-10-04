import { applyThemeColors } from '../lib/colors.js';
import { postAcknowledgeAlert, postCreateWorkOrder } from '../lib/api.js';

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
  WO: {},                 // work orders:  "aircraftIndex:part" -> "WO-1001"
  ACK: {},                // acknowledged alerts: "aircraftIndex:part" -> 1
  loaded: {},             // parts whose 3D model is ready: { eng: true, ... }
  backendConnected: false,// true when connected to live FastAPI + PostgreSQL
  user: { username: 'commander', role: 'commander', full_name: 'Cmdr. A. Rao' },
  serverAlerts: [],
};

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

export function createWorkOrder(key) {
  if (!app.WO[key]) {
    app.WO[key] = 'WO-' + (1001 + Object.keys(app.WO).length);
    // Asynchronously sync with backend if connected
    const [planeIdx, part] = key.split(':');
    const planeCode = 'Fighter-0' + (parseInt(planeIdx, 10) + 1);
    postCreateWorkOrder(planeCode, part === 'eng' ? 'engine' : part).then((res) => {
      if (res && res.code) {
        app.WO[key] = res.code;
        emit();
      }
    }).catch(() => {});
  }
  emit();
}

export function acknowledge(id) {
  app.ACK[id] = 1;
  // If numeric or matched with server alerts, notify backend
  postAcknowledgeAlert(id).catch(() => {});
  emit();
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

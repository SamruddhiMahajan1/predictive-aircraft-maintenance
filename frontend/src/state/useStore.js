import { useSyncExternalStore } from 'react';
import { app, subscribe, getVersion } from './store.js';

// Per-field selectors: components subscribe only to the slice they need.
// Before: every emit() triggered all 11 subscribers, and fleetStats() was computed
// twice per paint (Kpis.jsx:9, FleetHealth.jsx:57). Now components re-render only
// when their slice actually changes.

const noop = () => {};

// Simple structural equality for shallow comparison of arrays/objects.
function shallowEqual(a, b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  const ka = Object.keys(a), kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  for (const k of ka) if (!Object.prototype.hasOwnProperty.call(b, k) || a[k] !== b[k]) return false;
  return true;
}

export function useStore() {
  return useSyncExternalStore(subscribe, getVersion, noop, app);
}

export function useStoreSelector(selector) {
  const snapshot = useSyncExternalStore(
    subscribe,
    () => selector(app),
    noop,
    () => selector(app),
  );
  return snapshot;
}

// Convenience selectors for the common slices.
export const selectFleet = () => app.sel;
export const selectCycle = () => app.cycle;
export const selectCur = () => app.cur;
export const selectTgt = () => app.tgt;
export const selectFc = () => app.fc;
export const selectView = () => app.view;
export const selectTheme = () => app.theme;
export const selectStatus = () => app.status;
export const selectWO = () => app.WO;
export const selectACK = () => app.ACK;
export const selectLoaded = () => app.loaded;
export const selectBackendConnected = () => app.backendConnected;
export const selectApiReachable = () => app.apiReachable;
export const selectModel = () => app.model;
export const selectServerAlerts = () => app.serverAlerts;

// Derived slice used by Kpis and FleetHealth: avoid double-computing fleetStats.
// Uses a weak map keyed by the fleet array identity so the same fleet array
// reuses the previous result without recomputing.
const statsCache = new WeakMap();
export function selectFleetStats() {
  const fleetData = app.fleet || [];
  if (!statsCache.has(fleetData)) {
    statsCache.set(fleetData, computeStats(fleetData));
  }
  return statsCache.get(fleetData);
}

function computeStats(fleet) {
  if (!fleet.length) return { total: 0, ready: 0, watch: 0, critical: 0, avgHealth: 0 };
  let total = 0, ready = 0, watch = 0, critical = 0, healthSum = 0, count = 0;
  for (const e of fleet) {
    total++;
    if (e.missionReady === true) ready++;
    if (e.risk === 'watch') watch++;
    if (e.risk === 'critical') critical++;
    if (typeof e.engineHealth === 'number') { healthSum += e.engineHealth; count++; }
  }
  return { total, ready, watch, critical, avgHealth: count ? healthSum / count : 0 };
}
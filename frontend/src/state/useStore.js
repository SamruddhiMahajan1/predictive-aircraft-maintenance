import { useSyncExternalStore } from 'react';
import { app, subscribe, getVersion } from './store.js';

// Re-renders the calling component whenever the store emits. Returns the shared state object.
//
// The store is a single mutable `app` object plus a version counter. The hook
// subscribes to the version (so every emit() forces a re-render) and returns
// the live `app` object. getVersion is used for both the snapshot and the
// server snapshot so SSR and client agree.
export function useStore() {
  useSyncExternalStore(subscribe, getVersion, getVersion);
  return app;
}

export function useStoreSelector(selector) {
  useSyncExternalStore(subscribe, getVersion, getVersion);
  return selector(app);
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

// Derived slice used by Kpis and FleetHealth. This is a plain derivation over
// the fleet module + derived API aggregates (lib/fleetStats.js), not a store
// subscription — callers must also call useStore() (or useStoreSelector) so
// they re-render when the store emits.
export { fleetStats as selectFleetStats } from '../lib/fleetStats.js';
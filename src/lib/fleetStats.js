import { fleet } from '../data/fleet.js';
import { KEYS } from '../data/parts.js';
import { ready, rul, ph, worst } from './health.js';

export const pc = (h) => Math.round(h * 100);
export const shortId = (e) => e.id.replace('Fighter-', 'F-');

// Fleet-wide numbers used by several dashboard panels.
export function fleetStats() {
  const n = fleet.length;
  const nr = fleet.filter(ready).length;
  const wa = fleet.map((e) => { const k = worst(e); return { e, k, h: ph(e, k) }; }).sort((a, b) => a.h - b.h);
  return {
    n,
    nr,
    nCrit: fleet.reduce((a, e) => a + KEYS.filter((k) => ph(e, k) <= 0.4).length, 0),
    avg: Math.round(fleet.reduce((a, e) => a + rul(e), 0) / n),
    lo: fleet.reduce((a, e) => (rul(e) < rul(a) ? e : a)),
    wa,            // each aircraft's weakest part, worst first
    w0: wa[0],
  };
}

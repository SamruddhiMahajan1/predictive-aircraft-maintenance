// Health model: wear -> health of each engine module and each subsystem, plus derived fleet metrics.
import { clamp } from './math.js';
import { ENG, W, PARTS, KEYS, AG, stock } from '../data/parts.js';
import { fleet } from '../data/fleet.js';
import { app } from '../state/store.js';

// Wear including the forecast offset.
export const D = (e) => clamp(e.d + app.fc * 0.0045, 0, 0.99);

// Engine module health (fan / hpc / hpt / lpt).
export const comp = (e, k) => clamp(1 - clamp(D(e) * W[k] * 1.25 + e.bias[k] * D(e)));

// Remaining engine cycles.
export const rul = (e) => (e.serverRul != null && app.fc === 0) ? e.serverRul : Math.round(125 * (1 - D(e)));

// Health of a top-level part.
export const ph = (e, k) => (k == 'eng' ? clamp(1 - D(e)) : clamp(1 - D(e) * PARTS[k].f + e.off[k]));

export const ready = (e) => rul(e) > 30 && KEYS.every((k) => ph(e, k) > 0.4);
export const worst = (e) => KEYS.reduce((a, k) => (ph(e, k) < ph(e, a) ? k : a), 'eng');

// Weakest engine module (the one whose spare would be needed).
export const weakestModule = (e) => Object.keys(W).reduce((a, c) => (comp(e, c) < comp(e, a) ? c : a), 'fan');

// Spares in stock for a part.
export const stk = (e, k) => (k == 'eng' ? stock[weakestModule(e)] : PARTS[k].sp.s);

// Days until the part is back in service (agency slot + turnaround + spare lead time if out of stock).
export const backIn = (e, k) => {
  const a = AG[PARTS[k].ag];
  return a.slot + a.tat + (stk(e, k) > 0 ? 0 : PARTS[k].sp.lead);
};

// Health of the three sub-components of a subsystem (tank/pump/valves, tyres/struts/actuator...).
const SV = [[-0.22, 0.1, 0.06], [0.08, -0.24, 0.1], [0.1, 0.08, -0.26]];
export const subH = (e, k, i) => clamp(ph(e, k) + (k == 'fuel' ? SV[fleet.indexOf(e) % 3][i] : (i - 1) * 0.06));

export { ENG };

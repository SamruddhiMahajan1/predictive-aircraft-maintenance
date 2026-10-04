import { fleet } from '../data/fleet.js';
import { PARTS, AG } from '../data/parts.js';
import { app } from '../state/store.js';
import { hc, rk } from './colors.js';
import { ph, worst, rul, stk, backIn } from './health.js';

export const PLAN_HEADERS = ['Aircraft', 'Part', 'Risk', 'Action', 'Do by', 'Spare', 'Agency', 'Back in service'];

// One row per aircraft: its weakest part and what to do about it.
export function planRows() {
  return fleet.map((e, i) => {
    const k = worst(e), h = ph(e, k), r = rk(h), a = AG[PARTS[k].ag], s = stk(e, k);
    const healthy = r == 'healthy';
    return {
      id: e.id,
      part: PARTS[k].name,
      risk: r,
      color: hc(h),
      action: healthy ? 'Routine check' : r == 'watch' ? 'Plan inspection' : 'Replace now',
      wo: app.WO[i + ':' + k] || '',
      doBy: healthy ? '-' : 'within ' + Math.max(0, rul(e) - 10) + ' cycles',
      spare: healthy ? '-' : s > 0 ? s + ' in stock' : 'out of stock',
      spareBad: !(s > 0 || healthy),
      agency: a.n,
      back: healthy ? '-' : '~' + backIn(e, k) + ' days',
    };
  });
}

// CSV text of the maintenance plan (same cell text as shown in the table).
export function planCsv() {
  const q = (v) => '"' + String(v).replace(/"/g, '""') + '"';
  const rows = planRows().map((r) => [r.id, r.part, r.risk, r.action + (r.wo ? ' ' + r.wo : ''), r.doBy, r.spare, r.agency, r.back]);
  return [PLAN_HEADERS, ...rows].map((row) => row.map(q).join(',')).join('\n');
}

export function downloadPlanCsv() {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([planCsv()], { type: 'text/csv' }));
  a.download = 'maintenance-plan.csv';
  a.click();
}

import { useStore } from '../state/useStore.js';
import { fleet } from '../data/fleet.js';
import { PARTS } from '../data/parts.js';
import { ready, rul } from '../lib/health.js';
import { fleetStats, pc, shortId } from '../lib/fleetStats.js';

export default function Kpis() {
  const app = useStore();
  const { n, nr, nCrit, avg, lo, w0 } = fleetStats();
  return (
    <div className="kpis">
      <div className="kp" data-tip={'Aircraft with over 30 engine cycles left\nand every part above 40% health.'}>
        <div className="kpi" id="avail">{nr + ' of ' + n}<small>Mission-ready</small></div>
        <p className="kd" id="d-avail">{nr == n ? 'Every aircraft can fly' : 'Grounded: ' + fleet.filter((e) => !ready(e)).map(shortId).join(', ')}</p>
      </div>
      <div className="kp" data-tip="Parts at or below 40% health, across all aircraft.">
        <div className="kpi" id="crit">{nCrit}<small>Critical parts</small></div>
        <p className="kd" id="d-crit">{'Lowest: ' + shortId(w0.e) + ' ' + PARTS[w0.k].name.toLowerCase() + ', ' + pc(w0.h) + '%'}</p>
      </div>
      <div className="kp" data-tip="Engine life is simulated from a C-MAPSS stream.">
        <div className="kpi" id="life">{avg}<small>Avg engine cycles left</small></div>
        <p className="kd" id="d-life">{'Lowest: ' + shortId(lo) + ', ' + rul(lo) + ' cycles'}</p>
      </div>
      <div className="kp">
        <div className="kpi" id="cyc">{app.cycle}<small>Fleet cycle</small></div>
        <p className="kd" id="d-cyc">One cycle every 1.2 s in this simulation</p>
      </div>
    </div>
  );
}

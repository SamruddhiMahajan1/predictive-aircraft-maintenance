import { useStore } from '../state/useStore.js';
import { PARTS, AG } from '../data/parts.js';
import { rk } from '../lib/colors.js';
import { stk, backIn } from '../lib/health.js';
import { fleetStats, pc } from '../lib/fleetStats.js';

// The five aircraft whose weakest part is in the worst shape.
export default function NeedsAttention() {
  useStore();
  const { wa } = fleetStats();
  return (
    <section className="pn s7 rv" id="attention">
      <div className="hd"><h2>Needs attention</h2><p>Weakest part on each aircraft, worst first</p></div>
      <ul id="acts">
        {wa.slice(0, 5).map((x) => {
          const r = rk(x.h), a = AG[PARTS[x.k].ag], s = stk(x.e, x.k);
          return (
            <li key={x.e.id} className={r}>
              <b>{x.e.id}</b>{', ' + PARTS[x.k].name.toLowerCase() + ' at ' + pc(x.h) + '%'}
              <small>{(r == 'healthy' ? 'No action needed' : r == 'watch' ? 'Plan an inspection' : 'Replace now') + '. ' + (s > 0 ? s + ' spare in stock' : 'No spare in stock') + '. ' + a.n + ', back in about ' + backIn(x.e, x.k) + ' days.'}</small>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

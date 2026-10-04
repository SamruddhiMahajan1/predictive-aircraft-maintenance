import { useStore } from '../state/useStore.js';
import { inspectInTwin } from '../state/store.js';
import { fleet } from '../data/fleet.js';
import { PARTS, KEYS, AG } from '../data/parts.js';
import { rk } from '../lib/colors.js';
import { ph, stk, backIn } from '../lib/health.js';
import { pc, shortId } from '../lib/fleetStats.js';

// Aircraft x part grid. Clicking a cell opens that part in 3D.
export default function HealthHeatmap() {
  const app = useStore();
  return (
    <section className="pn s7 rv">
      <div className="hd"><h2>Health by part</h2><p>Select a cell to inspect that part in 3D</p></div>
      <div className="scroll">
        <table id="heat">
          <thead>
            <tr>
              <th></th>
              {KEYS.map((k) => <th key={k}>{PARTS[k].name.split(' ')[0]}</th>)}
            </tr>
          </thead>
          <tbody>
            {fleet.map((e, i) => (
              <tr key={e.id}>
                <th className={i == app.sel ? 'on' : ''}>{shortId(e)}</th>
                {KEYS.map((k) => {
                  const h = ph(e, k), r = rk(h), a = AG[PARTS[k].ag], s = stk(e, k);
                  const tip = e.id + ', ' + PARTS[k].name + '\nHealth ' + pc(h) + '% (' + r + ')\nSpare: ' +
                    (s > 0 ? s + ' in stock' : 'out of stock, ' + (k == 'eng' ? 21 : PARTS[k].sp.lead) + ' day lead time') +
                    '\n' + a.n + ': slot in ' + a.slot + ' days\nBack in service in about ' + backIn(e, k) + ' days\nClick to inspect in 3D';
                  return (
                    <td key={k}>
                      <button className={'cell ' + r} data-i={i} data-k={k} data-tip={tip} onClick={() => inspectInTwin(i, k)}>{pc(h)}</button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

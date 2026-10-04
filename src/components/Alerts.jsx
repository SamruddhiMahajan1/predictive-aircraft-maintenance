import { useStore } from '../state/useStore.js';
import { acknowledge } from '../state/store.js';
import { fleet } from '../data/fleet.js';
import { PARTS, KEYS } from '../data/parts.js';
import { ph } from '../lib/health.js';
import { pc } from '../lib/fleetStats.js';

// Critical parts (health <= 40%), worst first, up to 8.
export default function Alerts() {
  const app = useStore();
  const alerts = [];
  fleet.forEach((e, i) => KEYS.forEach((k) => { const h = ph(e, k); if (h <= 0.4) alerts.push({ id: i + ':' + k, e, k, h }); }));
  alerts.sort((x, y) => x.h - y.h);

  return (
    <section className="pn s12 rv" id="alerts">
      <div className="hd"><h2>Alerts</h2><p>Critical parts, worst first</p></div>
      <ul id="alist">
        {alerts.slice(0, 8).map((x) => {
          const ack = app.ACK[x.id];
          return (
            <li key={x.id} className={ack ? 'ack' : ''}>
              <span>
                <b>{x.e.id}</b>{' ' + PARTS[x.k].name + ', '}<span className="mono">{pc(x.h) + '%'}</span>
                <small>{ack ? 'Acknowledged' : 'Critical, needs action'}</small>
              </span>
              {ack ? null : <button className="wo" onClick={() => acknowledge(x.id)}>Acknowledge</button>}
            </li>
          );
        })}
        {alerts.length ? null : <li><span className="note">No critical parts.</span></li>}
      </ul>
    </section>
  );
}

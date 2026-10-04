import { useStore } from '../state/useStore.js';
import { selectAircraft } from '../state/store.js';
import { fleet } from '../data/fleet.js';
import { PARTS, KEYS } from '../data/parts.js';
import { C, hc, rk } from '../lib/colors.js';
import { ph, rul, ready, worst } from '../lib/health.js';
import { fleetStats, pc } from '../lib/fleetStats.js';

// "Parts status" stacked bar + average health per subsystem.
function PartsMix() {
  const c = { h: 0, w: 0, c: 0 };
  const rows = KEYS.map((k) => {
    let sum = 0, cr = 0;
    fleet.forEach((e) => { const v = ph(e, k); sum += v; const r = rk(v); c[r[0]]++; if (r == 'critical') cr++; });
    return [PARTS[k].name, sum / fleet.length, cr];
  });
  const n = fleet.length * KEYS.length;
  return (
    <div id="hmix">
      <h3>{'Parts status, ' + n + ' parts'}</h3>
      <div className="stk">
        <i style={{ flex: c.h, background: C.ok }}></i>
        <i style={{ flex: c.w, background: C.warn }}></i>
        <i style={{ flex: c.c, background: C.bad }}></i>
      </div>
      <div className="stl">
        <span><b>{c.h}</b> healthy</span>
        <span><b>{c.w}</b> watch</span>
        <span><b>{c.c}</b> critical</span>
      </div>
      <h3 style={{ marginTop: 6 }}>Average health by subsystem</h3>
      {rows.sort((a, b) => a[1] - b[1]).map((r) => (
        <div className="hmr" key={r[0]}>
          <span>{r[0]}</span>
          <div className="bar"><i style={{ width: r[1] * 100 + '%', background: hc(r[1]) }}></i></div>
          <span className="mono">{Math.round(r[1] * 100) + '%'}</span>
          <span className="cr" style={{ color: r[2] ? C.bad : 'var(--mut)' }}>{r[2] ? r[2] + ' crit' : 'ok'}</span>
        </div>
      ))}
    </div>
  );
}

export default function FleetHealth() {
  const app = useStore();
  const { n, nr } = fleetStats();
  return (
    <section className="pn s5 rv" id="health">
      <div className="hd"><h2>Fleet health</h2><p>Engine life left, per aircraft</p></div>
      <div className="hgrid">
        <div
          id="donut"
          style={{ '--p': (nr / n) * 100 + '%' }}
          data-tip={nr + ' of ' + n + ' aircraft are mission-ready\nMission-ready: over 30 engine cycles left\nand every part above 40% health'}
        >
          <div id="dn">{pc(nr / n) + '%'}</div>
        </div>
        <div>
          <div id="vbars">
            {fleet.map((e, i) => {
              const k = worst(e);
              return (
                <button
                  key={e.id}
                  className={'vb ' + (i == app.sel ? 'on' : '')}
                  data-i={i}
                  data-tip={e.id + '\nEngine life left: ' + rul(e) + ' of 125 cycles\nWeakest part: ' + PARTS[k].name + ', ' + pc(ph(e, k)) + '%\n' + (ready(e) ? 'Mission-ready' : 'Not mission-ready') + '\nClick to select'}
                  onClick={() => selectAircraft(i)}
                >
                  <span className="trk"><i className={ready(e) ? '' : 'bad'} style={{ height: Math.max(4, (rul(e) / 125) * 100) + '%' }}></i></span>
                  <em>{i + 1}</em>
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <PartsMix />
    </section>
  );
}

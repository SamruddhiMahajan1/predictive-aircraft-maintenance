import { app, openPart } from '../../state/store.js';
import { PARTS, KEYS, AG } from '../../data/parts.js';
import { C, hc } from '../../lib/colors.js';
import { ph, ready, rul, stk } from '../../lib/health.js';

// Inspector while the whole aircraft is shown: readiness + list of parts.
export default function AircraftSummary({ e }) {
  const ok = ready(e);
  return (
    <>
      <div className="blk">
        <h2>{e.id}</h2>
        <div className="kpi" style={{ color: ok ? C.ok : C.bad }}>
          {ok ? 'Mission-ready' : 'Not ready'}
          <small>{`Engine remaining life: ${rul(e)} cycles`}</small>
        </div>
      </div>
      <h2>Parts (click to inspect)</h2>
      {KEYS.map((k) => {
        const h = ph(e, k), a = AG[PARTS[k].ag], s = stk(e, k);
        return (
          <button key={k} className="prt" data-k={k} onClick={() => openPart(k)}>
            <div className="row" style={{ margin: 0 }}>
              <span><span className="dot" style={{ background: hc(h) }}></span>{PARTS[k].name}</span>
              <span className="mono" style={{ color: hc(h) }}>{Math.round(h * 100) + '%'}</span>
            </div>
            <div className="bar"><i style={{ width: h * 100 + '%', background: hc(h) }}></i></div>
            <p className="note">{'Spare: ' + (s > 0 ? s + ' in stock' : 'out of stock') + ' - ' + a.n}</p>
          </button>
        );
      })}
      <p className="note" style={{ marginTop: 14 }}>Engine life comes from a simulated C-MAPSS stream. Other parts use simulated health.</p>
    </>
  );
}

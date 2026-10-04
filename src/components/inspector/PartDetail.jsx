import { app, createWorkOrder } from '../../state/store.js';
import { ENG, W, PARTS, AG } from '../../data/parts.js';
import { C, hc, rk } from '../../lib/colors.js';
import { comp, ph, rul, stk, backIn, subH, weakestModule } from '../../lib/health.js';
import SubBar from './SubBar.jsx';
import SensorTable from './SensorTable.jsx';

// Inspector while a part is zoomed in: health, sub-components, records, spares, agency, sensors, work order.
export default function PartDetail({ e }) {
  const k = app.cur, p = PARTS[k], h = ph(e, k), a = AG[p.ag], s = stk(e, k), bk = backIn(e, k);
  const eng = k == 'eng';
  const sp = eng ? ENG[weakestModule(e)] + ' module' : p.sp.item;
  const woKey = app.sel + ':' + k;
  const wo = app.WO[woKey];

  return (
    <>
      <div className="blk">
        <h2>Health</h2>
        <div className="kpi" style={{ color: hc(h) }}>
          {Math.round(h * 100) + '%'}
          <small>{rk(h) + (eng ? ' - ' + rul(e) + ' cycles left' : '')}</small>
        </div>
      </div>
      {eng
        ? Object.keys(W).map((c) => <SubBar key={c} name={ENG[c]} h={comp(e, c)} />)
        : p.subs.map((n, i) => <SubBar key={n} name={n} h={subH(e, k, i)} />)}
      {eng ? <canvas id="hc" width="560" height="180"></canvas> : null}
      <div className="card">
        <h3>Technical records</h3>
        {p.rec.map((r, i) => <p key={r}>{`Cycle ${Math.max(0, app.cycle - 14 - i * 37)}: ${r}`}</p>)}
      </div>
      <div className="card">
        <h3>Spares</h3>
        <p>{sp + ': '}<b style={{ color: s > 0 ? 'inherit' : C.bad }}>{s > 0 ? s + ' in stock' : 'out of stock'}</b></p>
        <p className="note">{`Lead time ${eng ? 21 : p.sp.lead} days if ordered`}</p>
      </div>
      <div className="card">
        <h3>Maintenance agency</h3>
        <p>{`${a.n}: free slot in ${a.slot} days`}</p>
        <p className="note">{`Turnaround ${a.tat} days. Back in service in about ${bk} days.`}</p>
      </div>
      {eng ? <SensorTable e={e} /> : null}
      {rk(h) == 'healthy' ? null : (
        <button className="wo" onClick={() => createWorkOrder(woKey)}>{wo ? wo + ' created' : 'Create work order'}</button>
      )}
      <p className="note">{(eng ? 'Health from a simulated C-MAPSS stream.' : 'Simulated health and records.') + (p.real ? '' : ' Part model is illustrative.')}</p>
    </>
  );
}

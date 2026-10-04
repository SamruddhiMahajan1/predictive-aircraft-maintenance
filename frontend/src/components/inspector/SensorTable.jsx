import { ENG } from '../../data/parts.js';
import { SENS } from '../../data/sensors.js';
import { hc } from '../../lib/colors.js';
import { comp } from '../../lib/health.js';

// Simulated live sensors of the engine, biggest deviation first.
export default function SensorTable({ e }) {
  const rows = SENS.map(([id, n, u, b, dr, m, c]) => {
    const dv = dr * (1 - comp(e, c)) * m;
    return { id, n, u, c, v: b * (1 + dv / 100), dv };
  }).sort((x, y) => Math.abs(y.dv) - Math.abs(x.dv));

  return (
    <div className="card sx">
      <h3>Live sensors, top contributors first (simulated)</h3>
      <table className="st">
        <thead>
          <tr><th>Sensor</th><th>Part</th><th>Value</th><th>Deviation</th></tr>
        </thead>
        <tbody>
          {rows.map((x) => {
            const q = hc(1 - Math.abs(x.dv) / 3);
            return (
              <tr key={x.id}>
                <td>{x.id} <span className="note">{x.n}</span></td>
                <td>{ENG[x.c]}</td>
                <td className="mono">{x.v.toFixed(x.v > 1000 ? 0 : x.v > 100 ? 1 : 2)} <span className="note">{x.u}</span></td>
                <td className="mono">
                  <span className="dv" style={{ color: q }}>{(x.dv >= 0 ? '+' : '') + x.dv.toFixed(2) + '%'}</span>
                  <div className="bar"><i style={{ width: Math.min(100, (Math.abs(x.dv) / 3) * 100) + '%', background: q }}></i></div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

import { fleet } from '../data/fleet.js';
import { pc } from '../lib/fleetStats.js';
import { useStore } from '../state/useStore.js';

// Fleet average and weakest-aircraft engine health over the last 60 cycles.
//
// The useStore() subscription is load-bearing: `fleet[].hist` is mutated in place by
// the telemetry stream, so without it React never re-rendered this panel and the chart
// froze at its mount-time shape while every other panel tracked the live data.
export default function TrendChart() {
  useStore();
  const n = fleet.length, L = fleet[0].hist.length, A = [], M = [];
  for (let j = 0; j < L; j++) {
    const v = fleet.map((e) => e.hist[j]);
    A.push(v.reduce((a, b) => a + b, 0) / n);
    M.push(Math.min(...v));
  }
  const X = (j) => (j / (L - 1)) * 400, Y = (v) => 140 - v * 130;
  const P = (a) => a.map((v, j) => X(j).toFixed(1) + ',' + Y(v).toFixed(1)).join(' ');

  return (
    <section className="pn s5 rv">
      <div className="hd"><h2>Fleet engine trend</h2><p>Last 60 cycles</p></div>
      <svg id="trend" viewBox="0 0 400 150" role="img" aria-label="Fleet engine health over the last 60 cycles">
        <defs>
          <linearGradient id="tg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#800020" stopOpacity=".25" />
            <stop offset="1" stopColor="#800020" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((g) => <line key={g} x1="0" x2="400" y1={Y(g)} y2={Y(g)} stroke="rgba(0,0,0,.08)" />)}
        <polygon points={'0,140 ' + P(A) + ' 400,140'} fill="url(#tg)" />
        <polyline points={P(M)} fill="none" stroke="#D45060" strokeWidth="1.6" strokeDasharray="4 3" />
        <polyline points={P(A)} fill="none" stroke="#800020" strokeWidth="2.2" />
        {A.map((v, j) => (
          <rect
            key={j}
            className="hz"
            x={X(j) - 3.3}
            y="0"
            width="6.6"
            height="140"
            data-tip={(j == L - 1 ? 'Now' : L - 1 - j + ' cycles ago') + '\nFleet average: ' + pc(v) + '%\nWeakest aircraft: ' + pc(M[j]) + '%'}
          />
        ))}
      </svg>
      <div className="lg">
        <span><i></i>Fleet average</span>
        <span><i className="d"></i>Weakest aircraft</span>
      </div>
    </section>
  );
}

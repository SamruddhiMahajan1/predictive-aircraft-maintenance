import { clamp } from './math.js';
import { hc } from './colors.js';
import { ph } from './health.js';

// Engine-health history drawn on the inspector's <canvas id="hc">.
export function drawHistoryChart(e) {
  const c = document.getElementById('hc');
  if (!c) return;
  const x = c.getContext('2d'), w = c.width, h = c.height;
  x.clearRect(0, 0, w, h);
  x.strokeStyle = 'rgba(128,0,32,.12)';
  for (let i = 0; i < 4; i++) { x.beginPath(); x.moveTo(0, (i * h) / 3); x.lineTo(w, (i * h) / 3); x.stroke(); }
  const d = e.hist, col = hc(ph(e, 'eng'));
  x.beginPath();
  d.forEach((p, i) => { const px = (i / (d.length - 1)) * w, py = h - clamp(p) * h; i ? x.lineTo(px, py) : x.moveTo(px, py); });
  x.strokeStyle = col; x.lineWidth = 3; x.stroke();
  x.lineTo(w, h); x.lineTo(0, h); x.fillStyle = col + '22'; x.fill();
}

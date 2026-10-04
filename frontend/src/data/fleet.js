import { clamp } from '../lib/math.js';

// Initial wear (0 = new, 1 = end of life) of the eight simulated aircraft.
const d0 = [0.15, 0.35, 0.55, 0.8, 0.92, 0.25, 0.7, 0.1];

export const fleet = d0.map((d, i) => ({
  id: 'Fighter-0' + (i + 1),
  d,
  bias: { fan: Math.sin(i * 2) * 0.15, hpc: Math.cos(i) * 0.1, hpt: Math.sin(i * 5) * 0.12, lpt: Math.cos(i * 3) * 0.1 },
  off: { radar: Math.sin(i * 3) * 0.12, gear: Math.cos(i * 2) * 0.12, hyd: Math.sin(i * 7) * 0.12, fuel: Math.cos(i * 5) * 0.1 },
  hist: [],
}));

// 61 points of engine-health history per aircraft.
fleet.forEach((e) => {
  for (let k = 60; k >= 0; k--) e.hist.push(clamp(1 - (e.d - k * 0.004) + (Math.random() - 0.5) * 0.02));
});

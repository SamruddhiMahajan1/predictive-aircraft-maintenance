// Static configuration of the aircraft: engine modules, subsystems, spares and maintenance agencies.

export const ENG = { fan: 'Fan', hpc: 'HPC', hpt: 'HPT', lpt: 'LPT' };
// How strongly each engine module degrades with engine wear.
export const W = { fan: 0.6, hpc: 1, hpt: 0.4, lpt: 0.25 };

// Centre of the jet model, used to centre it in the scene.
export const JC = [28.8, 6, 0];

// a/n: arrow anchor + normal, t/d: ray target + direction used to snap arrows onto the jet surface.
// f: how fast the part wears, sp: spare part (stock s, lead time in days), ag: agency index, rec: technical records.
export const PARTS = {
  eng: { name: 'Engine', a: [-32, 3, 0], n: [0, 1, 0], t: [-30, 4, 0], d: [-0.45, 0.35, 1], real: 1, subs: ['Fan', 'HPC', 'HPT', 'LPT'], sp: { item: 'HPC module', s: 2, lead: 21 }, ag: 0, rec: ['Borescope check, no defect', 'Oil filter replaced'] },
  radar: { name: 'Radar and avionics', a: [104, -2.5, 0], n: [1, 0.45, 0.2], t: [96, 2, 0], d: [1, 0.35, 0.45], f: 0.35, subs: ['Antenna array', 'Gimbal drive', 'Transmitter'], sp: { item: 'Antenna array', s: 1, lead: 35 }, ag: 2, rec: ['Software update applied', 'Gimbal calibration'] },
  gear: { name: 'Landing gear', a: [30, -7, 0], n: [0, -1, 0], t: [28, -6, 0], d: [0.1, -1, 0.35], f: 0.5, subs: ['Tyres', 'Struts', 'Retract actuator'], sp: { item: 'Retract actuator', s: 3, lead: 14 }, ag: 0, rec: ['Tyre change', 'Strut seal inspection'] },
  hyd: { name: 'Hydraulics', a: [-18, 0, 28], n: [0, 1, 0], t: [-8, -3, 28], d: [0, 1, 0.15], f: 0.7, subs: ['Pump', 'Servo actuator', 'Lines'], sp: { item: 'Servo actuator', s: 0, lead: 28 }, ag: 1, rec: ['Pressure drop logged', 'Fluid top-up'] },
  fuel: { name: 'Fuel system', a: [-2, 11, 0], n: [0, 1, 0], t: [-2, 12, 0], d: [0, 1, 0], f: 0.3, subs: ['Tank', 'Boost pump', 'Valves'], sp: { item: 'Boost pump', s: 4, lead: 10 }, ag: 1, rec: ['Pump inspected', 'Valve replaced'] },
};

export const KEYS = Object.keys(PARTS);

// Maintenance agencies: free slot (days), turnaround (days).
export const AG = [
  { n: 'Depot Alpha', slot: 2, tat: 6 },
  { n: 'Depot Bravo', slot: 5, tat: 4 },
  { n: 'OEM service', slot: 9, tat: 12 },
];

// Engine module spares in stock.
export const stock = { fan: 1, hpc: 2, hpt: 0, lpt: 1 };

// Simulated C-MAPSS-style sensors: [id, name, unit, baseline, direction, magnitude, engine module].
export const SENS = [
  ['s2', 'LPC outlet temp', 'R', 642.5, 1, 0.6, 'fan'],
  ['s3', 'HPC outlet temp', 'R', 1589.7, 1, 1.4, 'hpc'],
  ['s4', 'LPT outlet temp', 'R', 1408, 1, 1.8, 'lpt'],
  ['s7', 'HPC outlet pressure', 'psia', 554.4, -1, 1.2, 'hpc'],
  ['s8', 'Fan speed', 'rpm', 2388.1, 1, 0.3, 'fan'],
  ['s9', 'Core speed', 'rpm', 9046.2, 1, 0.9, 'hpc'],
  ['s11', 'HPC static pressure', 'psia', 47.5, 1, 1, 'hpc'],
  ['s12', 'Fuel flow ratio', 'pps/psi', 521.7, -1, 1.1, 'hpc'],
  ['s13', 'Corrected fan speed', 'rpm', 2388.1, 1, 0.35, 'fan'],
  ['s14', 'Corrected core speed', 'rpm', 8138.6, 1, 1.2, 'hpc'],
  ['s15', 'Bypass ratio', '', 8.42, -1, 0.8, 'fan'],
  ['s17', 'Bleed enthalpy', '', 392, 1, 1.6, 'hpt'],
  ['s20', 'HPT coolant bleed', 'lbm/s', 39, -1, 2.4, 'hpt'],
  ['s21', 'LPT coolant bleed', 'lbm/s', 23.4, -1, 2.1, 'hpt'],
];

// Status colours. `C` is mutated when the theme changes (see applyThemeColors).
export const COLORS_LIGHT = { ok: '#4f8a6b', warn: '#c8902e', bad: '#800020' };
export const COLORS_DARK = { ok: '#6fbf94', warn: '#e0a64a', bad: '#e0506b' };

export const C = { ...COLORS_LIGHT };

export const hc = (h) => (h > 0.7 ? C.ok : h > 0.4 ? C.warn : C.bad);
export const rk = (h) => (h > 0.7 ? 'healthy' : h > 0.4 ? 'watch' : 'critical');

export function applyThemeColors(dark) {
  Object.assign(C, dark ? COLORS_DARK : COLORS_LIGHT);
}

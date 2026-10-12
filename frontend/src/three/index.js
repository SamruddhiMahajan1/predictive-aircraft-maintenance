import { ctx, rt, resetContext } from './context.js';
import { setStatus } from '../state/store.js';
import { createScene, resize } from './scene.js';
import { buildHydraulics } from './models/hydraulics.js';
import { buildFuelSystem } from './models/fuelSystem.js';
import { buildArrows } from './arrows.js';
import { createEngineTags } from './models/engine.js';
import { loadJet } from './models/jet.js';
import { attachInteraction } from './interaction.js';
import { startLoop } from './loop.js';

// Builds the whole 3D twin inside `stage` (a DOM element) and returns { dispose }.
export function createTwin(stage) {
  resetContext();
  createScene(stage);
  buildHydraulics();      // procedural models are ready immediately
  buildFuelSystem();
  buildArrows();          // hotspot arrows + HTML labels
  createEngineTags();
  const detach = attachInteraction();
  resize();
  startLoop();

  // Real models stream in from /public/models. The hero jet loads first so the
  // stage becomes meaningful as fast as possible; gear/radar/engine follow in
  // the background. Previously Promise.all() held the "Loading models…" status
  // until the slowest of the four finished.
  // Phase 4.8: the 3 non-hero models (~6.1 MB) are dynamic-imported only after
  // the hero paints (idle callback, 1.5 s fallback) — nothing off the critical
  // path. Static imports would bundle and fetch them with the initial chunk.
  loadJet()
    .then(() => {
      if (!ctx.disposed) setStatus('Drag to rotate. Click a label to inspect a part.');
      const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1500));
      idle(() => {
        if (ctx.disposed) return;
        Promise.all([
          import('./models/landingGear.js').then((m) => m.loadLandingGear()),
          import('./models/radar.js').then((m) => m.loadRadar()),
          import('./models/engine.js').then((m) => m.loadEngine()),
        ]).catch((e) => {
          if (!ctx.disposed) setStatus('Could not load a model: ' + e.message);
        });
      });
    })
    .catch((e) => { if (!ctx.disposed) setStatus('Could not load a model: ' + e.message); });

  return {
    dispose() {
      ctx.disposed = true;
      cancelAnimationFrame(rt.raf);
      detach();
      stage.querySelectorAll('canvas, .hs, .tag, .fstat').forEach((n) => n.remove());

      // FE7: R.dispose() alone frees nothing — geometries, materials, textures,
      // and the PMREM render target must be disposed explicitly, and the GL
      // context must be asked to force loss so the GPU driver releases memory.
      if (ctx.R) {
        // Traverse the entire scene graph and dispose every GL resource.
        if (ctx.S) {
          ctx.S.traverse((obj) => {
            if (obj.geometry) obj.geometry.dispose();
            if (obj.material) {
              if (Array.isArray(obj.material)) {
                obj.material.forEach((m) => m.dispose());
              } else {
                obj.material.dispose();
              }
            }
          });
        }
        ctx.R.dispose();
        ctx.R.forceContextLoss?.();
      }
    },
  };
}

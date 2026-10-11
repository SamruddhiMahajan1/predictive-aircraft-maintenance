import * as THREE from 'three';
import { ctx, rt } from './context.js';
import { app } from '../state/store.js';
import { fleet } from '../data/fleet.js';
import { PARTS } from '../data/parts.js';
import { subH } from '../lib/health.js';
import { SFG, SFM } from './config.js';

const FRAG_COMMON = 
  '#include <common>\n' +
  'varying float vT;\n' +
  'uniform vec3 uH;\n' +
  'uniform float uT;\n' +
  'float zn(float a,float b,float t){return smoothstep(a-.02,a+.02,t)*' +
  '(1.-smoothstep(b-.02,b+.02,t));}';

const FRAG_EMISSIVE = 
  'totalEmissiveRadiance+=vec3(1.,.04,.04)*smoothstep(.35,.65,dmg)*' +
  '(.3+.25*sin(uT*5.));';

const FRAG_COLOR = (d) => 
  'float dmg=' + d + ';' +
  '\ndiffuseColor.rgb=mix(diffuseColor.rgb,vec3(.9,.03,.03),smoothstep(.2,.6,dmg));';

const { PR } = ctx;

// Three HTML tags + a status line shared by the sub-fault models.
export function sfTags() {
  const { stage } = ctx;
  if (!ctx.SF) {
    const t = (c) => {
      const d = document.createElement('div');
      d.className = c;
      stage.appendChild(d);
      return d;
    };
    ctx.SF = { a: t('tag'), b: t('tag'), c: t('tag'), s: t('fstat') };
  }
  return [ctx.SF.a, ctx.SF.b, ctx.SF.c];
}

// Red pulsing halos at the damage zones.
export function sfHalos(o, an, r) {
  return an.map((p) => {
    const m = new THREE.Mesh(
      new THREE.SphereGeometry(r, 20, 14),
      new THREE.MeshBasicMaterial({ color: 0xff2a2a, transparent: true, opacity: 0, depthWrite: false })
    );
    m.position.set(p[0], p[1], p[2]);
    o.add(m);
    return m;
  });
}

// Prepare a GLB so that three zones along its axis can show damage (shader patch).
// FE7 fix: was cloning geometry and material per model (m.geometry.clone(), m.material.clone()),
// doubling the resident set. Now the GLB is prepared in-place and the shader patch uses
// the existing material without cloning.
export function setupGlb(o, k) {
  const c = SFG[k];
  o.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(o.matrixWorld).invert();
  const ms = [];
  o.traverse((m) => {
    if (m.isMesh) ms.push(m);
  });
  let mn = 1e9, mx = -1e9;
  const A = 'xyz'[c.ax];
  ms.forEach((m) => {
    // In-place transform instead of cloning: the GLB is only prepared once,
    // so we can mutate its geometry directly.
    m.geometry.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, m.matrixWorld));
    m.position.set(0, 0, 0);
    m.quaternion.identity();
    m.scale.set(1, 1, 1);
    o.add(m);
    m.geometry.computeBoundingBox();
    mn = Math.min(mn, m.geometry.boundingBox.min[A]);
    mx = Math.max(mx, m.geometry.boundingBox.max[A]);
  });
  const U = { uH: { value: new THREE.Vector3(1, 1, 1) }, uT: { value: 0 } };
  const len = mx - mn;
  o.userData.U = U;
  // Material is patched in-place (no clone) — the shader variant is keyed by 'sf'+k.
  ms.forEach((m) => {
    const mt = m.material;
    mt.customProgramCacheKey = () => 'sf' + k;
    mt.onBeforeCompile = (sh) => {
      sh.uniforms.uH = U.uH;
      sh.uniforms.uT = U.uT;
      sh.vertexShader = sh.vertexShader
        .replace('#include <common>', '#include <common>\nvarying float vT;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvT=(position.' + A + '-(' + mn.toFixed(6) + '))/' + len.toFixed(6) + ';');
      const d = c.z.map((z) => 'zn(' + z[0].toFixed(3) + ',' + z[1].toFixed(3) + ',vT)*(1.-uH[' + z[2] + '])').join('+');
      sh.fragmentShader = sh.fragmentShader
        .replace('#include <common>', FRAG_COMMON)
        .replace('#include <color_fragment>', FRAG_COLOR(d))
        .replace('#include <emissivemap_fragment>', FRAG_EMISSIVE);
    };
  });
  o.userData.rng = [mn, len];
}

// Register a prepared GLB as an inspectable part.
export function finGlb(o, k) {
  const c = SFG[k];
  const an = c.an.map((p) => {
    const a = [0, 0, 0];
    a[c.ax] = p[c.ax];
    if (k == 'gear') {
      a[1] = p[1];
    }
    return a;
  });
  Object.assign(PR[k], {
    obj: o,
    U: o.userData.U,
    sf: { an: an.map((p) => new THREE.Vector3(...p)), halos: sfHalos(o, an, c.hr), tags: sfTags() },
  });
}

// Per-frame animation of a sub-fault part.
export function subFaultAnim(pr, t, dt, po) {
  const { stage, cam } = ctx;
  const k = app.cur;
  const e = fleet[app.sel];
  const H = [0, 1, 2].map((i) => subH(e, k, i));
  const known = H.every((x) => x != null);
  const H2 = H.map((x) => x ?? 1);
  const pul = .5 + .5 * Math.sin(t / 180);
  const w = stage.clientWidth;
  const h2 = stage.clientHeight;
  const sf = pr.sf;
  const bad = known && H2.some((x) => x < .6);
  if (pr.U) {
    pr.U.uH.value.set(H2[0], H2[1], H2[2]);
    pr.U.uT.value = t / 1000;
  }
  if (pr.mg)
    pr.mg.forEach((ms, i) => {
      const b = H2[i] < .6;
      const g = b ? (.3 + .5 * pul) * (1.1 - H2[i] / .6 * .6) : 0;
      ms.forEach((m) => m.emissive.setRGB(g * 1.7, g * .05, g * .05));
    });
  sf.halos.forEach((m, i) =>
    (m.material.opacity = po * (H2[i] < .6 && known ? .16 + .2 * pul : 0))
  );
  sf.tags.forEach((d, i) => {
    if (H2[i] < .6 && known && rt.tz == 1) {
      _v.copy(sf.an[i]);
      pr.obj.localToWorld(_v);
      _v.project(cam);
      d.style.display = 'block';
      d.style.left = ((_v.x + 1) / 2 * w) + 'px';
      d.style.top = ((1 - _v.y) / 2 * h2 - 30) + 'px';
      d.style.background = '#d4162f';
      d.textContent = SFM[k][i] + ', ' + Math.round(H2[i] * 100) + '%';
    } else d.style.display = 'none';
  });
  const q = ctx.SF.s;
  q.style.display = rt.tz == 1 ? 'block' : 'none';
  q.textContent = !known ? 'Awaiting ' + PARTS[k].name.toLowerCase() + ' data' : bad ? 'Fault detected in ' + PARTS[k].name.toLowerCase() : PARTS[k].name + ' normal';
  q.style.color = !known ? '#c8902e' : bad ? '#ff4d5e' : '#3ddc84';
  q.style.borderColor = q.style.color;
}

export function hideSubFaultTags() {
  if (ctx.SF) Object.values(ctx.SF).forEach((x) => (x.style.display = 'none'));
}

// Hides the fuel-system tags and the sub-fault tags.
export function hideFaultTags() {
  if (ctx.FT) Object.values(ctx.FT).forEach((x) => (x.style.display = 'none'));
  hideSubFaultTags();
}
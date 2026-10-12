import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';

// Models are plain files in /public/models (they used to be base64 strings inside the HTML).
export const assetUrl = (name) => `${import.meta.env.BASE_URL}models/${name}`;

export async function fetchBuffer(name) {
  const r = await fetch(assetUrl(name));
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.arrayBuffer();
}

export async function fetchJson(name) {
  const r = await fetch(assetUrl(name));
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

let gltf;
let draco;
// Load a .glb from /public/models and resolve with its scene.
// Phase 4.7: DRACO-ready — assets recompressed with Draco decode via the
// vendored three/examples decoder; plain GLBs skip the extension and parse
// exactly as before, so compressed and uncompressed assets coexist.
export async function loadGlb(name) {
  const buf = await fetchBuffer(name);
  if (!gltf) {
    gltf = new GLTFLoader();
    try {
      draco = draco || new DRACOLoader();
      draco.setDecoderPath(`${import.meta.env.BASE_URL}draco/`);
      gltf.setDRACOLoader(draco);
    } catch {
      // Decoder assets absent (offline dev) — plain GLBs still parse.
    }
  }
  return new Promise((ok, no) => gltf.parse(buf, '', (g) => ok(g.scene), no));
}

// Gunzip an ArrayBuffer. If a server already decoded it (Content-Encoding: gzip) it is returned as is.
export async function gunzip(buf) {
  const u8 = new Uint8Array(buf);
  if (u8[0] !== 0x1f || u8[1] !== 0x8b) return buf;
  return new Response(new Blob([u8]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
}

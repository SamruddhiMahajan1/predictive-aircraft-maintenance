// Pre-compress dist assets for nginx gzip_static (docs/16 Phase 4.7).
// Writes .gz siblings for js/css/json/svg (not .glb/.bin.gz — already binary).
import { readdirSync, statSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const dist = new URL("../dist/", import.meta.url).pathname;
const exts = new Set([".js", ".css", ".json", ".svg", ".html"]);
let n = 0;
function walk(dir) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) {
      walk(p);
      continue;
    }
    if (![...exts].some((x) => p.endsWith(x))) continue;
    if (p.endsWith(".gz")) continue;
    const raw = readFileSync(p);
    if (raw.length < 1024) continue;
    writeFileSync(p + ".gz", gzipSync(raw, { level: 9 }));
    n++;
  }
}
try {
  walk(dist);
  console.log(`compress-dist: wrote ${n} .gz siblings`);
} catch (e) {
  console.log(`compress-dist: skipped (${e.message})`);
}

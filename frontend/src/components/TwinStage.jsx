import { useEffect, useRef, useState } from 'react';
import { useStore } from '../state/useStore.js';
import { closePart, setView, setStatus } from '../state/store.js';
import { fleet } from '../data/fleet.js';
import { PARTS } from '../data/parts.js';

const VIEWS = [['auto', 'Auto'], ['top', 'Top'], ['side', 'Side'], ['under', 'Underside']];

// The 3D viewport. React owns the overlay UI (title, view buttons); the three.js
// scene is a plain module mounted into #stage.
//
// three.js (~512 KB) is dynamically imported inside the effect — not statically —
// so it never blocks first paint. The shell (navbar, fleet bar, KPIs) renders
// from the initial ~85 KB gzip bundle while the 3D chunk + GLB models stream in
// behind the "Loading 3D…" status line.
export default function TwinStage() {
  const app = useStore();
  const stageRef = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let twin = null;
    let cancelled = false;
    (async () => {
      try {
        const { createTwin } = await import('../three/index.js');
        if (cancelled || !stageRef.current) return;
        twin = createTwin(stageRef.current);
        setReady(true);
      } catch (e) {
        if (!cancelled) setStatus('Could not load 3D: ' + (e?.message || e));
      }
    })();
    return () => {
      cancelled = true;
      try {
        twin?.dispose();
      } catch {
        /* dispose is best-effort on unmount */
      }
    };
  }, []);

  const e = fleet[app.sel];
  return (
    <section className="hero" id="twin">
      <div id="stage" ref={stageRef}>
        <i className="glow"></i>
        <div id="intro">
          <b>Fleet digital twin</b>
          <span>{ready ? 'Drag to turn the aircraft. Select a label to look inside.' : 'Loading 3D…'}</span>
        </div>
        <button id="back" onClick={closePart} style={{ display: app.tgt ? 'block' : 'none' }}>Back to aircraft</button>
        <div id="views">
          {VIEWS.map(([v, label]) => (
            <button key={v} data-v={v} className={app.view === v ? 'on' : ''} onClick={() => setView(v)}>{label}</button>
          ))}
        </div>
        <div id="ttl">
          <b id="t1">{app.tgt ? PARTS[app.cur].name + ' - ' + e.id : e.id}</b>
          <span id="t2">{app.status}</span>
        </div>
      </div>
    </section>
  );
}

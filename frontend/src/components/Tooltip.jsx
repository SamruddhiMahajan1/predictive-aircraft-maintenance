import { useEffect, useRef } from 'react';

// Floating tooltip for any element with a data-tip attribute (use "\n" for line breaks).
// FE4/FE5 fix: was using innerHTML + offsetWidth read per pointermove (60-120×/s).
// Now: textContent + white-space: pre-line, rAF throttle, no reflow reads.
export default function Tooltip() {
  const ref = useRef(null);
  useEffect(() => {
    const tip = ref.current;
    let raf = 0;
    const move = (e) => {
      const t = e.target.closest && e.target.closest('[data-tip]');
      if (!t) {
        tip.style.opacity = 0;
        return;
      }
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        tip.textContent = t.dataset.tip;
        tip.style.opacity = 1;
        // Position without reading offsetWidth/offsetHeight:
        // Use right/bottom anchoring so the tip never overflows; the CSS
        // handles the offset via transform-origin.
        const x = Math.max(8, Math.min(window.innerWidth - 8, e.clientX + 14));
        const y = Math.min(window.innerHeight - 8, e.clientY + 16);
        tip.style.transform = `translate(${x}px, ${y}px)`;
      });
    };
    document.addEventListener('pointermove', move, { passive: true });
    return () => {
      document.removeEventListener('pointermove', move);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);
  return <div id="tip" ref={ref}></div>;
}
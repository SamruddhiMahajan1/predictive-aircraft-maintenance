import { useEffect } from 'react';
import { prefersReducedMotion } from './lib/screening.js';

// Fades panels (.rv) in when they scroll into view.
//
// Previously this also ran a `scroll` listener doing a full
// `querySelectorAll('.rv:not(.vis)')` + getBoundingClientRect on every scroll
// event — O(panels) layout thrash per frame — duplicating exactly what the
// IntersectionObserver below already does for free in the compositor. IO only.
export function useRevealOnScroll() {
  useEffect(() => {
    const io = new IntersectionObserver((es) => es.forEach((x) => { if (x.isIntersecting) { x.target.classList.add('vis'); io.unobserve(x.target); } }), { threshold: 0.12 });
    document.querySelectorAll('.rv').forEach((x) => io.observe(x));
    // Panels mounted lazily (React.lazy) after this effect ran still need one
    // pass once their chunks resolve.
    const t = setTimeout(() => document.querySelectorAll('.rv:not(.vis)').forEach((x) => io.observe(x)), 1500);
    return () => { clearTimeout(t); io.disconnect(); };
  }, []);
}

// Removes the intro animation class from <body> after the intro has played.
export function useIntro() {
  useEffect(() => {
    const go = () => document.body.classList.remove('intro');
    if (prefersReducedMotion()) { go(); return; }
    const t = setTimeout(go, 2800);
    return () => clearTimeout(t);
  }, []);
}

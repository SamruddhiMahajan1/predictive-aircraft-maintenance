import { Suspense, lazy, useEffect } from 'react';
import { startSimulation } from './state/simulation.js';
import { useIntro, useRevealOnScroll } from './hooks.js';
import Navbar from './components/Navbar.jsx';
import FleetBar from './components/FleetBar.jsx';
import Kpis from './components/Kpis.jsx';
import Tooltip from './components/Tooltip.jsx';
import Footer from './components/Footer.jsx';

// Above-the-fold shell renders immediately. Everything below — the 512 KB
// three.js stage plus five data panels — used to be statically imported, so the
// browser parsed ~780 KB of JS and fired 5+ API reads + 4 model fetches before
// first paint. Each lazy chunk below loads in parallel after the shell paints,
// so LCP is the navbar + fleet bar instead of the slowest GLB.
const TwinStage = lazy(() => import('./components/TwinStage.jsx'));
const Inspector = lazy(() => import('./components/Inspector.jsx'));
const FleetHealth = lazy(() => import('./components/FleetHealth.jsx'));
const HealthHeatmap = lazy(() => import('./components/HealthHeatmap.jsx'));
const TrendChart = lazy(() => import('./components/TrendChart.jsx'));
const NeedsAttention = lazy(() => import('./components/NeedsAttention.jsx'));
const Alerts = lazy(() => import('./components/Alerts.jsx'));
const MaintenancePlan = lazy(() => import('./components/MaintenancePlan.jsx'));

function PanelFallback({ title }) {
  return (
    <section className="pn s12 rv vis" aria-busy="true">
      <div className="hd"><h2>{title}</h2><span>Loading…</span></div>
    </section>
  );
}

function Console() {
  useEffect(() => startSimulation(), []); // one simulated cycle every 1.2 s
  useIntro();
  useRevealOnScroll();

  return (
    <>
      <main className="wrap">
        <Navbar />
        <Suspense fallback={<PanelFallback title="3D twin" />}>
          <TwinStage />
        </Suspense>
        <FleetBar />
        <Kpis />
        <Suspense fallback={<PanelFallback title="Aircraft inspector" />}>
          <Inspector />
        </Suspense>
        <Suspense fallback={<PanelFallback title="Fleet health" />}>
          <FleetHealth />
        </Suspense>
        <Suspense fallback={<PanelFallback title="Health heatmap" />}>
          <HealthHeatmap />
        </Suspense>
        <Suspense fallback={<PanelFallback title="Trend" />}>
          <TrendChart />
        </Suspense>
        <Suspense fallback={<PanelFallback title="Needs attention" />}>
          <NeedsAttention />
        </Suspense>
        <Suspense fallback={<PanelFallback title="Alerts" />}>
          <Alerts />
        </Suspense>
        <Suspense fallback={<PanelFallback title="Maintenance plan" />}>
          <MaintenancePlan />
        </Suspense>
      </main>
      <Tooltip />
      <Footer />
    </>
  );
}

export default function App() {
  return <Console />;
}

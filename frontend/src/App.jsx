import { useEffect } from 'react';
import { startSimulation } from './state/simulation.js';
import { useIntro, useRevealOnScroll } from './hooks.js';
import Navbar from './components/Navbar.jsx';
import TwinStage from './components/TwinStage.jsx';
import FleetBar from './components/FleetBar.jsx';
import Kpis from './components/Kpis.jsx';
import Inspector from './components/Inspector.jsx';
import FleetHealth from './components/FleetHealth.jsx';
import HealthHeatmap from './components/HealthHeatmap.jsx';
import TrendChart from './components/TrendChart.jsx';
import NeedsAttention from './components/NeedsAttention.jsx';
import Alerts from './components/Alerts.jsx';
import MaintenancePlan from './components/MaintenancePlan.jsx';
import Tooltip from './components/Tooltip.jsx';
import Footer from './components/Footer.jsx';

function Console() {
  useEffect(() => startSimulation(), []); // one simulated cycle every 1.2 s
  useIntro();
  useRevealOnScroll();

  return (
    <>
      <main className="wrap">
        <Navbar />
        <TwinStage />
        <FleetBar />
        <Kpis />
        <Inspector />
        <FleetHealth />
        <HealthHeatmap />
        <TrendChart />
        <NeedsAttention />
        <Alerts />
        <MaintenancePlan />
      </main>
      <Tooltip />
      <Footer />
    </>
  );
}

export default function App() {
  return <Console />;
}

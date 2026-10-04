import { useStore } from '../state/useStore.js';
import { toggleTheme } from '../state/store.js';

export default function Navbar() {
  const app = useStore();
  return (
    <header className="nav">
      <div className="logo"></div>
      <b>Fleet digital twin</b>
      <span id="live">{'Live, cycle ' + app.cycle + (app.fc ? ', forecast +' + app.fc : '')}</span>
      <span className={'backend-badge ' + (app.backendConnected ? 'online' : 'connecting')} title="FastAPI + PostgreSQL + NASA C-MAPSS Telemetry Stream">
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: app.backendConnected ? '#10b981' : '#f59e0b', display: 'inline-block' }}></span>
        {app.backendConnected ? 'Backend Live' : 'Connecting...'}
      </span>
      {app.user && <span className="role-badge" title="Authenticated User">{app.user.role}</span>}
      <nav className="links">
        <a href="#twin">Aircraft</a>
        <a href="#health">Health</a>
        <a href="#attention">Attention</a>
        <a href="#plan">Plan</a>
      </nav>
      <button id="theme" className="wo" onClick={toggleTheme}>{app.theme === 'dark' ? 'Light' : 'Dark'}</button>
    </header>
  );
}

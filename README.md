# Fleet Digital Twin

A 3D digital twin of an eight-aircraft fighter fleet featuring real-time telemetry streaming, predictive health modeling, an interactive 3D inspector, and an end-to-end predictive maintenance operations center.

Built with **React 18 + Vite 5 + three.js r128** on the frontend, and **FastAPI + PostgreSQL 16/18 + NASA C-MAPSS Telemetry Replay** on the backend.

---

## Key Features

- **Interactive 3D Aircraft & Subsystem Twins**: Rotate, zoom, switch views (Auto, Top, Side, Underside), or click surface hotspots to smoothly zoom into five inspectable subsystems:
  - **Engine** (Fan, HPC, HPT, LPT modules with dynamic shader damage-zone glow)
  - **Radar & Avionics** (Antenna array, Gimbal drive, Transmitter)
  - **Landing Gear** (Tyres, Struts, Retract actuator)
  - **Hydraulics** (Pump, Servo actuator, Hydraulic lines)
  - **Fuel System** (Tank, Boost pump, Fuel valves)
- **Live Backend Telemetry & WebSocket Streaming**:
  - Live cycle ticks and sensor telemetry streamed every 1.2s over WebSocket (`ws://localhost:8000/ws/fleet`).
  - Staggered flight cycle advancement across all 8 aircraft (`Fighter-01` through `Fighter-08`).
  - Dynamic Remaining Useful Life (RUL) estimation powered by engine degradation modeling.
- **Relational Maintenance Database**:
  - Backed by **PostgreSQL** with 20 tables tracking aircraft history, sensor readings, flight operations, snag logs, technical records, maintenance agencies, and spare inventory.
  - Interactive **Work Order creation** and **Alert Acknowledgment** persisted directly to the database.
- **Mission Readiness & Fleet Analytics**:
  - Fleet readiness KPIs (Ready %, Fleet Average Health, Needs Attention list).
  - Aircraft × Subsystem Health Heatmap.
  - Multi-cycle Engine Health Trend Chart.
  - Maintenance plan with CSV export and agency turnaround estimates.
  - Lookahead Forecast slider (+10 / +20 / +30 cycles).
  - Role-based access control with demo accounts (`commander`, `officer`, `viewer`).

---

## Architecture Overview

```
Frontend (React 18 + Vite 5 + three.js)
├── 3D Canvas (ThreeStage) ── imperative r128 WebGL scene
├── State Store (store.js) ── pub/sub reactive store
├── API Client (api.js)   ── JWT auth + REST endpoints
└── WebSocket Listener    ── receives real-time cycle ticks and health updates
          ▲                                 ▲
          │ REST (http://localhost:8000)   │ WebSocket (ws://localhost:8000/ws/fleet)
          ▼                                 ▼
Backend (FastAPI + PostgreSQL)
├── api/v1/          ── Auth, Fleet, Telemetry, Maintenance, Alerts
├── realtime/replay  ── 1.2s C-MAPSS cycle replay engine
├── domain/rules     ── Deterministic maintenance rules & health bounds
├── ml/              ── RUL inference & deterministic fallback curves
└── db/              ── PostgreSQL tables, Alembic migrations & audit logging
```

---

## Quick Start

### 1. Backend Setup

Prerequisites: Python 3.11+ and PostgreSQL (or Docker).

```bash
cd backend/backend

# Create virtual environment and install dependencies
uv venv .venv --python 3.11
.venv\Scripts\activate       # On Windows (. .venv/bin/activate on Linux/Mac)
uv pip install -e .

# Configure environment (.env)
# Set your PostgreSQL connection string in .env:
# FDT_DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/fdt
# FDT_JWT_SECRET=your-random-secret-key

# Run database migrations and seed data
alembic upgrade head
python -m app.seed.run

# Start FastAPI server
uvicorn app.main:app --port 8000 --workers 1
```

- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- WebSocket endpoint: `ws://localhost:8000/ws/fleet`

### 2. Frontend Setup

Prerequisites: Node 18+.

```bash
# In the project root directory
npm install
npm run dev        # http://localhost:5173
```

- Open [http://localhost:5173](http://localhost:5173) in your browser.
- The top navigation bar will show `🟢 Backend Live` once connected to the backend WebSocket stream.

---

## Directory Layout

```
fleet-digital-twin/
├── index.html
├── package.json
├── vite.config.js
├── public/models/               3D GLB assets & engine mesh data
│   ├── rafale.glb               Fighter jet model
│   ├── landing-gear.glb         Landing gear model
│   ├── radar.glb                Radar antenna model
│   ├── engine.bin.gz            Engine mesh geometry (gzip compressed)
│   └── engine.meta.json         Engine geometry header
├── src/
│   ├── main.jsx                 Frontend entry point
│   ├── App.jsx                  Dashboard layout & component mount
│   ├── styles/global.css        Theme variables, layout, panels & badges
│   ├── lib/
│   │   ├── api.js               FastAPI client & WebSocket connection manager
│   │   ├── health.js            Health model: wear -> health, RUL, readiness
│   │   ├── fleetStats.js        Fleet analytics calculations
│   │   ├── plan.js              Maintenance plan generation & CSV export
│   │   └── colors.js            Health color scales & theme tokens
│   ├── state/
│   │   ├── store.js             Central reactive app store (state + actions)
│   │   ├── useStore.js          React hook for store subscriptions
│   │   └── simulation.js        Real-time telemetry sync & fallback ticker
│   ├── three/                   three.js WebGL scene & interaction
│   │   ├── index.js             Scene lifecycle manager
│   │   ├── scene.js             Lights, cameras, rendering pipeline
│   │   ├── loop.js              60 FPS render loop & transitions
│   │   ├── arrows.js            Interactive hotspot labels & surface pinning
│   │   └── models/              3D model loaders & custom shader damage zones
│   └── components/              React UI dashboard panels
│       ├── Navbar.jsx           Header with Live cycle & Backend status badge
│       ├── TwinStage.jsx        3D aircraft viewer stage
│       ├── FleetBar.jsx         Aircraft selector & search/sort toolbar
│       ├── Kpis.jsx             Fleet readiness KPI cards
│       ├── Inspector.jsx        Aircraft & subsystem detailed diagnostic cards
│       ├── FleetHealth.jsx      Overall fleet health overview
│       ├── HealthHeatmap.jsx    Aircraft x subsystem health matrix
│       ├── TrendChart.jsx       60-cycle engine trend history chart
│       ├── NeedsAttention.jsx   Aircraft requiring priority action
│       ├── Alerts.jsx           Live alerts list with backend ACK support
│       └── MaintenancePlan.jsx  Maintenance schedule table with CSV download
└── backend/                     FastAPI backend package
    ├── backend/
    │   ├── app/                 Application source (api, db, ml, domain, realtime)
    │   ├── data/                Raw fleet CSVs and NASA C-MAPSS datasets
    │   ├── alembic/             Database schema migrations
    │   └── pyproject.toml       Python dependencies
    └── docs/                    Architecture and ML design documentation
```

---

## Demo Accounts

The backend includes seeded demo users:

| Role | Username | Password | Permissions |
|---|---|---|---|
| Commander | `commander` | `commander123` | Full access & agency oversight |
| Maintenance Officer | `officer` | `officer123` | Work order mutations & alert actions |
| Viewer | `viewer` | `viewer123` | Read-only access |

---

## Credits

- Engine: "Turbine | Turbofan Engine | Jet Engine" by [blenderbirb](https://sketchfab.com/3d-models/turbine-turbofan-engine-jet-engine-74c6aceed86b4a41aaad3b93afc3e262), [CC-BY-4.0](http://creativecommons.org/licenses/by/4.0/).
- Aircraft Models: 3D fighter assets for visualization purposes.
- Telemetry: NASA Prognostics Center of Excellence C-MAPSS Turbofan Engine Degradation Simulation dataset.

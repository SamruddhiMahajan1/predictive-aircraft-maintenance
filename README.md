<div align="center">

# Fleet Digital Twin

**Predictive maintenance for an eight-aircraft fighter fleet.**

A 3D digital twin of a fleet with real-time telemetry streaming, XGBoost-powered
remaining-useful-life prediction, deterministic maintenance rules, and an end-to-end
operations console for alerts, work orders, spares and agency scheduling.

[![CI](https://github.com/OWNER/predictive-aircraft-maintenance/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/predictive-aircraft-maintenance/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/react-18-61dafb.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## Table of contents

- [What this is](#what-this-is)
- [Feature tour](#feature-tour)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [The domain model](#the-domain-model)
- [API reference](#api-reference)
- [The ML pipeline](#the-ml-pipeline)
- [Realtime and demo mode](#realtime-and-demo-mode)
- [Data sources](#data-sources)
- [Configuration](#configuration)
- [Local development without Docker](#local-development-without-docker)
- [Testing and quality](#testing-and-quality)
- [Production deployment](#production-deployment)
- [Operations](#operations)
- [Security model](#security-model)
- [Performance budgets](#performance-budgets)
- [Working with the 3D assets](#working-with-the-3d-assets)
- [Troubleshooting](#troubleshooting)
- [Demo accounts](#demo-accounts)
- [Design documentation](#design-documentation)
- [Credits and licence](#credits-and-licence)

---

## What this is

The Fleet Digital Twin is a complete predictive-maintenance platform for a small fighter
fleet. It answers one operational question continuously: **which aircraft cannot fly
next week, and why?**

Every 1.2 seconds the backend advances each of the eight aircraft by one real flight
cycle of the NASA C-MAPSS turbofan degradation dataset, runs an XGBoost model over the
last 30 cycles of 20+ engine sensors, derives a Remaining Useful Life (RUL), applies eight
deterministic business rules to turn that into risk bands and recommended actions, and
pushes the result to every connected browser over a WebSocket. The frontend renders it
as a 3D aircraft you can rotate, click and drill into.

Three things make it more than a dashboard:

1. **The rules are the contract.** Health bands, mission-readiness, do-by cycles,
   back-in-service dates and spare allocation are pure functions in
   `backend/app/domain/rules.py`, unit-tested against worked examples. The UI and the
   database agree because both derive from one implementation.
2. **The model is never silently absent.** If the trained artifacts are missing the API
   answers from a deterministic `rul = 125 − cycle` curve — and `/healthz` reports
   `status: degraded` with the exact reason. A maintenance system that quietly
   substitutes a heuristic for a model is more dangerous than one that is down.
3. **Everything is offline.** No outbound network calls at runtime. The dataset is
   vendored, the model is served locally, and the stack is three containers.

---

## Feature tour

**3D digital twin** — an interactive WebGL aircraft with five inspectable subsystems,
each with its own damage-zone shading that responds to live health:

| Subsystem | Model | Live animation |
|---|---|---|
| Engine | quantised mesh (`engine.bin.gz`), shader damage zones | Fan/HPC/HPT/LPT degrade independently; compressor health drives a glow ramp |
| Radar & avionics | `radar.glb` | Gimbal drive, transmitter, antenna array |
| Landing gear | `landing-gear.glb` | Tyres, struts, retract actuator |
| Hydraulics | procedural (three.js primitives) | Pump, servo actuator, hydraulic lines |
| Fuel system | procedural (three.js primitives) | Tank level, boost pump, valves, flow |

**Operations console**

- Fleet readiness KPIs: mission-ready count, critical parts, average RUL, fleet cycle.
- Aircraft × subsystem health heatmap — click a cell to select and zoom the 3D twin.
- Multi-cycle engine health trend chart, live.
- Needs-attention list: worst part per aircraft, with spare and agency availability.
- Alert panel with acknowledgement that persists to PostgreSQL.
- Maintenance plan table with CSV export and a +10/+20/+30-cycle lookahead slider.
- Live sensor table showing the 14 most attribution-weighted C-MAPSS sensors, ranked by
  deviation, so an operator can see *which* sensor is driving a health drop.
- No authentication: every operator sees the same console (see [Security model](#security-model)).

---

## Architecture

A **modular monolith** behind an **nginx BFF**. One origin serves the SPA and the API, so
there is no CORS, no build-time API URL, and no WebSocket special-casing.

```
                         ┌─────────────────────────────────────────┐
   browser ──────────────▶│  web · nginx 1.27 (unprivileged, :8080) │
                         │                                         │
                         │  /            → static SPA + hashed cache│
                         │  /models/*    → 3D assets, immutable    │
                         │  /healthz     → proxy                    │
                         │  /api/*       ─┐                        │
                         │  /ws/fleet    ─┤  same origin, no CORS   │
                         └────────────────┼────────────────────────┘
                                          ▼
                         ┌─────────────────────────────────────────┐
                         │  api · FastAPI monolith (:8000)         │
                         │                                         │
                         │  api/v1 ──▶ services ──▶ repositories   │
                         │                   │                     │
                         │             domain/ (pure)              │
                         │             ml/     (XGBoost)           │
                         │                                         │
                         │  realtime/ ── replay engine (1.2 s tick) │
                         │  lifespan ── model load, C-MAPSS index  │
                         └──────────────────┬──────────────────────┘
                                            ▼
                         ┌─────────────────────────────────────────┐
                         │  db · PostgreSQL 16 (20 tables)         │
                         └─────────────────────────────────────────┘
```

### Why this shape

| Decision | Rationale |
|---|---|
| **One FastAPI process** | The replay engine is an in-process asyncio task. Multiple uvicorn workers would run multiple replay loops and double-advance every aircraft. A monolith keeps that invariant obvious; `--workers 1` is enforced in the Dockerfile. |
| **nginx as the BFF** | The browser only ever sees one origin. That removed a hardcoded `http://127.0.0.1:8000`, the CORS preflight on every call, and the need to bake an API URL into the bundle at build time. |
| **Stateless API, stateful DB** | All state is in PostgreSQL. The only in-process state is the event bus and the replay cursor, both rebuilt from the database on restart. |
| **Layered, with a genuinely pure core** | `domain/` imports nothing but the standard library, which is why the rules are testable without a database and why `mypy --strict` passes on it. |

### Backend layers

```
api/          HTTP and WebSocket transport. Parses, delegates, shapes the response.
 └ services/  Use cases, one per endpoint intent. Owns transactions via UnitOfWork.
     ├ repositories/  Data access only. No business logic.
     │   └ models/    SQLAlchemy 2.0 declarative tables.
     ├ domain/        Pure business logic (rules, health, scheduling, aggregation).
     ├ ml/            Model store, feature contract, inference, attribution.
     └ realtime/     Event bus, replay engine, WebSocket endpoint.
```

The dependency direction is strictly downward. `domain/` is pure; `repositories/` never
imports `services/`; `api/` never issues SQL. The one place this used to break —
`api/v1/telemetry.py` executing ~120 lines of raw `pg_insert` upserts that duplicated
`realtime/replay.py` almost line for line — is now
`repositories/telemetry_repo.py`, a single writer for the engine time-series tables,
called by both `services/telemetry_service.py` and the replay engine.

---

## Quick start

**Prerequisites:** Docker with Compose v2. Nothing else — no local Python, no Node, no
PostgreSQL.

```bash
git clone https://github.com/OWNER/predictive-aircraft-maintenance.git
cd predictive-aircraft-maintenance

make setup     # .env + C-MAPSS dataset + images + migrations + seed
make up        # start the stack
```

Open **<http://localhost:8080>**.

| URL | What |
|---|---|
| `http://localhost:8080` | The application |
| `http://localhost:8000/docs` | Interactive OpenAPI docs (loopback only) |
| `http://localhost:8000/healthz` | Liveness, dependency and ML status |
| `ws://localhost:8080/ws/fleet` | Live telemetry stream |

There is no sign-in screen — the console opens directly (see [Security model](#security-model)).

`make setup` is idempotent. If you already have the dataset, or prefer to fetch it
yourself, `make fetch-data` is the only required step and `make migrate && make seed` the
only required initialisation.

### What `make setup` does

1. Copies `.env.example` → `.env`.
2. Downloads NASA C-MAPSS **FD001** into `backend/data/cmapss/` (26 MB, gitignored — see
   [Data sources](#data-sources)). FD001 is the only subset the replay engine and the
   shipped artifact use; `make fetch-data-all` adds FD002–FD004 (~43 MB total).
3. Builds both images.
4. Starts PostgreSQL and waits for it to be healthy.
5. Runs `alembic upgrade head` and `python -m app.seed.run`.

### Everyday commands

```bash
make help          # every target, with descriptions
make up            # start / rebuild and run in the background
make down          # stop, keeping the database
make logs          # tail all services
make logs SERVICE=api
make ps            # container status

make migrate       # apply migrations
make seed          # reload fleet data (idempotent)
make fresh         # drop the volume, migrate and seed from scratch

make lint          # ruff
make typecheck     # mypy --strict over core, domain and ml
make test          # full pytest suite (starts a throwaway database)
make db-dump       # backend/backup.sql.gz
```

---

## Project layout

```
predictive-aircraft-maintenance/
├── docker-compose.yml            # dev stack: db + api + web
├── docker-compose.prod.yml       # production overrides
├── Makefile                      # developer entry points
├── .env.example                  # every variable, documented
├── .github/workflows/ci.yml      # lint + types + tests + image builds
│
├── docker/
│   ├── backend/
│   │   ├── Dockerfile            # multi-stage, non-root, healthchecked
│   │   └── .dockerignore
│   └── frontend/
│       ├── Dockerfile            # node build → nginx unprivileged
│       ├── nginx.conf.template           # SPA + /api + /ws proxy, caching, hardening
│       └── .dockerignore
│
├── backend/                      # FastAPI monolith
│   ├── pyproject.toml            # deps, ruff, mypy, pytest config
│   ├── alembic.ini
│   ├── alembic/versions/         # one migration: 20 tables, enums, 33 indexes
│   ├── app/
│   │   ├── main.py               # factory, lifespan, middleware, error handler
│   │   ├── api/                  # v1 routers + dependencies (db session, settings)
│   │   ├── services/             # use cases
│   │   ├── repositories/         # data access
│   │   ├── domain/               # pure logic — rules, health, scheduling
│   │   ├── ml/                   # model store, features, inference, attribution
│   │   ├── realtime/             # event bus, replay engine, WebSocket
│   │   ├── models/               # SQLAlchemy tables
│   │   ├── schemas/              # Pydantic v2 request/response models
│   │   ├── seed/                 # idempotent loader + C-MAPSS index
│   │   ├── db/                   # session, unit of work, audit log
│   │   └── core/                 # settings, security, errors, logging
│   ├── scripts/                  # stage_ml_artifacts.py, verify_live.sh
│   ├── tests/                    # unit · integration · ml · performance
│   └── data/
│       ├── raw/                  # 7 fleet CSVs, committed (584 KB)
│       ├── cmapss/               # NASA telemetry, gitignored, `make fetch-data`
│       └── ml/                   # trained artifacts, gitignored
│
├── frontend/                     # React + Vite SPA
│   ├── index.html
│   ├── vite.config.js            # dev proxy to the API, same-origin
│   ├── public/models/            # 3D assets (~9 MB, served immutable)
│   └── src/
│       ├── components/           # dashboard panels + inspector sub-views
│       ├── state/                # store, React binding, simulation driver
│       ├── lib/                  # api client, health model, colours, CSV
│       ├── data/                 # fleet config, part catalogue, sensor map
│       └── three/                # WebGL scene, loop, interaction, models
│
├── ml/notebooks/                 # Model_training_249.ipynb — produces the artifacts
├── docs/                         # 15 design documents (see below)
└── scripts/                      # fetch-cmapss.sh, dev-up.sh, seed.sh
```

---

## The domain model

Eight aircraft (`Fighter-01` … `Fighter-08`), each with five parts
(`engine`, `radar`, `gear`, `hyd`, `fuel`) and four engine components
(`fan`, `hpc`, `hpt`, `lpt`).

### Health

- **Engine** comes from the model: `health = rul / 125`, smoothed with an EMA
  (α = 0.3) per aircraft.
- **The other four** come from `maintenance_burden_v1`: a recency-weighted sum over the
  aircraft's technical records and snag logs, normalised against the fleet 95th
  percentile, inverted and floored. A fault that is old and small barely matters; a
  recent, large one matters a lot.
- The two are reconciled at seed time and any divergence above a threshold is logged as
  a warning (`seed_reconciliation.log`).

### Business rules

Implemented in `backend/app/domain/rules.py`, specified in
[`docs/07-business-rules.md`](docs/07-business-rules.md).

| # | Rule | Behaviour |
|---|---|---|
| 19 | Risk band | `> 0.70` healthy · `> 0.40` watch · otherwise critical |
| 20 | Worst part | Lowest health; ties broken by canonical part order |
| 21 | Mission ready | Engine RUL > 30 **and** every part above watch |
| 22 | Do-by cycle | `rul − 10` for watch and critical; `None` for healthy |
| 23 | Weakest component | Lowest component health; drives the engine spare choice |
| 24 | Back in service | `free_slot + turnaround + (0 if in stock else lead_time)` |
| 25 | Spare selection | The weakest component's spare; ordered by criticality then stock |
| 26 | RUL cap | Rounded and clamped to `[0, 125]` |

### The database

20 tables in four groups:

| Group | Tables |
|---|---|
| Identity | `users`, `user_roles`, `audit_log` |
| Fleet | `aircraft`, `parts`, `aircraft_parts`, `risk_levels` |
| Telemetry | `engine_telemetry`, `component_health`, `health_snapshots`, `ml_predictions` |
| Maintenance | `work_orders`, `spares`, `stock_movements`, `agencies`, `agency_bookings`, `alerts` |
| Reference | `aircraft_ref`, `component_ref`, `flight_ops_monthly`, `technical_records`, `snags` |

Every mutation is written through `UnitOfWork`, which wraps the transaction and records
an `audit_log` row carrying the actor, the action, the entity and a JSON diff.
`GET /api/v1/audit` reads it back.

---

## API reference

All routes are under `/api/v1`. **No route requires authentication** — see
[Security model](#security-model). Every endpoint is open, including the 13 mutating ones,
and the deployment boundary is the network.

### Fleet

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/aircraft` | open | List with health, RUL, risk and readiness |
| `GET` | `/aircraft/{code_or_id}` | open | Single aircraft detail |
| `GET` | `/aircraft/{code_or_id}/engine` | open | Engine history, components, top sensors |
| `GET` | `/aircraft/{code_or_id}/parts/{part}` | open | One part's health and provenance |
| `GET` | `/fleet/summary` | open | Fleet rollup + aligned health series |
| `GET` | `/fleet/heatmap` | open | Aircraft × part health matrix |
| `GET` | `/fleet/actions` | open | Ranked recommended actions |
| `GET` | `/maintenance/schedule` | open | One row per aircraft: action, do-by, spares, agency |

### Maintenance

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/work-orders` | open | List, filterable by status, aircraft, part |
| `POST` | `/work-orders` | open | Create. Requires `aircraft`, `part`, `due_date` |
| `PATCH` | `/work-orders/{id}` | open | Update status, priority, due date, notes |
| `GET` | `/spares` | open | Stock, criticality, lead times |
| `PATCH` | `/spares/{part_ref_id}` | open | Adjust stock or lead time |
| `POST` | `/spares/{part_ref_id}/reserve` | open | Reserve against a work order |
| `GET` | `/agencies` | open | Agencies with free slots and turnaround |
| `POST` | `/agencies/{id}/bookings` | open | Book a maintenance slot |

### Alerts

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/alerts` | open | Filter by `acknowledged`, `level`, `aircraft` |
| `POST` | `/alerts/{id}/ack` | open | Acknowledge with an optional note |
| `GET` | `/audit` | open | Audit trail |

### Telemetry and ML

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/telemetry` | open | Ingest a batch; infers, persists, publishes |
| `POST` | `/internal/ml/predict` | open | Score an arbitrary window against the model |

### Operations

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/healthz` | — | Liveness, database and ML status |
| `GET` | `/readyz` | — | Readiness probe |
| `GET` | `/demo/status` | open | Replay engine state, subscribers, dropped events |
| `POST` | `/demo/pause` · `/demo/resume` · `/demo/tick` | open | Drive the replay manually |
| `POST` | `/seed/run` | open | Re-run the idempotent seed |

Full request and response schemas: <http://localhost:8000/docs>.

---

## The ML pipeline

### Training

[`ml/notebooks/Model_training_249.ipynb`](ml/notebooks/Model_training_249.ipynb) trains
the RUL model on a Colab VM and writes the artifacts to cloud storage. They are **not
committed** — a booster is ~900 KB and fully regenerable.

```bash
# 1. train in the notebook, then make the artifacts reachable at some URL
# 2. fetch them where the loader looks
make fetch-model
```

That downloads `<base>/<variant>/<file>` into `backend/data/ml/all/`, which is
bind-mounted into the container. `FDT_ML_ARTIFACTS_URL` in `.env` is the base URL; it
has no default, because unlike C-MAPSS the boosters are not on a public mirror.

To copy them across by hand instead — from a download, a Drive mount, anywhere:

```bash
docker compose --profile bootstrap run --rm --entrypoint sh model-fetch \
  -c 'python -m scripts.stage_ml_artifacts --source <dir> --variant all'
```

Both paths validate the set before staging: a booster whose feature count disagrees with
its contract is refused, because XGBoost consumes a positional matrix and the mismatch
would surface as plausible-looking wrong predictions rather than an error.

### Serving

Three variants, selected by `FDT_ML_VARIANT`. The loader resolves the **whole** artifact
set from that one value:

| Variant | Model | Features | Preprocessing |
|---|---|---|---|
| `all` *(default)* | Pooled FD001–FD004 | 32 | Per-regime z-score against four baselines |
| `full` | FD001 only | 29 | Per-regime z-score |
| `holdout` | FD001 80/20 split | 29 | `StandardScaler` |

The contract is 30 cycles of 20 sensors expanded to 32 columns, with `cycle` deliberately
excluded as a leakage vector. Two sensors (`s6`, `s16`) are constant in C-MAPSS and carry
no signal; they are retained only because the pooled contract's baselines reference them.

> **Do not set `FDT_ML_MODEL_PATH`.** An explicit path overrides the model while the
> contract still resolves from the variant, so the two describe different directories and
> the loader silently falls back — with a perfectly valid model sitting on disk unused.
> This exact failure happened once and cost a day.

### When no artifact is staged

The API still boots and answers every request from `rul = 125 − cycle`. `/healthz`
reports `"status": "degraded"` with the loader's error, so the degradation is visible to
monitoring and to the UI rather than hidden.

### Inference

`app/ml/` builds the feature matrix, validates it against the contract, classifies the
operating regime, runs XGBoost, then derives per-component health from the sensors
attributed to each component. The response always reports which model answered:

```json
{ "model": { "version": "xgboost_all_full", "fallback": false,
             "degraded": false, "loaded": true, "mae": 11.41 } }
```

Full details: [`docs/08-ml-service.md`](docs/08-ml-service.md) and
[`docs/15-serving-the-pooled-model.md`](docs/15-serving-the-pooled-model.md).

---

## Realtime and demo mode

With `FDT_DEMO_MODE=true` an in-process engine advances every aircraft by one C-MAPSS
cycle every `FDT_DEMO_TICK_SECONDS` (default 1.2 s), staggered so the fleet does not tick
in lockstep. Each tick:

1. Reads a 30-cycle window from the C-MAPSS index for that aircraft's bound engine.
2. Runs inference off the event loop (`asyncio.to_thread`).
3. Smooths engine health with the per-aircraft EMA.
4. Applies rules 19–26 and writes `engine_telemetry`, `component_health`,
   `ml_predictions`, `health_snapshots` and the denormalised `aircraft_parts` row — all
   in **one transaction per aircraft-tick**, so a tick is either fully visible or absent.
5. Publishes `cycle.tick`, `health.updated` and, on a risk-band change, `alert.raised`.

Subscribers on a bounded queue; a slow consumer drops events rather than stalling the
fleet, and `dropped_events` is reported by `/demo/status`.

Set `FDT_DEMO_MODE=false` in production — the API refuses to boot otherwise.

Protocol: [`docs/09-realtime-and-demo-mode.md`](docs/09-realtime-and-demo-mode.md).

---

## Data sources

| Source | Contents | In git? |
|---|---|---|
| Fleet CSVs | 8 tables, ~5,900 rows: aircraft, components, flight operations, agencies, spares, maintenance records, snag logs | **Yes** — `backend/data/raw/`, 584 KB |
| NASA C-MAPSS | 20,631 cycle rows (FD001), 21 sensors, 3 operating settings, ground-truth RUL | **No** — `make fetch-data` fetches FD001 (26 MB); `make fetch-data-all` adds FD002–FD004 (43 MB total) |
| Trained artifacts | XGBoost boosters, feature contracts, regime baselines | **No** — 1.2 MB, `make fetch-model` (`FDT_ML_ARTIFACTS_URL`) |

C-MAPSS is third-party with an unchanged upstream source, so re-fetching beats carrying
43 MB in every clone. The API **fails its Docker build** if `data/raw` is missing, and
`make setup` fetches C-MAPSS before the first start, so a misconfigured checkout is
caught at build time rather than degrading silently into an empty replay.

**Download verification.** `scripts/fetch-cmapss.sh` checks every file against NASA's
published row count, and additionally against a pinned SHA-256 where one exists. The row
count is the stronger of the two, because a digest can only be pinned from a copy that was
itself trusted: both configured mirrors currently serve byte-identical FD002 and FD004
`test_*`/`RUL_*` files carrying 259 and 248 engine units where NASA publishes 100 — train
data concatenated with test data — and FD003's test file one spurious row per engine.
Pinning those digests would make the script permanently accept the corruption, so they are
deliberately left unpinned and the row count rejects them instead. FD001, the only subset
the replay engine and the shipped booster use, is verified by both digest and row count.

---

## Configuration

Every setting is an environment variable prefixed `FDT_`, declared in
`backend/app/core/config.py` and documented in [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `FDT_ENVIRONMENT` | `development` | `development` \| `staging` \| `production` |
| `FDT_DATABASE_URL` | local Postgres | SQLAlchemy URL |
| `FDT_LOG_LEVEL` | `INFO` | Root log level |
| `FDT_CORS_ORIGINS` | `localhost:5173,8080` | Comma-separated browser allowlist |
| `FDT_DEMO_MODE` | `true` | Replay engine. Must be `false` in production |
| `FDT_DEMO_TICK_SECONDS` | `1.2` | Cycle interval |
| `FDT_RUL_CAP` | `125` | Rule 26 cap |
| `FDT_ML_VARIANT` | `all` | Which artifact generation to serve |
| `FDT_ML_DATASET` | `FD001` | Subset the fleet replays |
| `FDT_ML_FALLBACK` | `true` | Allow the deterministic curve |
| `FDT_ML_WINDOW` | `30` | Feature window length |
| `FDT_DATA_DIR` | `data` | Root for `raw/`, `cmapss/`, `ml/` |

Three settings exist purely to support the model loader's resolution rules and should be
left unset unless you know why: `FDT_ML_MODEL_PATH`, `FDT_ML_CONTRACT_PATH`,
`FDT_ML_SCALER_PATH`.

---

## Local development without Docker

Only needed if you are editing one half in isolation. Requires Python 3.11+ and Node 18+.

```bash
# API
make venv                       # backend/.venv with dev extras
docker compose up -d db         # or point FDT_DATABASE_URL at your own Postgres
cd backend
cp .env.example .env            # adjust FDT_DATABASE_URL
../backend/.venv/bin/alembic upgrade head
../backend/.venv/bin/python -m app.seed.run
../backend/.venv/bin/uvicorn app.main:app --reload --workers 1 --port 8000

# SPA, in another shell
cd frontend && npm install && npm run dev      # :5173
```

Vite proxies `/api`, `/ws` and `/healthz` to the API, so the browser origin is identical
in development and production and CORS never enters the picture. Point it elsewhere with
`VITE_API_PROXY_TARGET`.

> `--workers 1` is not a default to raise: the replay engine is an in-process task and
> additional workers would double-advance the fleet.

---

## Testing and quality

```bash
make test          # full suite, against a disposable database it creates
make test-unit     # pure domain tests, no database
make lint          # ruff
make typecheck     # mypy --strict over core, domain, ml
```

| Suite | Count | Scope |
|---|---|---|
| `tests/unit` | 167 | Pure domain functions and the ML feature contract |
| `tests/integration` | 204 | Real PostgreSQL, real Alembic, real seed |
| `tests/ml` | 21 | Model quality gates — skipped when no artifact is staged |
| `tests/performance` | 25 | Latency budgets and query-count bounds |

408 tests total, 9 skipped when no model artifact is staged.

Tests run against a **real** database rather than a mock, because most of what is worth
verifying lives in the schema: partial indexes, row locks, `CHECK` constraints, unique
alerts.

> **The suite drops and recreates the `public` schema.** It must only ever be pointed at a
> disposable database. `make test` starts one in a container and removes it afterwards. If
> you run pytest directly, set `FDT_TEST_DATABASE_URL` explicitly — there is deliberately
> no host or port guess.

CI (`.github/workflows/ci.yml`) runs three jobs: API lint + types + tests + a migration
round-trip, a frontend build that asserts the 3D assets reached the bundle, and Docker
builds of both images with an `nginx -t` and `docker compose config` validation.

---

## Production deployment

```bash
cp .env.example .env
```

Set at minimum:

```bash
FDT_ENVIRONMENT=production
POSTGRES_PASSWORD=<a real password>
FDT_DEMO_MODE=false                        # also enforced at startup
```

**The application has no authentication.** Do not publish it to the public internet —
see [Security model](#security-model) for the deployment boundary that does apply.

Then:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

The production overlay changes:

| | Development | Production |
|---|---|---|
| `api` port | `127.0.0.1:8000` | not published |
| `db` port | `127.0.0.1:5433` | not published |
| `FDT_ENVIRONMENT` | `development` | `production` |
| `FDT_DEMO_MODE` | `true` | `false` |
| CORS | localhost origins | empty — same-origin only |
| Resources | unbounded | CPU and memory limits on `api` and `web` |
| Logging | Docker default | 10 MB × 3 files per service |
| Postgres | defaults | tuned pools, `wal_compression`, slow-query logging |

Apply migrations and seed as a release step:

```bash
make migrate && make seed
```

### Scaling notes

The monolith runs **one replica** while demo mode is on, because the replay engine is an
in-process task. With `FDT_DEMO_MODE=false` and an external ingest feed against
`POST /api/v1/telemetry`, the API is stateless and can be replicated behind the same nginx
config.

---

## Operations

### Health checks

`GET /healthz` reports each dependency explicitly:

```json
{
  "status": "degraded",
  "db": true,
  "model": { "loaded": false, "version": "fallback", "degraded": true,
             "error": "... No such file or directory" },
  "replay": { "running": true, "paused": false, "tick": 16, "cmapss_loaded": true }
}
```

`status` is `ok` only when both the database and a real model are healthy. `GET /readyz`
is the lighter probe suitable for a load-balancer check. Both containers also carry a
Docker `HEALTHCHECK`, so `depends_on: service_healthy` gates startup ordering.

### Logging

Structured JSON, one object per line, with a request ID on every line. The ID is taken
from an inbound `X-Request-ID` when present and echoed on the response, so a trace spans
nginx and the API. Domain errors are logged with their code and request ID, never with a
stack trace.

### Backups

```bash
make db-dump        # → backend/backup.sql.gz
make db-restore     # restore (destructive)
```

---

## Security model

**This application has no authentication or authorisation.** That is a deliberate design
choice, not an oversight, and this section states exactly what it does and does not protect.

Migration `b7e3f1a9c2d4` removed the authentication subsystem — the `users` table, the
`user_role` enum and five foreign keys — along with the login route, the token issuing and
verification code, and the router-level role dependency. No password hashing, token issuing
or identity check exists anywhere in `backend/app/` or `frontend/src/`.

The consequences, stated plainly:

- **All 27 documented endpoints are open.** The OpenAPI document declares no
  `securitySchemes` and no global `security` requirement; no endpoint carries a security
  requirement. There is no role, session or principal concept in the request path.
- **13 mutating endpoints are open to anyone who can reach the API**, including through the
  nginx `/api/` proxy:

  ```
  POST   /api/v1/work-orders              PATCH /api/v1/spares/{part_ref_id}
  PATCH  /api/v1/work-orders/{id}         POST  /api/v1/spares/{part_ref_id}/reserve
  PATCH  /api/v1/alerts/{id}/ack          POST  /api/v1/agencies/{id}/bookings
  POST   /api/v1/telemetry                POST  /api/v1/seed/run
  POST   /api/v1/internal/ml/predict      POST  /api/v1/ml/reload
  POST   /api/v1/demo/pause|resume|tick
  ```

- **The audit trail has no actor.** `audit_log.actor_id` is written as `NULL` at all six
  call sites in `services/maintenance_service.py` (`actor_name="system"`). The table
  records what changed and when, never who changed it. The `ix_audit_actor` index built for
  the removed user table was dropped in Phase 3.
- **There is no demo password.** An earlier revision seeded three demo accounts with
  committed passwords; those rows no longer exist and nothing in the console asks for a
  credential.

### What the application does protect

| Concern | Measure |
|---|---|
| SQL injection | SQLAlchemy parameter binding throughout; the only string-built SQL is a static `COUNT` label in the performance tests |
| Secrets in source | `.env` is gitignored; `.env.example` holds placeholders only |
| Secrets in containers | Backend ports bind to loopback in dev and are unpublished in prod; both images run as non-root with `no-new-privileges` |
| WebSocket origin | `realtime/ws.py` checks `Origin` against the allowlist before `accept()`, closing with `4408`. This is a cross-site-requesting defence, **not** an identity check — it does not distinguish two authorised callers from two anonymous ones |
| Bounded fan-out | The WebSocket bus uses a bounded `asyncio.Queue` with an explicit overflow sentinel, so a slow client cannot exhaust server memory |
| Action traceability | Every mutation writes an `audit_log` row with action, entity and a JSON diff. It answers *what changed*, not *who changed it* |
| Error disclosure | SQLAlchemy and psycopg errors are not interpolated into HTTP responses |
| Dependency and image surface | `npm audit`, Dependabot, and container image scanning run in CI |

### Deployment boundary

Because there is no authentication, **network placement is the access control.** The API is
designed to run inside a trust boundary it does not itself enforce:

| Placement | Supported |
|---|---|
| Local development (`make up`, ports on `127.0.0.1` only) | **Yes** — intended configuration |
| Internal network behind a VPN, or an air-gapped network | **Yes** — intended configuration |
| Shared staging environment | Only with authentication added in front of the API |
| Public internet | **No.** Do not expose it. Anyone who can reach it can create work orders, acknowledge alerts, move stock, inject telemetry and force a model reload |

If you need public or multi-tenant exposure, put an authenticating reverse proxy in front of
`/api/` and `/ws` before exposing it. The application is deliberately built so that this can
be added without changing the API shape — no endpoint currently *depends* on being
unauthenticated.

`FDT_DEMO_MODE` chooses where telemetry comes from; it has no effect on any of the above.

nginx serves over plain HTTP by default — terminate TLS at the load balancer, or add a
`listen 443 ssl` block to `docker/frontend/nginx.conf.template`.

---

## Performance budgets

Enforced by `tests/performance/test_budgets.py`:

| Budget | Target |
|---|---|
| Fleet read endpoints (`/fleet/*`, `/aircraft/*`, `/spares`, `/agencies`, `/alerts`) | < 200 ms |
| `/internal/ml/predict` | < 100 ms |
| `/healthz` | < 5 ms, no database round-trip for the liveness path |
| Query count | Must not scale with fleet size — no N+1 |

The aggregate read path is one pass over the fleet rather than per-aircraft queries;
`tests/performance` asserts that by counting statements.

---

## Working with the 3D assets

`frontend/public/models/` holds ~9 MB of geometry, all fetched on first paint:

| File | Size | Used by |
|---|---|---|
| `rafale.glb` | 3.0 MB | Aircraft body |
| `landing-gear.glb` | 2.5 MB | Landing gear |
| `engine.bin.gz` | 1.9 MB | Engine — custom quantised mesh, gunzipped client-side |
| `radar.glb` | 1.7 MB | Radar array |
| `engine.meta.json` | 1.5 KB | Engine mesh header |

Hydraulics and the fuel system are procedural three.js geometry and ship no assets.

These are committed as plain git blobs, **not** Git LFS, so a fresh clone always has a
working viewer with no extra setup. `.gitattributes` marks them binary and documents the
one-command LFS migration if you would rather they stop bloating history.

`engine.bin.gz` must be served **without** `Content-Encoding: gzip`: the client sniffs
the magic bytes and gunzips it itself. `docker/frontend/nginx.conf.template` sets `gzip off` for
`.gz` for exactly this reason.

---

## Troubleshooting

**The 3D viewer is blank and the status reads "Could not load a model"**
The assets did not reach the bundle. Check `frontend/dist/models/` and that
`frontend/public/models/` is intact; `git lfs` is not in use, so a clone should have real
files.

**`/healthz` reports `status: degraded` with a missing-file error**
`backend/data/ml/` is empty: the boosters are not committed and have not been fetched.
The app stays functional on the deterministic `rul = 125 - cycle` curve, so this is
visible rather than silent. To serve the real model, set `FDT_ML_ARTIFACTS_URL` in `.env`
and run `make fetch-model`; the next API start (or `POST /api/v1/ml/reload`) picks it
up. `make fetch-model` with no URL set explains what to configure instead of skipping.

**The API boots but the replay engine reports no aircraft**
`backend/data/cmapss/` is empty. Run `make fetch-data`. A missing CSV is not an error
during seeding, so this presents as an empty fleet rather than a crash.

**`make test` refuses to run**
By design: the suite drops and recreates the `public` schema. `make test` provisions a
throwaway container for it. To use your own, export `FDT_TEST_DATABASE_URL` pointing at
a database you are willing to lose.

**`npm run dev` cannot reach the API**
The Vite proxy targets `http://127.0.0.1:8000` by default. Override with
`VITE_API_PROXY_TARGET`. If the API is in Docker and bound to loopback, that is already
correct.

**Port already in use**
`WEB_PORT`, `API_PORT` and `POSTGRES_PORT` in `.env` all take overrides.

**The fleet advances twice as fast as expected**
More than one API replica with `FDT_DEMO_MODE=true`. The replay engine is in-process;
run exactly one.

---

## Demo accounts

There are none. Migration `b7e3f1a9c2d4` removed the `users` table and every login
route along with it; `python -m app.seed.run` seeds aircraft, parts, spares and
telemetry only. If you need per-operator identity, put an authenticating reverse
proxy in front of `/api/` and `/ws` (see [Security model](#security-model)).

---

## Design documentation

Fifteen documents covering requirements through deployment, in [`docs/`](docs/README.md).

| # | Document |
|---|---|
| 01 | [Requirements evaluation](docs/01-requirements-evaluation.md) — spec-vs-data gap analysis, decisions taken |
| 02 | [Backend architecture](docs/02-backend-architecture.md) — layers, modules, request lifecycle |
| 03 | [System flow diagrams](docs/03-system-flow-diagrams.md) |
| 04 | [User flow diagrams](docs/04-user-flow-diagrams.md) — per-role journeys |
| 05 | [Database design](docs/05-database-design.md) — full DDL, indexes, derived columns |
| 06 | [API specification](docs/06-api-specification.md) — every endpoint, shapes, status codes |
| 07 | [Business rules](docs/07-business-rules.md) — rules 19–26, algorithms, worked examples |
| 08 | [ML service](docs/08-ml-service.md) — feature contract, artifacts, fallbacks |
| 09 | [Realtime and demo mode](docs/09-realtime-and-demo-mode.md) — WebSocket protocol |
| 10 | [Development plan](docs/10-development-plan.md) |
| 11 | [Deployment and NFRs](docs/11-deployment-and-nfr.md) |
| 12 | [Model training pipeline](docs/12-model-training-pipeline.md) |
| 13 | [Multi-regime training report](docs/13-multi-regime-training-report.md) |
| 14 | [Final status report](docs/14-final-status-report.md) — measured numbers and open defects |
| 15 | [Serving the pooled model](docs/15-serving-the-pooled-model.md) — the 32-column contract |

Start with **14**.

---

## Credits and licence

**Telemetry** — NASA Prognostics Center of Excellence,
[C-MAPSS Jet Engine Simulated Data](https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data).
Public domain.

**Engine model** — "Turbine | Turbofan Engine | Jet Engine" by
[blenderbirb](https://sketchfab.com/3d-models/turbine-turbofan-engine-jet-engine-74c6aceed86b4a41aaad3b93afc3e262),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

**Fleet reference data** — the eight maintenance CSVs originate from a project dataset;
see [`docs/01`](docs/01-requirements-evaluation.md).

**Software** — FastAPI, SQLAlchemy, Alembic, Pydantic, XGBoost, PostgreSQL, React, Vite,
three.js, nginx, Docker.

<div align="center">

MIT License · see [LICENSE](LICENSE)

</div>
# Fleet Digital Twin — Backend

FastAPI + PostgreSQL 16 + XGBoost (NASA C-MAPSS). Fully offline: no outbound network
calls at runtime.

Design documents live in `../docs/`. Start with `../docs/README.md`.

## Quick start

```bash
cp .env.example .env          # set FDT_JWT_SECRET
docker compose up --build
# → http://localhost:8000/docs
```

Local development:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d postgres
alembic upgrade head
python -m app.seed.run
uvicorn app.main:app --reload --workers 1
```

Demo logins: `commander` / `officer` / `viewer` (passwords in `app/seed/run.py`).

## ML artifacts

The model is not committed. Stage it from the Drive artifacts before starting:

```bash
python -m scripts.stage_ml_artifacts --source <dir-with-models/multi> --variant all
cp <dir-with-raw>/*_FD*.txt data/cmapss/
```

`FDT_ML_VARIANT` selects the generation — `all` (32 features, pooled over
FD001–FD004, **default**), `full` (29, FD001 only) or `holdout` (29, Phase 1 80/20 with a
`StandardScaler`). Do **not** set `FDT_ML_MODEL_PATH`: it overrides only the model and
leaves the contract to resolve from the variant. Without artifacts the app still boots
and answers every request from the deterministic `rul = 125 − cycle` fallback —
`/healthz` reports `status: degraded`.

Details, including the two constant sensors the pooled contract needs:
[`../docs/15-serving-the-pooled-model.md`](../docs/15-serving-the-pooled-model.md).

## Layout

```
app/
├── main.py            FastAPI factory, lifespan, middleware
├── core/              config · security · errors · logging · deps
├── db/                session · unit_of_work (transaction + audit boundary)
├── models/            20 SQLAlchemy tables, grouped
├── domain/            PURE: rules · health · aggregation · scheduling
├── schemas/           Pydantic v2 request/response models
├── repositories/      data access, no business logic
├── services/          use cases, one per endpoint intent
├── ml/                model_store · features · inference · attribution · fallback
├── realtime/          ws · bus · replay · events
├── api/v1/            auth · fleet · maintenance · telemetry · ops
└── seed/              run · loaders · derived · cmapss
alembic/               migrations (schema only — never data)
data/ml/<variant>/     staged model artifacts (gitignored)
data/raw/              the 8 Drive CSVs, vendored
data/cmapss/           raw C-MAPSS FD001–FD004 (train/test/RUL; 43 MB, from NASA)
scripts/train_rul.py   Phase 0 — does NOT yet reproduce the serving contract (see below)
scripts/stage_ml_artifacts.py   copies Drive artifacts into data/ml/<variant>/
tests/                 unit (rules) · integration · ml (quality gate)
```

## Layer rules

1. `domain/` imports only stdlib and pydantic. No SQLAlchemy, no FastAPI.
2. Routers are thin: validate → call one use case → return.
3. Use cases never build SQL; repositories never compute business logic.
4. Every mutation goes through `UnitOfWork`, which guarantees an `audit_log` row.

## Business rules

`app/domain/rules.py` implements spec items 19–26 with no I/O, so they test in
microseconds:

```bash
pytest tests/unit/test_rules.py -q      # 40 tests, ~50 ms
```

Boundaries are strict `>`: health **0.70 → watch**, **0.40 → critical**; RUL must be
**strictly > 30** for mission-ready. Tie-breaks: worst part and engine spare both fall
back to `engine → radar → gear → hyd → fuel` and `fan → hpc → hpt → lpt` order.

## ML

The serving model is trained by `Model_training_249.ipynb` and staged with
`scripts/stage_ml_artifacts.py` — see "ML artifacts" above.

Without artifacts the service runs a deterministic fallback (`rul = 125 − cycle`) and
every response carries `model.fallback: true` with a `reason`, so the demo never fails.
Replay is disabled until `data/cmapss/train_FD001.txt` exists.

> **`scripts/train_rul.py` does not reproduce the serving contract.** It trains 16
> features, includes `cycle` (a leakage vector — it was the most important column at
> 0.3585 before removal), takes an uncapped RUL target, and computes rolling means without
> standard deviations. Until it is reconciled, the notebook is the only producer of the
> artifact and it cannot be regenerated in CI. This is Phase 0 task 0.1 in
> [`../docs/10`](../docs/10-development-plan.md) and remains open.

## Demo mode

One C-MAPSS cycle per aircraft every 1.2 s, staggered so the fleet does not fail in
lockstep. Wrap at end-of-life is instant and resets EMA smoothing.

```bash
curl -X POST localhost:8000/api/v1/demo/pause -H "authorization: Bearer $TOKEN"
curl -X POST localhost:8000/api/v1/demo/tick  -H "authorization: Bearer $TOKEN"
```

**`--workers 1` is mandatory.** The replay engine is an in-process task; multiple
workers would run multiple loops and double-advance the fleet.

## Data provenance

| Source | Role |
|---|---|
| `data/raw/*.csv` (8 files) | fleet, spares, agencies, work orders, technical records |
| `data/cmapss/train_FD001.txt` | engine telemetry + RUL model |

Only the engine is data-driven. `radar`, `gear`, `hyd` and `fuel` derive health from
real maintenance burden (`maintenance_burden_v1`) and are always flagged
`simulated: true`. Agencies have no free-slot column in the source; `free_slot_days` is
derived as `ceil(30 / capacity_slots_per_month)`.

## Frontend Integration & Live Telemetry

The backend integrates directly with the 3D Fleet Digital Twin (React + three.js):

- **Real-time WebSocket (`/ws/fleet?token=...`)**: Streams `cycle.tick`, `health.updated`, and `alert.raised` events every 1.2s.
- **REST Endpoints**:
  - `POST /api/v1/auth/login`: Issues JWT tokens for `commander`, `officer`, and `viewer`.
  - `GET /api/v1/aircraft`: Initial fleet state, risk levels, and 5-subsystem health values.
  - `POST /api/v1/alerts/{id}/acknowledge`: Persists alert acknowledgments to PostgreSQL.
  - `POST /api/v1/maintenance/work-orders`: Creates and tracks persistent work orders.
- **Port Mapping**: Docker Compose is configured to map PostgreSQL to host port `5433:5432` to avoid conflicts with existing host PostgreSQL installations.
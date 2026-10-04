# 11 — Deployment & Non-Functional Requirements

Spec items 50–53, plus the container topology and the operational runbook.

---

## 1. Container topology

```mermaid
flowchart LR
    subgraph Host["Docker host"]
        subgraph Compose["docker-compose"]
            API["fdt-api<br/>FastAPI + uvicorn<br/>Python 3.11 slim, non-root<br/>:8000"]
            PG[("fdt-postgres<br/>PostgreSQL 16-alpine<br/>:5432, named volume")]
        end
        FE["Frontend<br/>built static assets or dev server<br/>:5173"]
    end

    API -->|SQLAlchemy / psycopg| PG
    API -->|read at startup| DA[("/data/raw 8 Drive CSVs")]
    API -->|read at startup| CM[("/data/cmapss train_FD001.txt")]
    API -->|load once| MA[("/app/models_artifacts/*.json")]
    API -->|serve| GLB[("/app/static/models/*.glb")]
    FE -->|HTTP /api/v1| API
    FE -->|WSS /ws/fleet| API
    FE -->|GET /models/*.glb| API

    API -.->|none — fully offline| EXT(("No external services"))
```

The `EXT` node with no edges is deliberate and load-bearing: spec item 8 requires the system
to run with no calls to external services. There is no telemetry gateway, no ML registry, no
CDN, no auth provider.

---

## 2. Dockerfile

Multi-stage. The builder installs build tooling and compiles wheels; the runtime carries
only what is needed to serve.

```dockerfile
# ---------- stage 1: builder ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install .

# ---------- stage 2: runtime ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FDT_DATA_DIR=/data

RUN groupadd -r fdt && useradd -r -g fdt -d /app fdt
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY alembic/ alembic/
COPY alembic.ini .
COPY app/ app/
COPY scripts/ scripts/
COPY data/ data/                       # Drive CSVs + C-MAPSS, vendored
COPY models_artifacts/ models_artifacts/

RUN mkdir -p /app/static/models \
 && chown -R fdt:fdt /app

USER fdt
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers"]
```

Two decisions worth stating:

**`--workers 1`.** The replay engine is an in-process asyncio task
([09](09-realtime-and-demo-mode.md)). Multiple workers would run multiple replay loops
against one database and double-advance every aircraft. Horizontal scaling requires
promoting an external telemetry source and setting `FDT_DEMO_MODE=false`. This is the
constraint behind risk R11.

**`COPY models_artifacts/`** — the model artifact is baked into the image so the container
is self-contained. If the artifact is absent the build still succeeds and the service runs
on the documented fallback, logging one warning.

---

## 3. docker-compose.yml

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: fdt-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-fdt}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-fdt}
      POSTGRES_DB: ${POSTGRES_DB:-fdt}
    volumes:
      - fdt-db:/var/lib/postgresql/data
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-fdt} -d ${POSTGRES_DB:-fdt}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 10s
    restart: unless-stopped

  api:
    build: { context: ., dockerfile: Dockerfile }
    container_name: fdt-api
    depends_on:
      postgres: { condition: service_healthy }
    environment:
      FDT_DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-fdt}:${POSTGRES_PASSWORD:-fdt}@postgres:5432/${POSTGRES_DB:-fdt}
      FDT_JWT_SECRET: ${FDT_JWT_SECRET:?set FDT_JWT_SECRET in .env}
      FDT_CORS_ORIGINS: ${FDT_CORS_ORIGINS:-http://localhost:5173}
      FDT_DEMO_MODE: ${FDT_DEMO_MODE:-true}
      FDT_DEMO_TICK_SECONDS: ${FDT_DEMO_TICK_SECONDS:-1.2}
      FDT_RUL_CAP: ${FDT_RUL_CAP:-125}
      # Never pin FDT_ML_MODEL_PATH here. It overrides only the model, leaving the
      # contract to resolve from the variant, and the service then degrades to the
      # deterministic fallback with a valid model on disk. This exact line shipped and
      # did so silently -- see docs/15 §6.1.
      FDT_ML_VARIANT: ${FDT_ML_VARIANT:-all}
      FDT_ML_DATASET: ${FDT_ML_DATASET:-FD001}
      FDT_ML_FALLBACK: ${FDT_ML_FALLBACK:-true}
    ports: ["8000:8000"]
    restart: unless-stopped

volumes:
  fdt-db:
```

**Startup orchestration.** A container entrypoint runs migrations, seeds idempotently, then
hands over to uvicorn:

```bash
#!/bin/sh
set -e
echo "→ waiting for postgres"
until python -c "import psycopg; psycopg.connect('$FDT_DATABASE_URL').close()" 2>/dev/null; do
  sleep 1
done
echo "→ alembic upgrade head"
alembic upgrade head
echo "→ seed (idempotent)"
python -m app.seed.run
echo "→ starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Migrations own the schema, the seed owns the data, and both are safe to re-run — which is
what makes `restart: unless-stopped` safe.

---

## 4. Configuration reference

| Variable | Default | Notes |
|---|---|---|
| `FDT_DATABASE_URL` | `postgresql+psycopg://fdt:fdt@localhost:5432/fdt` | Required in compose |
| `FDT_JWT_SECRET` | dev placeholder | **Required** in production; compose fails fast without it |
| `FDT_JWT_TTL_MIN` | `720` | 12 h |
| `FDT_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated. Never `*` with credentials |
| `FDT_DEMO_MODE` | `true` | Enables the replay loop |
| `FDT_DEMO_TICK_SECONDS` | `1.2` | Spec 43 |
| `FDT_RUL_CAP` | `125` | Rule 26 |
| `FDT_ML_VARIANT` | `all` | Artifact generation: `all` (32 features, 4 subsets) · `full` (29, FD001) · `holdout` (29, +scaler) |
| `FDT_ML_FALLBACK` | `true` | `false` → 503 instead of degrading (useful in CI) |
| `FDT_ML_DATASET` | `FD001` | Subset the demo **replays**. Independent of the variant — see docs/15 §1 |
| `FDT_LOG_LEVEL` | `INFO` | Structured JSON above `WARNING` |
| `FDT_DATA_DIR` | `/app/data` | Drive CSVs + C-MAPSS + `ml/`. Must match where the Dockerfile copies `data/`; a mismatch degrades silently |

`.env` is gitignored. `FDT_JWT_SECRET` has no committed default — compose uses
`${FDT_JWT_SECRET:?...}` so a missing value fails at parse time rather than silently
signing tokens with a known key.

---

## 5. Performance budgets (spec 50)

### 5.1 Targets

| Endpoint | p95 budget | p99 budget | Notes |
|---|---|---|---|
| `GET /fleet/summary` | 200 ms | 400 ms | 60-cycle series, 2 queries |
| `GET /aircraft` | 200 ms | 400 ms | 2 queries |
| `GET /aircraft/{id}` | 200 ms | 400 ms | 3 queries |
| `GET /aircraft/{id}/engine?window=60` | 200 ms | 400 ms | 4 queries, 60 × 5 rows |
| `GET /aircraft/{id}/parts/{part}` | 200 ms | 400 ms | 4 queries |
| `GET /fleet/heatmap` | 200 ms | 400 ms | 1 query, 40 cells |
| `GET /fleet/actions?limit=5` | 200 ms | 400 ms | 2 queries |
| `GET /maintenance/schedule` | 200 ms | 400 ms | 3 queries |
| `POST /internal/ml/predict` | **100 ms** | 200 ms | Budget halved per spec |
| `POST /telemetry` (30 rows) | 300 ms | 600 ms | Not a GET; budget is ours |

### 5.2 Measured expectations

| Path | Expected | Headroom |
|---|---:|---:|
| `GET /fleet/summary` | 8–15 ms | ~15× |
| `GET /aircraft/{id}/engine?window=60` | 15–30 ms | ~7× |
| `POST /internal/ml/predict` | 3–5 ms | ~25× |

Framework overhead (middleware, JWT verify, Pydantic, serialisation) is ~4 ms. Database time
dominates the GETs; inference dominates the ML call. The headroom exists because the fleet
may grow from 8 to 100 aircraft without re-tuning.

### 5.3 How the budget is enforced

Not asserted and hoped for. Three mechanisms:

1. **`tests/performance/test_budgets.py`** — p95 over 200 iterations after a 20-iteration
   warmup. Fails CI on breach.
2. **Query-count assertion** — the test records the SQL count per endpoint and asserts it is
   **constant** as the aircraft count grows. A reintroduced N+1 fails CI immediately, before
   it becomes a slow demo.
3. **`ml_prediction.latency_ms`** — recorded on every prediction, so the ML budget is
   verifiable from SQL after any run:

   ```sql
   SELECT model_version, COUNT(*),
          ROUND(AVG(latency_ms),2) avg_ms,
          ROUND(MAX(latency_ms),2) max_ms,
          COUNT(*) FILTER (WHERE latency_ms > 100) AS violations
   FROM ml_prediction GROUP BY model_version;
   -- violations must be 0
   ```

### 5.4 Key optimisations

| Optimisation | Effect |
|---|---|
| Denormalised `mission_ready` / `risk_level` / `worst_part` on `aircraft` | Avoids 40 rule evaluations per dashboard request |
| Denormalised `health` / `risk_level` / `rul` on `aircraft_part` | Heatmap and actions list are single-index reads |
| Partial indexes on `WHERE risk_level='critical'` and `WHERE status <> 'done'` | Hot queries touch a fraction of the table |
| `DISTINCT ON` view for the latest prediction | One index scan per aircraft instead of a window function over all rows |
| `run_in_executor` for inference | Keeps the event loop free during tick storms |
| Connection pooling (QueuePool, 5 + 10) | No per-request TCP handshake |
| Only engine `health_snapshot` rows are written per tick | 5× fewer inserts than a naive all-parts loop |

---

## 6. Audit logging (spec 51)

**Every** work order, stock change and booking is logged with the user and time.

| Entity | Actions logged |
|---|---|
| `work_order` | create, update (status, priority, due_date, notes) |
| `spare` | reserve, restock, adjust, return |
| `agency` | book, cancel |
| `alert` | ack |

Guarantees:

- Written **in the same transaction** as the change. A work order without its audit row
  cannot exist.
- `actor_name` is denormalised so the trail survives user deletion.
- `before`/`after` hold JSONB snapshots of the changed columns only, not whole rows.
- `request_id` links the audit row to the access-log line and the response header.

```sql
-- Work orders created or changed today
SELECT at, actor_name, entity, entity_id, action,
       before -> 'status' AS was, after -> 'status' AS now
FROM audit_log
WHERE entity = 'work_order' AND at >= CURRENT_DATE
ORDER BY at DESC;

-- Every stock movement, with who and when
SELECT sm.created_at, u.username, s.part_ref_id, s.item_name,
       sm.delta, sm.reason, sm.work_order_id
FROM stock_movement sm
JOIN spare s ON s.id = sm.spare_id
LEFT JOIN users u ON u.id = sm.user_id
ORDER BY sm.created_at DESC;

-- Bookings, with the slot arithmetic that produced the ETA
SELECT b.created_at, u.username, a.name AS agency, b.slot_days,
       b.turnaround_days, b.lead_time_days, b.eta_date
FROM agency_booking b
JOIN agency a ON a.id = b.agency_id
LEFT JOIN users u ON u.id = b.created_by
ORDER BY b.created_at DESC;
```

`GET /api/v1/audit?entity=&actor=&from=&to=` (commander only) exposes the same data over
the API for an in-app compliance view.

---

## 7. Testing (spec 52)

### 7.1 Rules tests — the spec requirement

Rules 19–26 are unit-tested as pure functions ([07](07-business-rules.md) holds the full
matrix). Coverage:

| Rule | Cases |
|---|---|
| 19 risk | 3 bands, **both boundaries**, out-of-range rejection |
| 20 mission-ready | RUL above/below 30, **boundary 30**, all-parts-above-0.4, **boundary 0.4**, empty parts |
| 21 worst part | minimum, tie-break, single part, all parts |
| 22 action | 3 mappings, invalid input |
| 23 do-by | healthy → null, `rul−10`, **clamp when window closed**, non-engine null RUL |
| 24 back-in-service | **stock 0 vs stock > 0**, real agency values, zero slot, all-zero edge |
| 25 engine spare | weakest component, **tie prefers upstream**, null sensors ignored, all null |
| 26 RUL cap | above cap, at cap, below cap, **negative floor**, rounding |

Plus a golden-file test over the whole seeded fleet, which catches drift in any rule at once.

### 7.2 Full test matrix

| Layer | Scope | Target runtime |
|---|---|---|
| Unit | `domain/rules.py`, `domain/health.py`, `domain/scheduling.py`, `ml/features.py` | < 50 ms |
| Integration | Every endpoint, request/response validation, full RBAC matrix (3 × 20) | < 30 s |
| Concurrency | 20 parallel reservations on 1 unit; 20 parallel bookings on 1 slot | < 10 s |
| Contract | Response schemas vs. the committed OpenAPI snapshot | < 5 s |
| Performance | 200 ms / 100 ms budgets + query-count assertions | < 60 s |
| ML quality | MAE ≤ 25, determinism, health bounds, latency budget | < 20 s |
| Realtime | 60 s soak, event ordering, wrap behaviour, reconnect | < 90 s |

Total under 4 minutes. Fast enough to run on every commit, which is the only way the
query-count and latency assertions actually protect anything.

---

## 8. Security

| Concern | Control | Verification |
|---|---|---|
| Password storage | bcrypt cost 12 | Hash prefix `$2b$12$` |
| Token forgery | HS256, secret required in production | Compose fails without `FDT_JWT_SECRET` |
| Privilege escalation | Router-level RBAC; viewer denied mutations structurally | 7 × 3 integration tests |
| SQL injection | ORM parameter binding throughout; no string-built SQL | `rg "execute(f\"\|text("` in CI |
| CORS | Explicit allowlist, never `*` with credentials | Config test |
| Secret leakage | `.env` gitignored; no committed defaults | Pre-commit hook |
| Path traversal on `/models` | `StaticFiles` at a fixed mount; no user-controlled segments | Request test |
| Error disclosure | 500s log the traceback, return a generic message + `request_id` | Response-shape test |
| Username enumeration | Identical 401 message for unknown user and wrong password | Response-shape test |
| Token in a WS URL | `wss://` only; bounded TTL; grants nothing beyond read access | Documented |

---

## 9. Observability

### 9.1 Health endpoints

```json
// GET /healthz
{ "status": "ok", "db": true,
  "model": { "loaded": true, "degraded": false, "version": "ALL",
             "dataset": "FD001+FD002+FD003+FD004", "mae": 17.369, "fallback": false },
  "replay": { "running": true, "tick": 4821, "interval_seconds": 1.2,
              "cmapss_loaded": true, "replay_subset": "FD001",
              "subsets": { "FD001": 100, "FD002": 260, "FD003": 100, "FD004": 249 } } }

// GET /readyz  — additionally requires seeded data
{ "status": "ready", "aircraft_seeded": 8, "db": true, "model_loaded": true }
```

`status` is `degraded` and `model.degraded` is `true` whenever the artifact set did not
load — which includes the two configuration traps in [15 §6](15-serving-the-pooled-model.md).
Both failed silently for a while, so treat `status: degraded` as an alert condition rather
than a detail.

`readyz` failing while `healthz` passes is the correct signal: the process is alive but
should not receive traffic.

### 9.2 Structured logs

```json
{"ts":"2026-10-03T11:27:04.182Z","level":"INFO","request_id":"01JQ8X4T2M9K7P3R",
 "method":"GET","path":"/api/v1/fleet/summary","status":200,"duration_ms":9.4,
 "user":"commander","role":"commander"}
```

`X-Request-ID` on every response, echoed from an inbound `X-Request-ID` when present, so a
frontend error report maps to exactly one backend log line.

### 9.3 Metrics worth watching

| Metric | Source | Alert if |
|---|---|---|
| GET p95 latency | Request middleware | > 200 ms sustained |
| ML p95 latency | `ml_prediction.latency_ms` | > 100 ms |
| Replay tick latency | Replay loop | > 500 ms (1.2 s interval) |
| `budget_violations` count | `ml_prediction` query | > 0 |
| Unacknowledged critical alerts | `alert` query | > 0 for > 5 min |
| Spare below minimum | `spare` query | any row |
| Audit rows per mutation | `audit_log` query | < 1 (a mutation went unaudited) |
| Open booking conflicts | 409 rate | rising |

---

## 10. Operations runbook

### Start

```bash
cp .env.example .env          # then edit FDT_JWT_SECRET
docker compose up --build
# → http://localhost:8000/docs
```

### Verify

```bash
curl -s localhost:8000/healthz | jq
curl -s localhost:8000/readyz  | jq

TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"commander","password":"…"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/fleet/summary -H "authorization: Bearer $TOKEN" | jq
```

### Reset

```bash
docker compose down -v        # drops the volume; next start re-migrates and re-seeds
```

### Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `503 ModelUnavailableError` | `FDT_ML_FALLBACK=false` and no artifact | Train the model (Phase 0) or set `true` |
| Response shows `"model": "fallback"` | Artifact absent | Expected, not an error. Check `/healthz` |
| `healthz` reports `replay: false` | C-MAPSS file missing at `FDT_DATA_DIR` | Verify `/data/cmapss/train_FD001.txt` |
| `readyz` fails, `healthz` passes | Not seeded | `python -m app.seed.run` |
| Aircraft advance two cycles per tick | Two API instances running | Scale to one replica, or set `FDT_DEMO_MODE=false` |
| `docker compose up` fails on `FDT_JWT_SECRET` | Not set in `.env` | Set it |
| GLB requests 404 | Assets not mounted | Copy to `app/static/models/` |
| Frontend CORS error | Origin not allowlisted | Add to `FDT_CORS_ORIGINS` |

---

## 11. Data management

**Retention.** The demo writes ~32 rows per tick, ~96,000 rows/hour
([05 §9](05-database-design.md)). A pruning job keeps 5,000 cycles per aircraft in
`engine_telemetry`, `health_snapshot`, `component_health` and `ml_prediction`. Optional for
a demo; include before any multi-day run.

**Backup.** `pg_dump -Fc` for a full snapshot; the dataset is small enough that a nightly
dump plus `pg_dump -t audit_log` is sufficient. `audit_log` should never be pruned.

**Derived state.** `aircraft_part.health` and `aircraft.mission_ready` are denormalised. If
they ever drift from the time-series tables, rebuild rather than patch:

```sql
-- recompute engine health from the latest prediction for one aircraft
UPDATE aircraft_part ap
SET health = LEAST(1.0, ml.rul / 125.0)
FROM aircraft a
JOIN ml_prediction ml ON ml.aircraft_id = a.id
WHERE ml.cycle = a.current_cycle
  AND ap.aircraft_id = a.id
  AND ap.part_id = (SELECT id FROM part WHERE code = 'engine');
```

The time-series tables are the source of truth; the denormalised columns are a cache.

---

## 12. Non-functional traceability

| Spec | Requirement | Implementation | Verified by |
|---|---|---|---|
| 50 | GETs under 200 ms | §5 | `tests/performance/test_budgets.py` |
| 50 | ML under 100 ms | §5, [08 §10](08-ml-service.md) | `p95(latency_ms) < 100` |
| 51 | Log every work order, stock change, booking with user and time | §6 | Audit integration tests + SQL in §6 |
| 52 | Unit tests for rules 19–26 | [07](07-business-rules.md), §7.1 | `tests/unit/test_rules.py`, 22 named cases |
| 53 | Dockerfile and compose with API and Postgres | §2, §3 | `docker compose up` from clean |
| 8 | Runs offline, no external calls | §1 | CI network-egress assertion |
| 6 | OpenAPI docs at `/docs` | [02](02-backend-architecture.md) | Phase 1 exit criteria |
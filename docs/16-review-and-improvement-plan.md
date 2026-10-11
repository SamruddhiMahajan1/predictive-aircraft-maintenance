# 16 — Review & Improvement Plan

A full review of the Fleet Digital Twin: what was measured, what is broken, what to fix, a
standard training pipeline, and the innovations to add next.

**Everything below was measured**, not inferred. The stack was run live (PostgreSQL 16 +
uvicorn + the shipped XGBoost artifact), the full suite was executed, and the model's accuracy
was independently re-derived from raw C-MAPSS with a harness that reproduces the shipped
artifact's own reported metrics to three decimal places. Reproduction instructions are in
[Appendix A](#appendix-a--how-the-numbers-were-measured).

**Decisions taken:**

| Decision | Choice |
|---|---|
| Authentication | **None, by design.** The README's security claims are replaced with honest documentation |
| ML package location | **Top-level `ml/`** becomes the canonical ML home; the backend imports from it |
| Pipeline tooling | **Stdlib-first** — TOML config, local run registry, no tracking server, no extra containers |
| Feature contract | **One shared package**, imported by both training and serving |
| Sequencing | Serve-path fixes ship with the pipeline restructure; Phases 2–4 ship first |

---

## Table of contents

- [1. Executive summary](#1-executive-summary)
- [2. What is already good](#2-what-is-already-good)
- [3. Verified findings](#3-verified-findings)
  - [3.1 Critical](#31-critical)
  - [3.2 High — performance](#32-high--performance)
  - [3.3 Medium — database](#33-medium--database)
  - [3.4 Medium — frontend](#34-medium--frontend)
  - [3.5 Medium — test & CI integrity](#35-medium--test--ci-integrity)
- [4. Accuracy assessment](#4-accuracy-assessment)
- [5. Phase 0 — Honest security documentation](#5-phase-0--honest-security-documentation)
- [6. Phase 1 — Serving-path correctness](#6-phase-1--serving-path-correctness)
- [7. Phase 2 — Performance](#7-phase-2--performance)
- [8. Phase 3 — Database](#8-phase-3--database)
- [9. Phase 4 — Frontend](#9-phase-4--frontend)
- [10. Phase 5 — Standard training pipeline](#10-phase-5--standard-training-pipeline)
- [11. Phase 6 — Innovations](#11-phase-6--innovations)
- [12. Cross-cutting: CI must actually gate](#12-cross-cutting-ci-must-actually-gate)
- [13. Ship order and effort](#13-ship-order-and-effort)
- [14. Appendix A — how the numbers were measured](#appendix-a--how-the-numbers-were-measured)

---

## 1. Executive summary

The system is **well-built and correctly architected at the seams** — pure domain rules, a
427-test suite against real PostgreSQL, sub-2ms inference, honest `/healthz` degradation
reporting, multi-stage non-root images with healthcheck-gated startup. That foundation should
not be touched.

The problems are concentrated in three places:

1. **Two silent model defects.** The serving path zeroes two sensor inputs that training used
   (`s8`, `s13`), which makes predictions optimistic by ~0.7 cycles and permanently pins the
   `fan` component to "perfectly healthy". Both survive a fully green test suite because **no
   test in the repo ever compares a prediction to a true RUL.**

2. **Documentation that no longer matches the code.** Migration `b7e3f1a9c2d4` deleted the
   entire authentication subsystem — the `users` table, the `user_role` enum, five foreign
   keys — while the README's Security Model table still documents bcrypt, JWT, RBAC, WebSocket
   token verification and a bundle test that does not exist. There is no authentication
   anywhere in the codebase. This plan replaces those claims with accurate ones.

3. **Measured runtime problems** at the documented deployment shape: connection-pool
   exhaustion producing HTTP 500 at 20 concurrent clients, the replay engine blocking the
   event loop for up to 104 ms per tick, and 17.9% of wall time spent blocked.

Plus a structural problem: the feature transform is implemented **twice** — once in the
training notebook, once in `backend/app/ml/features.py` — and the two drifted by one constant.
That is the root cause of defect 1. Phase 5 removes the duplication rather than patching the
symptom.

---

## 2. What is already good

Do not regress these. They are the reason the rest of this document is a list of fixes rather
than a rewrite.

| Area | Evidence |
|---|---|
| **Test suite** | **427 passed, 1 skipped in 39 s** against real PostgreSQL — real partial indexes, row locks, CHECK constraints. Not mocks (`backend/tests/conftest.py:1-5`) |
| **Notebook leakage discipline** | `cycle` deliberately excluded with the rationale written down; `GroupShuffleSplit`/`GroupKFold` on `unit` with explicit overlap assertions; unit-ids namespaced `FDxxx#n` before any pooled split |
| **Inference latency** | **p50 1.93 ms, p95 3.01 ms** against a 100 ms budget — 30× headroom |
| **Honest degradation** | `Navbar.jsx:12` `ModelBadge` surfaces fallback state and reason; `/healthz` reports ML status. The system does not silently swap a heuristic for a model |
| **Pure domain core** | `domain/` imports only stdlib, which is why the rules are testable without a database and why `mypy --strict` passes |
| **Query-count guards** | `tests/performance/test_budgets.py:114` asserts per-request statement counts — an N+1 net that already caught things |
| **Infra** | Multi-stage non-root images, healthcheck-gated `depends_on`, loopback-only ports in dev and none in prod, `no-new-privileges`, log rotation; CI validates nginx config and 3D asset presence |
| **WebSocket backpressure (server)** | Bounded `asyncio.Queue` with overflow sentinel (`realtime/bus.py:32-33, 76-91`) |

---

## 3. Verified findings

### 3.1 Critical

#### C1 — There is no authentication, and the README says there is

Migration `b7e3f1a9c2d4` dropped `users`, the `user_role` enum, and five foreign keys. Docs
were never updated. Confirmed against the live OpenAPI document:

```
securitySchemes : <NONE DEFINED>
global security: <NONE>
27 of 27 endpoints carry NO security requirement
```

The README's Security Model table claims eight controls. **Five are false:**

| README claim | Reality |
|---|---|
| "Passwords — bcrypt via `passlib`" | `passlib` is not a dependency. A ghost reference survives at `backend/pyproject.toml:50` (mypy overrides) |
| "Sessions — signed JWT, HS256, explicit role claim" | No JWT code anywhere in `backend/app/` |
| "Authorisation — structural RBAC, router-level dependency" | Zero `require_role` / `current_user` in all six routers. `api/deps.py` is 13 lines |
| "WebSocket — token verification before `accept()`, closes 4401/4408" | Origin check and code 4408 exist (`realtime/ws.py:52-55`). No token verification, no 4401 |
| "Audit — every mutation records actor" | `actor_id=None` hardcoded at all six call sites; the `users` table it referenced was dropped |
| "`tests/bundle.test.mjs` asserts the demo password is eliminated" | **File does not exist.** `frontend/package.json:14` — `npm test` is `echo "No frontend tests configured."` |
| "The console requires an explicit sign-in" | No login UI anywhere in `frontend/src/` |
| "The API refuses to start on the dev JWT secret in production" | No such guard in `main.py` or `config.py` |

**13 unauthenticated mutating endpoints** are reachable through nginx `/api/`:

```
POST   /api/v1/work-orders              PATCH /api/v1/spares/{ref}
PATCH  /api/v1/work-orders/{id}         POST  /api/v1/spares/{ref}/reserve
PATCH  /api/v1/alerts/{id}/ack          POST  /api/v1/agencies/{id}/bookings
POST   /api/v1/telemetry                POST  /api/v1/seed/run
POST   /api/v1/internal/ml/predict      POST  /api/v1/ml/reload
POST   /api/v1/demo/pause|resume|tick
```

**Decision: no authentication is added.** Phase 0 replaces the false documentation with an
accurate statement of the posture and its intended deployment boundary.

#### C2 — Train/serve skew: 2 of 32 features are silently zeroed

`ml/features.py:47` defines `MAD_REL_FLOOR = 1e-4`, applied at `:235` as
`if mad <= max(abs(median) * MAD_REL_FLOOR, eps): out[sensor] = 0.0`.

The training notebook floors MAD **only when it equals zero** (`max(mad, 1e-6)`). Measured
against the shipped artifact's own `regime_baselines_all.json`:

| Sensor | median | MAD | backend floor | training | serving |
|---|---:|---:|---:|---|---|
| `s8` | 2388.06 | **0.04** | 0.2388 | used, \|z\| → 12.5 | **z = 0** |
| `s13` | 2388.06 | **0.04** | 0.2388 | used, \|z\| → 12.5 | **z = 0** |

`s8`/`s13` are **not** constant sensors — their MAD is genuinely non-zero. The code comment at
`features.py:236-241` justifies the floor for *constant* sensors (`s10`, `s16`), an argument
that does not apply here.

The booster's own split thresholds corroborate the training-time magnitudes: `s6` splits at
−70000…−10000, and `s10`/`s16` at 0 / 10000 / 30000.

**Measured cost** (FD001 official test, final cycle per engine, 100 unseen engines):

```
notebook semantics : RMSE 17.942   MAE 13.079     <- the artifact's own claim, reproduced exactly
backend  semantics : RMSE 18.290   MAE 13.393
delta              : mean +0.700 cycles, sd 1.961, max |delta| 14.43
direction          : OPTIMISTIC — the model over-predicts remaining life
```

#### C3 — The `fan` component can never fail

`domain/rules.py:24` maps `fan → ["s8", "s13"]`. Both are floored to `z = 0.0` in
`ml/attribution.py:60-62`, using the same floor. Proven by running the real code at end of life:

```
component_health: {'fan': 1.0, 'hpc': 0.0, 'hpt': 0.0, 'lpt': 0.0}
fan inputs = [0.0, 0.0] -> mean_z = 0.0 -> health = 1.0   (PERMANENTLY PERFECT)
```

`engine_spare()` can therefore never select `fan`, and **no fan alert can ever be raised**. A
quarter of the engine is dead code. The existing suite cannot detect this:
`tests/unit/test_inference.py:187` checks only `hpc`, and passes `z` directly, bypassing the
scorer where the floor lives.

Good news: `s8`/`s13` are genuine C-MAPSS fan sensors (`Pfan`, `RPM`). Fixing C2 revives `fan`
automatically — **no mapping change required**.

---

### 3.2 High — performance

#### H1 — Connection pool exhaustion produces HTTP 500

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 5 reached,
connection timed out, timeout 30.00
```

Reproduced on the lightest read endpoint (`/api/v1/fleet/summary`) at **20 concurrent clients**.
Pool is `pool_size=5, max_overflow=5` (`core/config.py:32-33`). The replay holds ~2
connections permanently (serialised ticks), retention takes a third for the duration of its
pass. `session.py:48-55` sets no `pool_timeout`, so SQLAlchemy's 30 s default applies.

#### H2 — The replay engine blocks the event loop

`realtime/replay.py:133-155` is `async def`, but every database call inside is **synchronous
psycopg executed on the event loop thread** — 8 aircraft × ~9 serialised round trips per tick.
Only `inference.predict` is offloaded (`:122`). `retention.py:134` already uses
`asyncio.to_thread`, so this is an oversight rather than a constraint.

Measured on the lightest handler (`/healthz`), which contains no query work — any latency above
~1 ms is pure blocking:

```
min 2.94 ms   p50 5.09 ms   p90 10.94 ms   p99 64.54 ms   max 104.75 ms
requests blocked > 20 ms : 10/400 = 2.5%
worst-block share of total wall time    : 17.9%
```

This is with the database on **localhost**. `render.yaml` describes a cross-region database; at
40–120 ms RTT the same code path becomes multi-second stalls, during which the loop cannot
serve WebSocket drains, `/healthz` (the liveness probe), or any request.

#### H3 — Throughput plateaus regardless of concurrency

```
 1 client -> 24.3 ms/req    41.2 req/s
 5 clients-> 22.4 ms/req    44.7 req/s
10 clients-> 24.5 ms/req    40.8 req/s
```

Doubling clients buys nothing, because the single event loop is the bottleneck, not the pool.
`--workers 1` is correct for the in-process replay (`docker/backend/Dockerfile:63-66`), so the
fix is to unblock the loop, not to add workers.

#### H4 — Tick drift is real and unreported

```
ticks 210 -> 232 in 30.0 s  =  1.364 s per tick   (+13.6% drift)
status reports interval_seconds: 1.2             <- configured, not measured
```

`realtime/replay.py:204-213` exposes no achieved period, lag, or drift field. An operator
watching `/api/v1/demo/status` cannot see degradation. Compounding it, the kill-switch at
`:35` logs only every 50th tick (~60 s), so a persistently failing tick is near-silent — the
opposite of the "wall of exceptions" failure mode `retention.py:19-20` warns about.

#### H5 — Latency table

16 endpoints, 40 iterations each, live server, replay running:

| Endpoint | p50 | p95 |
|---|---:|---:|
| `/healthz` | 6.8 ms | 13.7 ms |
| `/api/v1/fleet/summary` | 24.5 ms | 104.9 ms |
| `/api/v1/aircraft` | 13.4 ms | 21.7 ms |
| `/api/v1/aircraft/Fighter-01` | 24.1 ms | 92.8 ms |
| `/api/v1/aircraft/Fighter-01/engine` | 42.8 ms | 109.4 ms |
| `/api/v1/aircraft/Fighter-01/engine?window=60` | 36.9 ms | 94.4 ms |
| `/api/v1/aircraft/Fighter-01/parts/engine` | 45.1 ms | 92.6 ms |
| `/api/v1/fleet/heatmap` | 15.9 ms | 85.5 ms |
| `/api/v1/fleet/actions` | 22.4 ms | 86.3 ms |
| `/api/v1/maintenance/schedule` | 25.4 ms | 38.1 ms |
| `/api/v1/spares` | 12.0 ms | 20.9 ms |
| `/api/v1/agencies` | 23.1 ms | 92.7 ms |
| `/api/v1/alerts` | 45.4 ms | 89.9 ms |
| `/api/v1/work-orders?limit=200` | 31.0 ms | 92.0 ms |
| `/api/v1/audit?limit=100000` | 12.4 ms | 90.4 ms |
| `/api/v1/fleet/summary?window=500` | 32.9 ms | 78.8 ms |

All pass the 200 ms p95 budget **at 8 aircraft**. The 4–5× p95/p50 ratio is the replay
blocking (H2), not query cost. The sum of p50 across all sixteen — one full UI refresh — is
414 ms. The p95 column is what a user feels.

---

### 3.3 Medium — database

Every item below was confirmed with `EXPLAIN (ANALYZE, BUFFERS)` against the live schema.

#### M1 — 7 of 33 indexes (21%) are dead weight

| Drop | Redundant because |
|---|---|
| `ix_tel_window` | byte-identical to `uq_engine_telemetry_aircraft_id_cycle` |
| `ix_ch_window` | byte-identical to `uq_component_health_aircraft_id_cycle` |
| `ix_mlp_window` | byte-identical to `uq_ml_prediction_aircraft_id_cycle` |
| `ix_hs_window` | byte-identical to `uq_health_snapshot_aircraft_id_part_id_cycle` |
| `ix_flight_ops_aircraft` | byte-identical to `uq_flight_ops_monthly_aircraft_ref_id_month` |
| `ix_ap_critical` | strict subset of `ix_ap_aircraft` |
| `ix_audit_actor` | indexes `actor_id`, which every call site writes as `NULL` |

The first four sit on precisely the tables the replay writes 8 rows/tick into. Dropping them
removes roughly 25% of index-write volume at 40 writes/sec, at zero query-plan cost — the
planner never prefers a duplicate.

#### M2 — Five missing indexes fix confirmed sequential scans

| P | Index | Fixes |
|---|---|---|
| **P0** | `health_snapshot(part_id, aircraft_id, cycle DESC) INCLUDE (health, risk_level)` | `fleet_repo.py:180,117` — `Seq Scan on health_snapshot` on the most-polled endpoint; makes `fleet_snapshots` index-only |
| **P0** | `engine_telemetry(recorded_at)`, `component_health(recorded_at)`, `health_snapshot(recorded_at)`, `ml_prediction(created_at)` | `retention.py:97` — `Seq Scan ... Filter: recorded_at < now()`, every 300 s, forever |
| **P1** | `alert(created_at DESC)` | `fleet_repo.py:262` — default `/alerts` does `Seq Scan` + `Sort` |
| **P1** | `work_order(status)` | `fleet_repo.py:83` — `Seq Scan` on the second-most-polled endpoint |
| **P1** | `aircraft(is_active)` | replay fleet scan every 1.2 s |

Plus 14 unindexed FK referencing columns, four of them `ON DELETE CASCADE` parents.
`docs/05-database-design.md:20` claims "Every FK is indexed. Postgres does not index the
referencing side automatically" — the migration violates this 14 times.

#### M3 — Query-level defects

| Issue | Location |
|---|---|
| `last_stock_movements` loads the **entire table with no LIMIT**, sorting in Python, on the one table with no retention job | `fleet_repo.py:202-210` |
| **Correctness:** `engine_history` collapses rows with an *unordered* dict comprehension over **all 5 parts** — the "engine health" shown to an operator can silently be a radar reading | `fleet_repo.py:130-138` |
| `list_work_orders` filters **after** `LIMIT` (wrong pages once > 200 rows), has no `ORDER BY` (non-deterministic pagination), unbounded `OFFSET`, and 2 N+1 queries per row | `maintenance_service.py:154-168` |
| `list_alerts` same shape; `count(Alert.id)` prevents an index-only scan where `count()` permits one | `maintenance_service.py:358-379`, `fleet_repo.py:272` |
| `_next_reference` uses `count(*)+1` → concurrent creates collide → `IntegrityError` → **bare 500**, not the 409 `DuplicateWorkOrderError` exists to give | `maintenance_service.py:47-49` |
| `/api/v1/audit` has **no `le=` bound** on `limit` — the only unbounded parameter in the API | `ops.py:143` |
| `days_available / days_available + days_unavailable` on `SmallInteger` columns is **integer division** in PostgreSQL. Latent only because the seed sets `days_unavailable=0`; 830/3300 rows are affected the moment real data lands | `fleet_repo.py:314-326` |
| Exactly **one** `selectinload` in the entire codebase, and zero `lazy=` declarations. `Logistics.for_part` lazy-loads `spare` and `agency` inside a **40-iteration loop** | `fleet_repo.py:49,71`; `fleet_service.py:329` |
| Four `cascade="all, delete-orphan"` relationships onto high-volume tables lack `passive_deletes=True`; an ORM delete bypasses the database's `ON DELETE CASCADE` | `models/fleet.py:76-87` |
| 11 sites use naive `datetime.utcnow()` into `timestamptz` columns — interpreted in the session `TimeZone`, so a DB on `Asia/Kolkata` stores the audit trail 5h30m wrong. `retention.py:90` does it correctly | `models/*.py` |
| Zero `server_default` in the entire migration; `TimestampMixin` declares `now()` but no model uses it | `d50c12bdb5c9`, `db/session.py:26-29` |

#### M4 — Scale readiness

- **No partitioning** on the four high-volume tables. At the documented rate (8 rows/tick ×
  3,000 ticks/h) `ml_prediction` reaches ~10⁷ rows in ~17 days and ~34 GB.
- **Zero autovacuum tuning anywhere in the repo.** With the 0.2 default, autovacuum at 10⁷ rows
  waits for 2,000,000 dead tuples — bloat becomes unbounded between passes.
- `stock_movement` and `audit_log` are **never pruned** (`retention.py:69-74` covers neither);
  `stock_movement` is the one table loaded without bound.
- Partitioning is **blocked on a design decision**: all four tables carry
  `UNIQUE(aircraft_id, cycle)`, which is the `ON CONFLICT` target for every replay upsert.
  Range-partitioning on `recorded_at` forces re-keying to `(recorded_at, aircraft_id, cycle)`,
  changing the conflict semantics the replay depends on.

---

### 3.4 Medium — frontend

| # | Issue | Location |
|---|---|---|
| **FE1** | `key={++seq.current}` increments on **every render**, unmounting and rebuilding the entire inspector subtree, its `<canvas>` and the sensor table **~6.7×/second** (8 `health.updated` frames per 1.2 s tick). It also makes the `.chg` value-flash replay from frame 0 forever. Fix: use the `key` already computed at `:20` | `components/Inspector.jsx:37` |
| **FE2** | `store.js:34` is one global version counter with **no selector**; `useMemo`/`useCallback`/`React.memo` appear **0 times** in the codebase. All 11 subscribers re-run per emit, and `fleetStats()` is computed twice per paint | `state/store.js:34`, `components/Kpis.jsx:9`, `FleetHealth.jsx:57` |
| **FE3** | `refreshAircraft` and `refreshEngine` **share one `detailSeq` counter**. `Inspector.jsx:77-78` fires them back to back, so the aircraft response always fails `seq !== detailSeq`; `applyDetail()` never runs and `availability`/`partRul` never populate | `state/server.js:213,221,230` |
| **FE4** | `innerHTML` sink fed by database-controlled `spare.item_name` / `agency.name`. Not exploitable today (no auth, operator-seeded data), but it is the one place DB content reaches an HTML-parsing sink in a console that can create work orders | `components/Tooltip.jsx:11` |
| **FE5** | Same handler forces a synchronous reflow per `pointermove` (`innerHTML` write → `offsetWidth` read), ~60–120×/s, interleaved with the 3D loop's own DOM writes | `components/Tooltip.jsx:8-15` |
| **FE6** | `three/loop.js:44-45` reads `stage.clientWidth/Height` *after* writing styles — **4–5 forced layouts per frame**. Cache in `rt`, refresh on resize | `three/loop.js:44-45` |
| **FE7** | `R.dispose()` frees no geometries, materials, textures, or the PMREM render target, and never calls `forceContextLoss()`. `subFaults.js:26-28` additionally clones geometry and material per model, doubling resident set | `three/index.js:37-45` |
| **FE8** | `URL.createObjectURL` never revoked — leaks a Blob per CSV export | `lib/plan.js:88-99` |
| **FE9** | WebSocket messages parsed and dispatched synchronously per frame, no queue, no depth cap, no rAF coalescing. The *server* has a bounded queue with overflow handling; the client has none | `lib/api.js:267-273` |

**Weight.** 9.2 MB of 3D assets, of which ~7.2 MB crosses the wire uncompressed.
No Draco, no brotli, and all three non-hero models (6.1 MB) begin downloading the instant the
jet paints.

| File | Size |
|---|---:|
| `rafale.glb` | 3.0 MB |
| `landing-gear.glb` | 2.5 MB |
| `engine.bin.gz` | 1.9 MB |
| `radar.glb` | 1.7 MB |

**nginx headers silently missing.** `add_header` does **not** merge across blocks —
`nginx.conf.template:84` (`= /index.html`) declares its own `add_header`, discarding all four
security headers inherited from the server block. **The main document ships with none of them.**
Separately, the `\.gz$` block at `:76` is dead code (the regex at `:68` matches first), and
there is no CSP.

---

### 3.5 Medium — test & CI integrity

Every finding in §3.1 survived a green suite.

- **No test anywhere compares a prediction to a true RUL.** `tests/ml/test_model_quality.py`
  never loads the booster, never predicts against a labelled engine, never checks a prediction
  is in the right ballpark. A ~10-line golden test would have caught C2 immediately.
- **`test_metrics_meet_the_gate` is tautological** (`:88-96`). It asserts
  `metrics["has_holdout"] is False` — literally certifying the *absence* of a holdout — and
  reads the JSON the notebook itself wrote. The MAE ≤ 14 / RMSE ≤ 20 / R² ≥ 0.80 gates from
  `docs/08:524-527` **are not implemented anywhere**.
- `test_rul_never_leaves_the_cap` (`:166`) asserts `0 <= rul <= 125`, which `cap_rul` guarantees
  by construction. `test_predictions_are_deterministic` (`:179`) does not assert
  `model["fallback"] is False`, so it passes identically when the fallback is answering.
- `test_z_scorer_guards_a_zero_mad` (`tests/unit/test_features.py:203`) asserts all values are
  `0.0`, which **also passes if the scorer returns `{}`** — and cannot detect the `mad=0.04`
  case that causes C2.
- **`frontend/package.json:14` — `npm test` is `echo "No frontend tests configured."`** and exits
  0. `ci.yml:123` reports a green no-op.
- **`frontend/package.json:15` states "both halves are type-checked in CI" — this is false.**
  `ci.yml:76` runs `mypy app/core app/domain app/ml` only; there is no `tsconfig.json` in the
  repo.
- `ci.yml:74` — `ruff format --check || true` is non-blocking.
- Docs quote metrics for a model that is not served: `docs/08:59` and `docs/01:51` report the
  FD001-only candidate's CV (`17.988 ± 1.487`) while the shipped artifact reports
  `17.369 ± 0.950`. Same label, different model.
- `docs/15:181` claims `data/ml/` is gitignored; `.gitignore:46` has it commented out, so the
  1.2 MB of artifacts are tracked.

---

## 4. Accuracy assessment

Measured on the FD001 official test set — 100 engines the model never trained on — against the
ground truth in `RUL_FD001.txt`.

```
FD001 official test, final cycle per engine:
  shipped artifact claim      RMSE 17.942   MAE 13.079
  my independent harness      RMSE 17.942   MAE 13.079    <- reproduced EXACTLY
  as actually served (backend) RMSE 18.290   MAE 13.393

Reference points:
  best possible constant       RMSE 41.556   MAE 36.767
  constant = train mean 87.4   RMSE 43.220   MAE 35.908
  constant = 125 (the cap)     RMSE 64.615   MAE 51.620
```

**Verdict: respectably good, ~30% off best-in-class, and currently served through a bug.**

The model beats the best trivial baseline by ~2.3×, which is real signal. Published XGBoost
results on FD001 with good feature engineering reach RMSE 15–17; the gap is features, not the
booster. Three structural caveats:

1. **The model has no holdout of its own.** `metrics_all_full.json` reports `has_holdout: false`.
   Its `cv_rmse` belongs to five *different* boosters. No number currently describes the
   artifact on disk.
2. **FD002/FD004 are not serving-ready.** RMSE 28.3 and 30.2 — broken, not hard. The cause is
   identified: `inference.py:62-63` classifies **one** regime from the **latest** cycle and
   writes it into **every** row of the window (`features.py:157-158`), while the notebook
   z-scored **each row against its own regime baseline**. FD001 has one regime, so the bug is
   invisible; the six-regime subsets get the wrong baseline for every non-final row.
3. **Threshold misclassification.** Against the `RUL ≥ 30` mission-ready boundary on the demo
   replay path: **3.89% misclassified** (grounded engines called flyable, and the reverse), with
   the prediction bias sitting inside the margin the thresholds rely on. `MISSION_READY_MIN_RUL`,
   `HEALTHY_ABOVE`, `WATCH_ABOVE` and the two `Z_*` anchors in `inference.py:23-24` are
   **uncalibrated constants with no derivation in the repo.**

---

## 5. Phase 0 — Honest security documentation

**0.25 day · no code risk**

| File | Change |
|---|---|
| `README.md` §Security model | Replace the table with an accurate statement: **no authentication by design**. List the 13 open mutating endpoints. State the intended deployment boundary (internal / VPN / air-gapped). Delete the false "requires an explicit sign-in" paragraph and the `tests/bundle.test.mjs` citation |
| `backend/pyproject.toml:50` | Remove `passlib.*` from mypy overrides — a ghost; passlib is not a dependency |
| `README.md` §Data sources | "20,631+ cycle rows across FD001–FD004" → FD001 by default; `--subset-all` fetches the rest |

**Gate:** `grep -ri "passlib\|jwt\|bcrypt\|rbac" README.md backend/pyproject.toml` returns
nothing.

---

## 6. Phase 1 — Serving-path correctness

**1 day · ships together with Phase 5**

| # | Fix | Location |
|---|---|---|
| 1.1 | Delete `MAD_REL_FLOOR`; floor **only** when `mad <= eps`, matching training. Rewrite the comment — it justifies the floor for *constant* sensors, which does not apply to `s8`/`s13` | `features.py:47,235`; `attribution.py:8,60-62` |
| 1.2 | Verify `fan` revives automatically. `rules.py:24` maps `fan → ["s8","s13"]`, genuine C-MAPSS fan sensors (`Pfan`, `RPM`). **No mapping change.** Assert end-of-life `fan < 0.5` | `tests/ml/test_model_quality.py` |
| 1.3 | Check `h.ready` **before** `build_window`, so `artifact_missing` becomes reachable. Today `z_scorer()` raises first, so a missing model reports `window_rejected:…` — the single most important diagnostic misfires | `inference.py:68-92` |
| 1.4 | Gate `warmup()` on `result["model"]["fallback"] is False`. `predict()` never raises, so `warm=True` is set for a model that was never exercised. Surface `warm` in `describe()` and on `/healthz` | `model_store.py:360-373, 251-260` |
| 1.5 | Track imputation **per sensor**. `s10`/`s16` are always missing, so `s6_imputed` is `true` on 100% of requests, destroying the documented "frontend cannot emit sensor_6 → accuracy loss" signal | `features.py:136-142` |
| 1.6 | Bound `_find_sensor_block` to the requested subset — it can return another subset's baseline (latent today, but it is exactly the failure the function exists to prevent) | `features.py:294` |

### The test that prevents recurrence

**The highest-value test missing from the repository.** Add to `tests/ml/test_model_quality.py`:

- **Golden accuracy** — last cycle of each of the 100 FD001 train engines through the real
  serving path; assert `RMSE < 22` and `MAE < 16`. Measured baseline **17.942 / 13.079**
- **Replace the tautological gate** — implement MAE ≤ 14, RMSE ≤ 20, R² ≥ 0.80 from
  `docs/08:524-527` against *measured predictions*, not the notebook's own JSON
- **Fan regression** — `fan < 0.5` at end of life
- **Fallback assertion** — `model["fallback"] is False` in `test_predictions_are_deterministic`

**Gate:** 427 existing tests stay green, **and** the golden test fails if `MAD_REL_FLOOR` is
reintroduced.

---

## 7. Phase 2 — Performance

**2 days · independent of the ML work**

### 2.1 Pool exhaustion → HTTP 500

| Change | File |
|---|---|
| Add `pool_timeout=5` (currently the 30 s default), `pool_recycle`, `application_name` | `db/session.py:48-55` |
| Raise `db_pool_size`; Aiven free is `max_connections=20`, so size *below* that | `core/config.py:32-33`, `render.yaml:148-151` |
| Cap the anyio threadpool to match, so requests queue rather than starving the replay | `db/session.py` |

### 2.2 Replay blocks the event loop

| Change | File |
|---|---|
| Wrap the DB block in `asyncio.to_thread` — `retention.py:134` already uses this pattern | `realtime/replay.py:133-155` |
| **Better:** give the replay a dedicated engine, so its 8 serialised round trips never occupy the request pool | `db/session.py` |
| One transaction per tick instead of 8 `COMMIT`s — 6.7 fsyncs/s → 0.83/s | `realtime/replay.py:155` |

### 2.3 Drift reporting

| Change | File |
|---|---|
| Add `last_tick_ms`, `achieved_interval_seconds`, `drift_pct`, `consecutive_failures` | `realtime/replay.py:204-213` |
| Log the first N tick failures, then throttle to every 50th — currently near-silent | `realtime/replay.py:35` |
| Fix the `demo_tick` race: `pause()` is set before in-flight ticks observe it, so two clients can run `tick_once` concurrently against the same aircraft | `api/v1/ops.py:136-140` |

**Gate:** 0 non-2xx under 50 concurrent clients for 60 s · `/healthz` p99 < 15 ms · reported
drift < 2%.

---

## 8. Phase 3 — Database

**2 days · all findings EXPLAIN-confirmed**

1. **Drop the 7 dead indexes** (M1). Add a test asserting no index is prefix-identical to a
   unique constraint, so the drift cannot reappear.
2. **Add the 5 indexes** (M2), plus the 14 missing FK indexes.
3. **Fix the query defects** (M3): `DISTINCT ON` for stock movements; `ORDER BY part_id` and a
   `part_id` filter in `engine_history`; pre-`LIMIT` filtering and real pagination in
   `list_work_orders` and `list_alerts`; `count()` instead of `count(Alert.id)`; a `SEQUENCE`
   for work-order references; a `le=` bound on `/audit`; explicit `cast(..., Numeric)` in the
   availability aggregation; `selectinload` on the aircraft-part relationships;
   `passive_deletes=True` on the four cascading relationships; timezone-aware timestamps.
4. **Scale** (M4): decide the partitioning key trade-off, add `autovacuum_*` tuning, prune
   `stock_movement` and `audit_log`.

**Gate:** every touched seq scan becomes an Index Scan under `EXPLAIN`; suite green;
`test_budgets.py` N+1 guards extended to the newly-touched paths.

---

## 9. Phase 4 — Frontend

**2 days**

| # | Change | Expected effect |
|---|---|---|
| 4.1 | `key={++seq.current}` → the `key` already computed at `Inspector.jsx:20` | **−6.7 subtree remounts/s**, −6.7 canvas redraws, −6.7 full-DOM query passes; fixes the perpetually-replaying `.chg` flash |
| 4.2 | Per-field selectors in `useStore.js`; `useMemo` the derived panels; `React.memo` the 6 props-free ones; `useMemo(() => fleetStats(), [version])` in `Kpis` and `FleetHealth` | −40 to −60 component renders/s |
| 4.3 | Coalesce WS messages into one `emit()` per `requestAnimationFrame` (`lib/api.js:267`) | **6.67 → 0.83 render waves/s (−87%)**, zero behaviour change |
| 4.4 | Split `detailSeq` into two counters | Restores `applyDetail()` — fixes `availability` / `partRul` never populating |
| 4.5 | `Tooltip`: `textContent` + `white-space: pre-line`; rAF throttle; drop the `offsetWidth` read | Removes the XSS sink and 60–120 forced reflows/s |
| 4.6 | Cache `clientWidth/Height` in `rt`; full `dispose()` traversal + `forceContextLoss()`; revoke CSV object URLs | −4–5 forced layouts/frame; removes the GPU leak |
| 4.7 | **Draco-compress the 3 GLBs** + `gzip_static` with pre-compressed variants | 3.0→0.6, 2.5→0.5, 1.7→0.35 MB → **9.2 MB → ~1.6 MB (−82%)** |
| 4.8 | Lazy-load the 3 non-hero models (6.1 MB currently starts downloading when the jet paints) | −6.1 MB off the critical path |
| 4.9 | Re-declare the four security headers inside `= /index.html`; fix the dead `\.gz` block; add a CSP | Restores headers on the main document |
| 4.10 | Upgrade `three@0.128.0` (Nov 2021, exact-pinned — will never receive a security fix) | Maintenance; budget ~1 week for `outputEncoding` → `outputColorSpace` and shader-chunk renames |

**Gate:** −87% renders · `dist/models` < 3.5 MB · `index.html` returns all four security
headers.

---

## 10. Phase 5 — Standard training pipeline

**5 days · the long pole**

### 10.1 Architecture — `ml/` at the top level

The feature transform exists **twice** today — notebook cell 17 (`build_features`) and
`backend/app/ml/features.py` — and drifted by one constant. That duplication is the root cause
of C2. This phase removes it.

```
predictive-aircraft-maintenance/
├── ml/                                  # canonical ML home
│   ├── pyproject.toml                   # distribution: rul
│   ├── requirements.lock                # pinned + hashes
│   ├── configs/{base,fd001,fd001_fd003,all}.toml
│   ├── src/rul/
│   │   ├── contract/                    # <<< SINGLE SOURCE OF TRUTH — PURE STDLIB
│   │   │   ├── order.py                 # FEATURE_ORDER, ROLLING_SENSORS, window consts
│   │   │   ├── matrix.py                # build_matrix() rolling transform, ddof=0
│   │   │   ├── zscore.py                # the ONE MAD rule
│   │   │   ├── regimes.py               # classify_regime / nearest centroid
│   │   │   └── errors.py                # ContractError
│   │   ├── config.py  cli.py  pipeline.py
│   │   ├── data/{acquire,schema,loader}.py
│   │   ├── modeling/{estimator,splits,metrics,train}.py
│   │   ├── evaluation/{official,exam}.py
│   │   └── registry/{manifest,promote}.py
│   └── tests/
└── backend/app/ml/
    ├── features.py                      # thin adapter → `from rul.contract import …`
    └── inference.py  model_store.py  attribution.py  fallback.py    # unchanged
```

**Dependency direction inverts: backend → ml.** `rul.contract` imports only stdlib and never
knows the API exists — the same relationship `domain/` already has.

**Verified cheap.** `features.py` has exactly **one** external dependency
(`from ..core.errors import BusinessRuleError`). Its callers are `model_store.py` (3 lazy
imports), `inference.py` (2) and `attribution.py` (1) — **all inside `app/ml`**. The four
modules outside it that import from `app/ml` (`main.py`, `replay.py`, `fleet_service.py`,
`telemetry_service.py`) import `model_store`/`inference`, **not `features`**. Four test files
need one import line changed. `app/ml`'s public surface is untouched.

**Errors.** The contract cannot raise the backend's `BusinessRuleError`, which inverts the
dependency properly:

```python
# ml/src/rul/contract/errors.py
class ContractError(Exception): ...

# backend/app/core/errors.py — unchanged hierarchy
class BusinessRuleError(DomainError): ...      # backend-thrown; keeps status_code=422

# backend/app/ml/inference.py:81
except ContractError:                            # replaces `except BusinessRuleError`
```

HTTP status mapping stays in the backend; the domain error belongs to the contract.

### 10.2 Packaging — one distribution, zero new backend dependencies

`rul`'s runtime deps are `numpy` + `xgboost`, **which the backend already installs**
(`backend/pyproject.toml:18-19`). `scikit-learn` and `matplotlib` go in a `[train]` extra the
backend never pulls. `rul/__init__.py` must not eagerly import training modules, so
`from rul.contract import …` resolves without sklearn present.

| Change | File |
|---|---|
| New `ml/pyproject.toml` — dist `rul`, `packages.find` → `rul*`, deps `numpy,xgboost`, extra `train = [scikit-learn, matplotlib]` | new |
| Add `rul` to `dependencies` | `backend/pyproject.toml:10` |
| **Builder:** `COPY ml/ ./ml/` before `pip install ./ml`. `rul` lands in site-packages, so no runtime `COPY` is needed — same pattern as the backend itself at `Dockerfile:11-14` | `docker/backend/Dockerfile:11-14` |
| **Remove `ml` from the ignore list** (keep `ml/runs`, `ml/notebooks`) | `docker/backend/.dockerignore:6` |
| **CI:** `pip install -e ../ml` **before** `pip install -e ".[dev]"`; add `ml/requirements.lock` to `cache-dependency-path` | `.github/workflows/ci.yml:59-68` |
| **mypy:** extend strict scope to `ml/src/rul/contract` | `ci.yml:76`, `backend/pyproject.toml:43-50` |
| Makefile `train-*` targets install `ml` first | `Makefile` |

### 10.3 Config-driven — TOML via stdlib `tomllib`

Python 3.11 → `tomllib` is stdlib, so configs need **zero new dependencies** and stay diffable.

```toml
# ml/configs/all.toml
name = "all"
datasets = ["FD001", "FD002", "FD003", "FD004"]
rul_cap = 125
seed    = 42

[split]
strategy = "group_shuffle"
test_size = 0.20
groups = "unit"

[features]
rolling_window = 5
rolling_ddof = 0
zscore_by = "regime"
excluded = ["unit", "cycle", "RUL"]

[model]
n_estimators = 1000
learning_rate = 0.05
max_depth = 6
min_child_weight = 3
subsample = 0.8
colsample_bytree = 0.8
reg_lambda = 1.0
early_stopping_rounds = 50

[gates]
max_cv_rmse = 21.0
max_test_rmse = 25.0
max_mae = 20.0
min_r2 = 0.80
```

`config.py` validates with pydantic and **fails on unknown keys**, so `max_depth = "6"` or
`early_stopping_rond = 50` is a hard error rather than a silent default. Hyperparameters stop
being literals buried in notebook cell 10.

### 10.4 Local run registry (replaces "trust the JSON")

Every run writes `runs/<run_id>/`:

| File | Contents |
|---|---|
| `config.json` | Fully **resolved** config (defaults filled, so nothing is implicit) |
| `manifest.json` | git SHA, run_id, UTC timestamp, seed, `python`/`xgboost`/`sklearn`/`numpy` versions, platform, **SHA256 of every input C-MAPSS file**, SHA256 of every produced artifact |
| `metrics.json` | CV folds, official-test per-subset scores, gate results |
| `report.md` | Candidate table, selection decision, feature importances |

Plus an append-only `runs/index.jsonl` — one line per run, greppable, diffable.

This directly addresses §4: the shipped artifact says `has_holdout: false`, so **its only
numbers belong to five other boosters.** The registry ties every metric to the exact artifact it
describes, with the data hash and code SHA that produced it.

**Promotion gate** (`registry/promote.py`) refuses a run unless:

- the `[gates]` thresholds pass
- `manifest.json` carries a git SHA and a complete data manifest
- **the artifact's contract matches `rul.contract`'s `FEATURE_ORDER`** — a promotion-time drift
  check, the strongest structural guard against C2 recurring
- at least two independent seed runs agree within tolerance

Promoted artifacts are staged into `backend/data/ml/<variant>/` by the existing
`scripts/stage_ml_artifacts.py`, so the serving path is unchanged.

### 10.5 Finish the data story

`scripts/fetch-cmapss.sh:37-40` carries SHA256 checksums for **FD001 only**, so `--subset-all`
downloads are **unverified**. And `make fetch-data` invokes it with no arguments
(`Makefile:69`), so it fetches FD001 only — contradicting the README's claim of FD001–FD004.

- Add checksums for all 12 files (train/test/RUL × 4 subsets)
- Add `make fetch-data-all` → `scripts/fetch-cmapss.sh --subset-all`
- `rul download` wraps the same logic, so training never depends on a shell script
- `rul validate` (`data/schema.py`) asserts 26 columns per file, unit ids contiguous from 1,
  cycles starting at 1 and increasing by 1, no NaN, positive RUL, and **row counts matching the
  published NASA counts** — FD001 20,631/13,096 · FD002 53,759/16,796 · FD003 24,720/16,496 ·
  FD004 61,249/25,149 — so a truncated download fails hard rather than training silently

### 10.6 Reproducibility

The repo has **no Python dependency pinning at all** — only `>=` ranges and no lock file. For a
pipeline whose output is a committed artifact, that makes "reproducible" a claim rather than a
fact.

- `ml/requirements.lock` — pinned with hashes
- The manifest records every library version that can change a fitted model
- `PYTHONHASHSEED` and XGBoost's `random_state` both derive from `config.seed`
- One CI assertion: two runs on a 2-engine fixture produce **byte-identical** artifacts

### 10.7 CI — a third job

`ci.yml` currently has `api`, `web`, `images`. **No ML job exists** — which is precisely how a
train/serve skew survived a fully green pipeline.

```yaml
ml:
  steps:
    - pip install -r ml/requirements.lock
    - python -m rul validate --fixture          # fast
    - python -m rul train --config fd001.toml --dry-run
    - pytest ml/tests
    - # contract parity: training path == serving path, bit-identical
    - # artifact validation: contract names its own baselines, feature count matches
# nightly (schedule:): full train --config all.toml, then promote gates
```

`--dry-run` trains two engines and writes nothing, so PRs stay fast while still proving the
pipeline executes.

### 10.8 Fix the model properly

1. **Remove the relative MAD floor at the source.** With one MAD rule in the contract, Phase 1.1
   becomes structural rather than a serving-side patch. Baselines are re-derived and the model
   refit.
2. **A real holdout.** Hold out engines by group, report on the holdout, *then* refit on 100% for
   serving — recording **both** numbers. `has_holdout` becomes `true`, and metric reporting stops
   describing a booster that is not on disk.
3. **Per-row regime z-scoring.** The contract gets a `classify_regime(row_settings)` call per row,
   matching the notebook. This is the fix for FD002/FD004's RMSE 28.3 / 30.2.

### 10.9 Notebook disposition

Cells 13–30 — the code that writes the shipped artifact — have **zero outputs and
`execution_count: null`**, and cell 2 hard-fails outside Colab (`drive.mount('/content/drive')`).
The artifact cannot be traced to code that runs.

Delete `ml/notebooks/Model_training_249.ipynb` once `rul` reproduces its metrics within
0.1 RMSE, and replace it with `ml/docs/MODEL_CARD.md`: dataset, target, feature list, split
strategy, metric definitions, gate thresholds, known limitations (FD002/FD004 not serving-ready
until per-row regime lands), and the serving-path equivalence argument.

This also resolves the stale docs: `docs/08:59` and `docs/01:51` quote the FD001-only
candidate's CV (`17.988 ± 1.487`) while the shipped artifact reports `17.369 ± 0.950`.

### 10.10 What is ported, not reinvented

The notebook's discipline is **reproduced verbatim**: `GroupShuffleSplit`/`GroupKFold` on
`unit`, the `SELECTION_METRIC` declared before any number is seen, the exam-style CV that
rebuilds features on truncated histories, `assert_used_everything()` in the refit, the
`cycle`-exclusion decision and its written rationale, and unit-id namespacing before pooling.

| Step | Est. |
|---|---|
| Extract contract + delete `MAD_REL_FLOOR` | 0.5 d |
| `ml/` skeleton, pyproject, config schema, CLI | 0.5 d |
| `data/` — acquire, schema validation, loader | 0.5 d |
| `modeling/` + `evaluation/` — port cells 14–26 | 1.5 d |
| `registry/` — manifest, gates, promote | 0.5 d |
| Holdout + per-row regime + refit | 1.0 d |
| CI `ml` job + fixture | 0.5 d |
| Delete notebook, write model card | 0.25 d |

**Gate:** a clean clone reproduces artifacts whose metrics match `metrics_*.json` within
0.1 RMSE, and the Phase 1 golden test passes against them.

---

## 11. Phase 6 — Innovations

Ship only after Phases 1–5.

### 11.1 Conformal prediction intervals — highest value

Replace the point estimate with a calibrated interval: **`RUL = 40 ± 12` (90% coverage)**.

Split-conformal calibration wraps the booster and emits a per-prediction interval at a stated
coverage level. This is the most defensible single upgrade for safety-critical maintenance,
because it converts §4's finding into something the operator can see: the decision thresholds
(`MISSION_READY_MIN_RUL = 30`, `Z_HEALTHY_ANCHOR = 1.15`) are **uncalibrated constants sitting
inside the model's own noise band**, producing a measured **3.9% mission-ready
misclassification**. An interval makes that uncertainty visible instead of hiding it behind a
confident integer.

*Requires Phase 5 — a genuine holdout to calibrate against.*

### 11.2 Baseline-drift sentinel

Watch live input statistics against the shipped `regime_baselines` artifact and surface
divergence on `/healthz` and `ModelBadge`. When `s8`'s served variance collapses to zero — as in
C2 — the system **says so**, rather than quietly getting worse.

This catches the **bug class**, not just the bug. It is the "never silently substitute a
heuristic for a model" principle from the README, extended to features.

### 11.3 Time-travel scrubber

Every cycle is already persisted. The replay engine advances forward at 1.2 s, but there is no
way to go **back**. A scrubber over `health_snapshot` + `ml_prediction` lets an operator ask
*"what did we tell the commander three weeks ago, and was it right?"*

Pure frontend, zero new infrastructure, high demonstration value.

### 11.4 Survival / hazard model

The README states the app answers *"which aircraft cannot fly next week, and why?"* — but it
computes a continuous RUL and thresholds it. Train a discrete-time hazard model to answer
**P(unserviceable within k cycles)** directly. Better calibrated for the actual question, and it
degrades gracefully exactly where FD002/FD004 currently fail.

### 11.5 Physics-constrained attribution

C-MAPSS sensors have known degradation directions — HPC pressure falls, turbine temperature
falls, oil pressure rises. Constrain SHAP attributions to respect those monotonicity signs. The
result is an explanation that **cannot lie about physics**: *"HPC health dropped; 71% of that is
`s9` rolling-mean, which physically should fall, and did."* Turns the sensor table into an
argument.

### 11.6 Champion/challenger with automatic rollback

Promote a retrained model to a shadow slot, diff its predictions against the live one per
aircraft, and roll back automatically on regression. This is what makes the Phase 5 retrain safe
to ship, and it makes the "no holdout" problem structurally impossible to repeat.

### 11.7 Continuous aggregates (TimescaleDB)

Swap the window function in `fleet_snapshots` for continuous aggregates refreshed per tick, plus
continuous aggregates for `engine_history`. Turns the most-polled endpoint from O(table) into
O(aircraft × window), and turns the unindexed retention `DELETE` into a native `DROP CHUNK`.

### 11.8 Fleet-level what-if simulator

The console already has spares, agencies, work orders and a +10/+20/+30-cycle lookahead slider.
Wire them into a counterfactual: *"if we defer WO-0142 by 20 cycles, what is projected fleet
availability at day 30?"* Backs the existing `planRows()` with real optimisation rather than a
slider.

### 11.9 Spare inventory optimiser

40 `aircraft_part` rows with criticality and a `spare` table are already loaded. Add a
criticality-weighted EOQ / reorder-point model answering *"which spare do we buy next, and what
does not buying it cost?"*

### 11.10 CP-SAT maintenance scheduling

`domain/rules.py` computes do-by cycles deterministically and the schedule is greedy. Model it as
a constrained optimisation — labour capacity, agency slots, part availability, airframe
mission-readiness — minimising total downtime. The deterministic rules remain as the fallback and
as the constraint bounds.

---

## 12. Cross-cutting: CI must actually gate

Every finding in §3.1 survived a green suite. Close the gates:

- **`frontend/package.json:14`** — `npm test` is `echo "No frontend tests configured."` and exits
  0; `ci.yml:123` reports a green no-op. Add `node:test` suites for the pure logic (`store.js`
  emit/subscribe, `server.js` history cap and `detailSeq` sequencing, `api.js` backoff and retry
  classification). **This would have caught FE3.**
- **`frontend/package.json:15`** claims *"both halves are type-checked in CI"* — false. Either
  correct the claim or add ESLint + `eslint-plugin-react-hooks`; extend `mypy --strict` to
  `app/api`, `app/services`, `app/realtime` (`ci.yml:76` covers 3 of ~10 backend packages, and
  `app/realtime` is where the WS queue-overflow logic lives).
- **`ci.yml:74`** — make `ruff format --check` blocking.
- **Bundle budget** — `vite.config.js:35` sets `chunkSizeWarningLimit: 900` as a *warning*, and
  `reportCompressedSize: false` means the build does not even print gzip sizes. Add a real
  assertion on `dist`.
- **`npm audit` + Dependabot** — `three@0.128.0` is exact-pinned, so it is invisible to audit's
  outdated-range reporting and will never receive a security fix.
- **Container scanning and an image-size gate** — `docker/backend/Dockerfile:14` runs
  `pip install ".[dev]"`, shipping pytest, ruff, mypy and httpx into production: ~80 MB of dead
  weight plus a larger CVE surface than the app needs.

---

## 13. Ship order and effort

```
Phase 0   docs                                  0.25 d
Phase 2   performance                           2.0 d   ┐
Phase 3   database                              2.0 d   ├─ ship together,
Phase 4   frontend                              2.0 d   ┘  independent of ML
Phase 1+5 serving correctness + pipeline       6.0 d
Phase 6   innovations                                     ─
```

**≈ 12 days to a correct, fast, reproducible system.**

### Expected outcome

| Measure | Before | After Phases 0–5 |
|---|---|---|
| FD001 RMSE (as served) | 18.290 | **17.942** |
| RUL bias | +0.700 cycles, optimistic | **≈ 0** |
| `fan` component | pinned at 1.0 forever | **degrades correctly** |
| Model holdout | none | **real, recorded** |
| FD002 / FD004 RMSE | 28.3 / 30.2 (broken) | **per-row regime fixed** |
| Concurrent clients before HTTP 500 | ~10 | **50+, no timeouts** |
| `/healthz` p99 | 64.5 ms | **< 15 ms** |
| Replay drift | +13.6%, unreported | **< 2%, measured and exposed** |
| 3D payload | 9.2 MB | **~1.6 MB** |
| Frontend render waves/s | ~6.7 | **~0.83** |
| Reproducible from a clean clone | **No** | **Yes** |
| Security documentation | 8 claims, 5 false | **Accurate** |

### Risks

| Risk | Mitigation |
|---|---|
| Removing the MAD floor could regress accuracy | The Phase 1 golden test is written **first**, with the measured RMSE 17.942 as reference. If it gets worse, that is a finding to report, not a failure to hide |
| Phase 5 is the schedule risk | The notebook port is the long pole and is genuinely ~5 days. Phases 2–4 are independent — ship them and take the correctness win early |
| Partitioning needs a design decision | It forces re-keying the `ON CONFLICT` target. Flag it rather than silently choosing |
| No holdout until Phase 5 | State plainly in the docs that no reported number describes the artifact on disk |

---

## Appendix A — how the numbers were measured

All measurements were taken on a live stack: `postgres:16-alpine`, the repository's FastAPI
application under uvicorn with the shipped `backend/data/ml/all/` artifact, and FD001 telemetry
from `backend/data/cmapss/`.

### Model accuracy

A harness rebuilt the 32-column feature matrix from raw C-MAPSS under **both** semantics — the
notebook's (`max(mad, 1e-6)`, floored only at MAD = 0) and the backend's
(`max(|median| × 1e-4, 1e-6)`) — and scored both with real XGBoost inference against
`RUL_FD001.txt`.

**Validation of the harness:** under notebook semantics it reproduced the artifact's own
reported figures — **RMSE 17.942, MAE 13.079** — to three decimal places. That agreement is what
licenses the backend-semantics number as a measurement rather than an estimate.

### Latency

40 iterations per endpoint against the live HTTP server (not `TestClient`, which adds its own
overhead), after 5 warm-up requests, with the replay engine running. Concurrency figures come
from `concurrent.futures.ThreadPoolExecutor` at 1/5/10/20/40 clients. Event-loop lag was
measured by hammering `/healthz` — a handler containing no database work, so any latency above
~1 ms is pure blocking — for 400 requests spanning ~8 replay ticks.

### Query plans

`EXPLAIN (ANALYZE, BUFFERS)` against the live migrated and seeded schema, using the exact
statements the repositories emit.

### Reproduction

```bash
# database
docker run -d --name fdt_pg -e POSTGRES_USER=fdt -e POSTGRES_PASSWORD=fdt \
  -e POSTGRES_DB=fdt -p 55432:5432 postgres:16-alpine

# migrate, seed, serve
cd backend
export FDT_DATABASE_URL='postgresql+psycopg://fdt:fdt@127.0.0.1:55432/fdt'
alembic upgrade head && python -m app.seed.run
FDT_ML_VARIANT=all FDT_DEMO_MODE=true python -m uvicorn app.main:app --port 58000

# suite (drops and recreates the public schema)
FDT_TEST_DATABASE_URL="$FDT_DATABASE_URL" python -m pytest -q

# cleanup
docker rm -f fdt_pg
```

---

*Review conducted against commit `f3cd675`. Measured 427/428 tests passing, artifact
`xgboost_all_full.json` (161 trees, 709 engines, 1.12 MB, CV RMSE 17.369).*
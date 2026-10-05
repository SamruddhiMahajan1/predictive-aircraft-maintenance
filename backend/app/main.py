"""FastAPI application factory, lifespan and middleware (docs/02 §2)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.v1.router import api_router
from .core.config import Settings, get_settings
from .core.errors import DomainError
from .core.logging import configure_logging, new_request_id, request_id_var
from .db.session import get_sessionmaker
from .ml import model_store
from .realtime.bus import bus
from .realtime.replay import start_replay, stop_replay
from .realtime.ws import router as ws_router
from .repositories import fleet_repo as repo
from .seed.cmapss import cmapss
from .services.retention import RetentionPruner

log = logging.getLogger(__name__)

# Directories Vite emits into `dist/`: public/ is copied verbatim as `models/`, and
# the bundle plus stylesheets go to `assets/` under content-hashed names. Mounting
# only these, plus `/` for the shell, is what keeps the web build from shadowing an
# API route — see `_mount_frontend`.
WEB_MOUNT_PREFIXES = ("assets", "models")


async def _seed_if_empty(settings: Settings) -> None:
    """Seed the fleet on first boot.

    For deployments nobody can shell into — a Render free service cannot run
    `python -m app.seed.run`, so it depends on this.
    """
    if not settings.seed_on_boot:
        return

    from .seed.run import run

    with get_sessionmaker(settings)() as db:
        needs_fleet = not repo.count_aircraft(db)

    if not needs_fleet:
        log.info("fleet already seeded — skipping boot seed")
        return

    # Imported here, not at module scope: app.seed imports the repositories and the ORM,
    # and ops.py:71 does the same for the HTTP path.
    log.info("fleet is empty and FDT_SEED_ON_BOOT is set — seeding")

    # Blocking work (CSVs, inserts) — keep it off the event loop so the
    # readiness probe and /healthz stay responsive while it runs.
    await asyncio.to_thread(run)
    log.info("boot seed complete")


def _migrate_schema() -> None:
    """Bring the database to `head`, with retries. Render-only.

    Gated on the `RENDER` env var that Render injects (`RENDER=true`), so local
    dev, Compose and the test suite keep running migrations explicitly and are
    unaffected. On Render this used to run in `startCommand` *before* uvicorn
    bound the port — a second interpreter boot plus a cross-region database
    round trip during which the proxy answers every request with 502. Running it
    here, after the port is bound, shrinks the 502 window on every cold start
    and every deploy to the bare interpreter boot.

    Never fatal: a failed migration is logged loudly and serving continues. A
    crash-looping process serves 502 forever; a running one serves degraded
    reads until the next deploy.

    Requires CWD=backend (`alembic.ini` resolves `script_location = alembic`
    relatively) — startCommand's `cd backend` is load-bearing for this too.
    """
    from alembic.config import Config  # noqa: E402

    from alembic import command  # noqa: E402

    for attempt in (1, 2, 3):
        try:
            command.upgrade(Config("alembic.ini"), "head")
            log.info("schema at head (migration pass %d)", attempt)
            return
        except Exception:  # noqa: BLE001 — retried below, then tolerated
            log.warning("migration pass %d failed", attempt, exc_info=True)
            time.sleep(5 * attempt)
    log.error("migrations failed after 3 passes — serving without schema upgrade")


async def _background_init(app: FastAPI, settings: Settings) -> None:
    """Heavy boot work, off the readiness path.

    Runs after the app starts accepting traffic so /healthz answers during a
    cold boot instead of going dark for the 1-3 min a free-tier instance spends
    importing xgboost, parsing C-MAPSS and seeding. Endpoints stay correct while
    it runs: the model serves the deterministic fallback until loaded, the replay
    refuses to start until C-MAPSS is present, and /healthz reports `starting`.
    """
    try:
        if os.getenv("RENDER") == "true":
            await asyncio.to_thread(_migrate_schema)

        # The two heavy reads — xgboost import + booster load + warmup inference,
        # and the C-MAPSS np.loadtxt parse. Both are CPU/file bound, so they go to
        # threads and run concurrently; the loop stays responsive while they finish.
        handle, _ = await asyncio.gather(
            asyncio.to_thread(model_store.load, settings),
            asyncio.to_thread(cmapss.load, settings),
        )
        if handle.ready:
            await asyncio.to_thread(model_store.warmup, handle)
            log.info("model loaded: %s (mae=%s)", handle.version, handle.mae)
        else:
            log.warning("running deterministic fallback: %s", (handle.error or "")[:200])

        # Seed before the replay engine: the engine walks `Aircraft`, so it has to
        # find the fleet already present rather than racing to populate it.
        await _seed_if_empty(settings)
        await start_replay()
    except Exception:  # noqa: BLE001 — a failed init must not kill the process
        log.exception("background startup init failed")
        app.state.startup_error = "startup init failed; serving degraded"
    finally:
        app.state.startup_done = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    log.info("starting %s", settings.app_name)

    # Readiness gate for /healthz: False until the background init finishes.
    # Render's health check hits /healthz, which answers instantly in either
    # state — the service no longer goes dark during a cold boot.
    app.state.startup_done = False
    app.state.startup_error = None

    bus.bind_loop()

    # Per-app, not a module singleton: the pruner's task belongs to this app's event
    # loop, so an instance shared across every app built in the process cannot be
    # stopped safely from a second one.
    pruner = RetentionPruner(settings)
    app.state.retention = pruner
    await pruner.start()

    init_task = asyncio.create_task(_background_init(app, settings), name="startup-init")

    try:
        yield
    finally:
        init_task.cancel()
        with suppress(asyncio.CancelledError):
            await init_task
        await stop_replay()
        await pruner.stop()
        log.info("shutdown complete")


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the Vite build from this process when there is no nginx in front of it.

    `frontend/src/lib/api.js` derives both its REST base and its WebSocket URL from
    `window.location.origin`, so on a deployment with no nginx in front the bundle has
    to be served by this process. Under Compose, nginx proxies `/api` and `/ws` and this
    never runs. Either way the browser only ever talks to one origin, which is also why
    CORS never enters the picture.

    Why three narrow paths and not a `StaticFiles` mount at "/"
    ---------------------------------------------------------
    A mount at "/" matches every path, and Starlette takes the first *complete* match.
    An API request whose path matches but whose method does not only partially matches
    the router, so routing continues into the mount, which matches as a GET, finds no
    such file, and answers 404. The request silently stops being a method error and
    becomes a missing asset.

    So the build is claimed exactly where it lives: `/` for the shell, plus the two
    directories Vite emits. Every other path belongs to the API by construction rather
    than by registration order, so a route added to a router later cannot be shadowed by
    anything here.

    `/assets` holds content-hashed filenames, so StaticFiles' own ETag/Last-Modified
    revalidation is enough and no immutable-cache header is needed. `index.html` must
    never be cached, or a deploy leaves clients requesting asset names that no longer
    exist — the same reason the nginx config marks it no-store.
    """
    dist = settings.web_dist
    index = dist / "index.html"
    # index.html specifically, not merely "the directory exists": an empty or partial
    # dist/ is what a fresh checkout and an interrupted `npm run build` both look like,
    # and serving that would break the app while looking like a routing bug.
    if not index.is_file():
        log.info("no web build at %s — serving the API only", dist)
        return

    @app.get("/", include_in_schema=False)
    async def web_index() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-store, must-revalidate"})

    mounted = []
    for prefix in WEB_MOUNT_PREFIXES:
        directory = dist / prefix
        if directory.is_dir():
            app.mount(
                f"/{prefix}", StaticFiles(directory=directory), name=f"web-{prefix}"
            )
            mounted.append(prefix)

    log.info("serving the web build from %s (/, %s)", dist.resolve(), ", ".join(mounted))


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Fleet Digital Twin predictive-maintenance backend.\n\n"
            "Business rules 19-26 live in `app/domain/rules.py` and are "
            "covered by `tests/unit/test_rules.py`."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,   # explicit allowlist, never "*"
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    # On Render there is no nginx in front — uvicorn serves the Vite bundle
    # directly. Without this every JSON response and every JS/CSS asset goes
    # over the wire uncompressed (~780 KB JS + multi-MB GLBs). Gzip at level 5
    # is the sweet spot for a 512 MB instance: ~70% smaller responses for
    # negligible CPU. StaticFiles mounts below go through middleware too.
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=5)

    @app.middleware("http")
    async def cache_control(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        # Vite emits content-hashed filenames under /assets and versioned binary
        # models under /models — both immutable for a year. Without this every
        # cold visitor re-downloads ~10 MB of JS + GLBs on every navigation,
        # which is the bulk of "takes a lot of time to render".
        if path.startswith("/assets/") or path.startswith("/models/"):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        elif path in ("/healthz", "/readyz"):
            # Keep-alive bots hit these every 5 min — never let a CDN cache them.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code, "message": exc.message,
                    "request_id": request_id_var.get(), "detail": exc.detail,
                }
            },
        )

    app.include_router(api_router)
    app.include_router(ws_router)

    # No static mount under Compose: the 3D assets are frontend build output and are
    # served by nginx (docker/frontend/nginx.conf), which also reverse-proxies /api and
    # /ws here. Where there is no nginx, this process serves the bundle instead.
    _mount_frontend(app, settings)

    return app


app = create_app()
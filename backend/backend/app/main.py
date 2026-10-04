"""FastAPI application factory, lifespan and middleware (docs/02 §2)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.v1.router import api_router
from .core.config import get_settings
from .core.errors import DomainError
from .core.logging import configure_logging, new_request_id, request_id_var
from .ml import model_store
from .realtime.bus import bus
from .realtime.replay import start_replay, stop_replay
from .realtime.ws import router as ws_router
from .seed.cmapss import cmapss

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)

    log.info("starting %s", settings.app_name)

    # ML artifact loaded once, before traffic is accepted (docs/08 §5)
    handle = model_store.load(settings)
    if handle.ready:
        model_store.warmup(handle)
        log.info("model loaded: %s (mae=%s)", handle.version, handle.mae)
    else:
        log.warning("running deterministic fallback: %s", (handle.error or "")[:200])

    bus.bind_loop()
    cmapss.load(settings)
    await start_replay()

    try:
        yield
    finally:
        await stop_replay()
        log.info("shutdown complete")


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
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

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

    settings.static_models_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/models", StaticFiles(directory=settings.static_models_dir), name="models")

    return app


app = create_app()
"""WebSocket /ws/fleet — spec item 42 (docs/09 §3)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..core.config import get_settings
from ..core.errors import AuthenticationError
from ..core.security import decode_ws_token
from ..db.session import get_sessionmaker
from ..models.fleet import Aircraft
from .bus import bus
from .events import ClientMessage, connection_ready, pong

log = logging.getLogger(__name__)
router = APIRouter()

WS_UNAUTHORIZED = 4401
WS_BAD_ORIGIN = 4408
WS_INTERNAL = 1011


@router.websocket("/ws/fleet")
async def ws_fleet(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    aircraft: str | None = Query(default=None),
) -> None:
    settings = get_settings()

    origin = websocket.headers.get("origin")
    if origin and settings.cors_origins and origin not in settings.cors_origins:
        await websocket.close(code=WS_BAD_ORIGIN, reason="origin not allowed")
        return

    try:
        decode_ws_token(token, settings)
    except AuthenticationError:
        await websocket.close(code=WS_UNAUTHORIZED, reason="unauthorized")
        return

    await websocket.accept()
    queue = bus.subscribe()
    filters: set[str] = set(filter(a.strip() for a in aircraft.split(","))) if aircraft else set()

    session = get_sessionmaker(settings)
    with session() as db:
        count = len(list(db.scalars(select(Aircraft.id))))
    await websocket.send_json(
        connection_ready(count, settings.demo_mode, settings.demo_tick_seconds).envelope(0)
    )

    async def drain() -> None:
        seq = 1
        while True:
            event = await queue.get()
            if filters and event.payload.get("aircraft") not in filters:
                continue
            await websocket.send_json(event.envelope(seq))
            seq += 1

    pump = asyncio.create_task(drain())
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                msg = ClientMessage(**raw)
            except Exception:  # noqa: BLE001
                continue
            if msg.type == "ping":
                await websocket.send_json(pong().envelope())
            elif msg.type == "subscribe":
                filters = set(msg.aircraft)
            elif msg.type == "unsubscribe":
                filters -= set(msg.aircraft)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("WebSocket error")
        with suppress(RuntimeError):
            await websocket.close(code=WS_INTERNAL)
    finally:
        with suppress(asyncio.CancelledError):
            pump.cancel()
        bus.unsubscribe(queue)
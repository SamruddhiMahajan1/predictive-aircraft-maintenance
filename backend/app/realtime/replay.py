"""Replay engine — one C-MAPSS cycle per aircraft every 1.2 s (docs/09 §1)."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from ..core.config import Settings, get_settings
from ..core.logging import Timer
from ..db.session import get_sessionmaker
from ..domain.health import EmaState, engine_health_from_rul
from ..domain.rules import do_by_cycle, risk_level
from ..ml import inference
from ..models.alert import Alert
from ..models.fleet import Aircraft
from ..repositories import telemetry_repo as telemetry
from ..seed.cmapss import cmapss
from .bus import bus
from .events import alert_raised, cycle_tick, health_updated

log = logging.getLogger(__name__)

EMA: dict[int, EmaState] = {}


@dataclass(slots=True)
class TickEvent:
    """One aircraft's result from one tick, carried out of the blocking section.

    The worker thread cannot `await`, so it returns these and the event loop publishes
    them. A dataclass rather than a tuple because the fields are read by name in three
    places and a 7-tuple with `event[3]` in it is how the previous version's alert
    logic came to be reading the wrong field.
    """

    aircraft_id: int
    code: str
    previous_risk: str
    cycle: int
    health: float
    risk: str
    prediction: dict[str, Any]
    do_by: int
    telemetry_rows: list[dict[str, Any]]


class ReplayEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.task: asyncio.Task | None = None
        self.paused = False
        self.tick_count = 0
        self.running = False
        # Serialises the replay loop against the manual `/demo/tick` endpoint. Both
        # advance the same aircraft, and neither took a lock, so a manual tick landing
        # mid-loop advanced an engine twice and wrote one of the two rows away.
        self._tick_lock = asyncio.Lock()
        # Degradation reporting. `interval_seconds` in /demo/status is what the
        # operator configured, not what the engine achieved; drift was real (+13.6%
        # measured) and invisible.
        self.last_tick_ms: float | None = None
        self.achieved_interval_seconds: float | None = None
        self.drift_pct: float | None = None
        self.consecutive_failures: int = 0
        self._last_tick_started: float | None = None

    def _record_failure(self, exc: BaseException) -> None:
        """Log the first few failures, then throttle.

        The previous behaviour logged every 50th tick's exception, so a tick failing
        every time was near-silent for the first ~60 seconds -- the opposite of what
        `services/retention.py` warns about ("a wall of exceptions" hides the signal).
        Logging the first N makes an onset obvious and a persistent fault visible in
        aggregate rather than 8.3 times a minute.
        """
        self.consecutive_failures += 1
        if self.consecutive_failures <= 5 or self.consecutive_failures % 50 == 0:
            log.exception("replay tick failed (failure #%d)", self.consecutive_failures)

    def _record_success(self, elapsed_ms: float, started: float) -> None:
        if self.consecutive_failures:
            log.info("replay recovered after %d consecutive failures", self.consecutive_failures)
        self.consecutive_failures = 0
        self.last_tick_ms = round(elapsed_ms, 2)
        if self._last_tick_started is not None:
            achieved = started - self._last_tick_started
            self.achieved_interval_seconds = round(achieved, 4)
            target = self.settings.demo_tick_seconds
            if target > 0:
                self.drift_pct = round((achieved - target) / target * 100.0, 2)
        self._last_tick_started = started

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def start(self) -> None:
        if not self.settings.demo_mode or not cmapss.loaded:
            log.info(
                "replay engine not started (demo_mode=%s, cmapss=%s)",
                self.settings.demo_mode,
                cmapss.loaded,
            )
            return
        self.running = True
        self.task = asyncio.create_task(self._loop(), name="replay")

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def tick_once(self) -> None:
        if not cmapss.loaded:
            log.warning("tick requested but C-MAPSS is not loaded — nothing to advance")
            return
        # `tick_once` is reachable from POST /demo/tick, and the replay loop may be
        # mid-tick at the same moment. Without this lock two passes walk the same
        # aircraft concurrently: both read `current_cycle`, both advance, and one of
        # the two writes is silently lost.
        async with self._tick_lock:
            await self._tick()

    async def _loop(self) -> None:
        while self.running:
            started = time.perf_counter()
            if not self.paused:
                try:
                    async with self._tick_lock:
                        await self._tick()
                except Exception as exc:  # noqa: BLE001 — a bad tick must not kill the loop
                    self._record_failure(exc)
            # Schedule against the previous tick's START, not the end. Sleeping the
            # configured interval after the work finishes makes the achieved period
            # (interval + tick duration) drift above the configured one by exactly the
            # time the tick takes — measured at 1.364 s against a configured 1.2 s,
            # a 13.6% error that no endpoint reported.
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.0, self.settings.demo_tick_seconds - elapsed))

    # ── one fleet pass ────────────────────────────────────────────────────────
    async def _tick(self) -> None:
        if not cmapss.loaded:
            return
        started = time.perf_counter()
        with Timer() as t:
            # The whole pass is synchronous psycopg work. Running it inline blocked
            # the event loop for the duration of 8 aircraft x ~9 serialised round
            # trips per tick -- measured at up to 104 ms of pure stall, which showed
            # up as `/healthz` p99 of 64 ms on a handler that does no database work
            # at all, and 17.9% of wall time spent blocked. On a localhost database.
            # `render.yaml` describes a cross-region one, where the same code path
            # becomes multi-second stalls during which the loop cannot drain
            # WebSocket queues or answer the liveness probe.
            events = await asyncio.to_thread(self._tick_sync)
        self._record_success(t.ms, started)
        if self.tick_count % 50 == 0:
            log.info("replay tick %d in %sms", self.tick_count, t.ms)
        # Publishing stays on the event loop -- `bus.publish` is async. Doing it on the
        # worker thread would require run_coroutine_threadsafe and would publish
        # concurrently with whatever else the loop is doing.
        if events:
            now = datetime.now(UTC)
            await bus.publish(cycle_tick(max(e.cycle for e in events)))
            for event in events:
                await bus.publish(
                    health_updated(
                        event.code,
                        event.aircraft_id,
                        "engine",
                        event.health,
                        event.risk,
                        event.prediction["rul"],
                        event.cycle,
                        model=event.prediction.get("model"),
                    )
                )
                if event.risk != event.previous_risk and event.risk != "healthy":
                    await self._raise_alert(event, now)

    def _tick_sync(self) -> list[TickEvent]:
        """One fleet pass, entirely blocking. Runs on a worker thread.

        A single transaction for the whole fleet rather than one per aircraft: eight
        separate COMMITs means eight fsyncs per tick, ~6.7/s at the configured interval,
        none of which any reader needs to see individually. A tick is only meaningful as
        a whole -- a partially-applied tick advances some engines and not others -- so
        committing it atomically is both faster and more correct than the per-aircraft
        commits it replaces.
        """
        session = get_sessionmaker(self.settings)
        now = datetime.now(UTC)
        with session() as db:
            engine_part = telemetry.engine_part(db)
            events: list[TickEvent] = []
            active = db.scalars(
                select(Aircraft).where(Aircraft.is_active.is_(True)).order_by(Aircraft.id)
            )
            for row_obj in active:
                event = self._prepare(row_obj)
                if event is None:
                    continue
                telemetry.write_engine_prediction(
                    db,
                    aircraft=row_obj,
                    part=engine_part,
                    prediction=event.prediction,
                    health=event.health,
                    risk=event.risk,
                    cycle=event.cycle,
                    do_by=event.do_by,
                    source="cmapss",
                    cmapss_unit_id=row_obj.cmapss_unit_id,
                    telemetry_rows=event.telemetry_rows,
                    recorded_at=now,
                )
                row_obj.updated_at = now
                events.append(event)
            db.commit()
        return events

    def _prepare(self, aircraft: Aircraft) -> TickEvent | None:
        """Predict one aircraft and assemble its tick payload. No database access.

        Inference is CPU-bound (XGBoost), so it runs on the same worker thread as the
        rest of the pass rather than being awaited per aircraft on the event loop.
        """
        unit = aircraft.cmapss_unit_id
        next_cycle = aircraft.current_cycle + 1
        row = cmapss.row(unit, next_cycle)

        if row is None:  # wrap at end of life
            next_cycle = self._resume_cycle(unit)
            row = cmapss.row(unit, next_cycle)
            aircraft.current_cycle = next_cycle
            EMA[aircraft.id] = EmaState.empty()  # reset smoothing (docs/09 §1.2)
            log.info("%s wrapped to cycle %d", aircraft.code, next_cycle)

        window = cmapss.window(unit, next_cycle, self.settings.ml_window)
        prediction = inference.predict(window, current_cycle=next_cycle)

        raw_health = engine_health_from_rul(prediction["rul"])
        state = EMA.setdefault(aircraft.id, EmaState.empty())
        health = round(state.update("engine", raw_health), 3)
        risk = risk_level(health)
        return TickEvent(
            aircraft_id=aircraft.id,
            code=aircraft.code,
            previous_risk=aircraft.risk_level,
            cycle=next_cycle,
            health=health,
            risk=risk,
            prediction=prediction,
            do_by=do_by_cycle(prediction["rul"], next_cycle, risk),
            telemetry_rows=[{"cycle": next_cycle, **row}],
        )

    def _resume_cycle(self, unit: Any) -> int:
        """Where a wrapped engine restarts, so the feature window is already full.

        Wrapping to cycle 1 gave `cmapss.window` a single row, and `build_window`
        rejects anything under five cycles — so the first four ticks after every wrap
        were answered from `rul = 125 - cycle`. That is not a rounding artefact: the
        model said 118 at cycle 5 while the fallback had just been claiming 121, and
        the degradation was invisible because a healthy engine's linear guess is
        roughly right. Each wrap therefore produced a visible step *and* a silent
        fallback, once per engine lifetime.

        Restarting at `ml_window` skips the first 29 cycles of an engine's life —
        the least informative ones, all healthy and well above the RUL cap — and
        buys a complete window, so every prediction is model-backed. The unit is
        still walked to genuine end of life before wrapping.
        """
        target = max(1, self.settings.ml_window)
        if cmapss.row(unit, target) is not None:
            return target
        # Pathological unit shorter than the window; fall back to the old behaviour
        # and let build_window report the short window rather than inventing data.
        return 1

    async def _raise_alert(self, event: TickEvent, now: datetime) -> None:
        """One live alert per aircraft+part (uq_alert_live).

        Runs on the event loop, so its database work is offloaded rather than blocking
        -- an alert fires on the tick that first crosses into watch or critical, which
        is precisely when other requests are arriving.
        """
        session = get_sessionmaker(self.settings)

        def _write() -> dict[str, Any]:
            with session() as db:
                part = telemetry.engine_part(db)
                existing = db.scalar(
                    select(Alert).where(
                        Alert.aircraft_id == event.aircraft_id,
                        Alert.part_id == part.id,
                        Alert.acknowledged.is_(False),
                    )
                )
                message = (
                    f"Engine health {event.health:.2f} — RUL {event.prediction['rul']}. "
                    f"{'Replace now' if event.risk == 'critical' else 'Plan inspection'}."
                )
                if existing:
                    existing.level = event.risk
                    existing.message = message
                    existing.health = event.health
                    existing.cycle = event.cycle
                else:
                    existing = Alert(
                        aircraft_id=event.aircraft_id,
                        part_id=part.id,
                        level=event.risk,
                        message=message,
                        cycle=event.cycle,
                        health=event.health,
                        created_at=now,
                    )
                    db.add(existing)
                db.commit()
                return {
                    "id": existing.id,
                    "aircraft": event.code,
                    "aircraft_id": event.aircraft_id,
                    "part": "engine",
                    "level": event.risk,
                    "message": message,
                    "health": event.health,
                    "rul": event.prediction["rul"],
                    "cycle": event.cycle,
                }

        await bus.publish(alert_raised(await asyncio.to_thread(_write)))

    # ── controls ──────────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "tick": self.tick_count,
            # The configured period. Read `achieved_interval_seconds` and `drift_pct`
            # for what the engine is actually doing: this number is what an operator
            # set, not what the fleet experienced, and the two differed by 13.6% with
            # nothing anywhere reporting it.
            "interval_seconds": self.settings.demo_tick_seconds,
            "last_tick_ms": self.last_tick_ms,
            "achieved_interval_seconds": self.achieved_interval_seconds,
            "drift_pct": self.drift_pct,
            "consecutive_failures": self.consecutive_failures,
            **cmapss.describe(),
            "subscribers": bus.subscriber_count,
            "dropped_events": bus.dropped,
        }

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False


engine = ReplayEngine()


async def start_replay() -> None:
    await engine.start()


async def stop_replay() -> None:
    await engine.stop()

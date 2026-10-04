"""Replay engine — one C-MAPSS cycle per aircraft every 1.2 s (docs/09 §1)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..core.config import Settings, get_settings
from ..core.logging import Timer
from ..db.session import get_sessionmaker
from ..domain.health import EmaState, engine_health_from_rul
from ..domain.rules import PART_ORDER, do_by_cycle, risk_level
from ..ml import inference
from ..models.alert import Alert
from ..models.fleet import Aircraft, AircraftPart, Part
from ..models.telemetry import ComponentHealth, EngineTelemetry, HealthSnapshot, MlPrediction
from ..seed.cmapss import cmapss
from .bus import bus
from .events import alert_raised, cycle_tick, health_updated

log = logging.getLogger(__name__)

EMA: dict[int, EmaState] = {}


class ReplayEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.task: asyncio.Task | None = None
        self.paused = False
        self.tick_count = 0
        self.running = False

    # ── lifecycle ─────────────────────────────────────────────────────────────
    async def start(self) -> None:
        if not self.settings.demo_mode or not cmapss.loaded:
            log.info("replay engine not started (demo_mode=%s, cmapss=%s)",
                     self.settings.demo_mode, cmapss.loaded)
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
        await self._tick()

    async def _loop(self) -> None:
        while self.running:
            if not self.paused:
                try:
                    await self._tick()
                except Exception:  # noqa: BLE001 — a bad tick must not kill the loop
                    log.exception("replay tick failed")
            await asyncio.sleep(self.settings.demo_tick_seconds)

    # ── one fleet pass ────────────────────────────────────────────────────────
    async def _tick(self) -> None:
        if not cmapss.loaded:
            return
        with Timer() as t:
            for aircraft in self._active():
                await self._advance(aircraft)
        self.tick_count += 1
        if self.tick_count % 50 == 0:
            log.info("replay tick %d in %sms", self.tick_count, t.ms)

    def _active(self) -> list[Aircraft]:
        session = get_sessionmaker(self.settings)
        with session() as db:
            return list(db.scalars(select(Aircraft).where(Aircraft.is_active.is_(True))))

    async def _advance(self, aircraft: Aircraft) -> None:
        unit = aircraft.cmapss_unit_id
        next_cycle = aircraft.current_cycle + 1
        row = cmapss.row(unit, next_cycle)

        if row is None:                                   # wrap at end of life
            next_cycle = 1
            row = cmapss.row(unit, 1)
            aircraft.current_cycle = 1
            EMA[aircraft.id] = EmaState.empty()          # reset smoothing (docs/09 §1.2)
            log.info("%s wrapped to cycle 1", aircraft.code)

        window = cmapss.window(unit, next_cycle, self.settings.ml_window)
        prediction = await asyncio.to_thread(inference.predict, window, current_cycle=next_cycle)

        raw_health = engine_health_from_rul(prediction["rul"])
        state = EMA.setdefault(aircraft.id, EmaState.empty())
        health = round(state.update("engine", raw_health), 3)
        risk = risk_level(health)

        previous_risk = aircraft.risk_level
        now = datetime.now(UTC)

        session = get_sessionmaker(self.settings)
        with session() as db:                              # ONE transaction per aircraft-tick
            row_obj = db.get(Aircraft, aircraft.id)
            engine_part = db.scalar(
                select(Part).where(Part.code == "engine")
            )

            db.execute(
                pg_insert(EngineTelemetry)
                .values(
                    aircraft_id=row_obj.id, cycle=next_cycle, cmapss_unit_id=unit,
                    setting_1=row["settings"]["setting_1"],
                    setting_2=row["settings"]["setting_2"],
                    setting_3=row["settings"]["setting_3"],
                    # the regime the prediction was actually made in, not a literal 0:
                    # six-regime data would silently record every cycle as regime 0
                    regime=int(prediction["model"].get("regime") or 0),
                    source="cmapss", recorded_at=now,
                    **row["sensors"],
                )
                .on_conflict_do_update(
                    index_elements=[EngineTelemetry.aircraft_id, EngineTelemetry.cycle],
                    set_={"recorded_at": now},
                )
            )
            db.execute(
                pg_insert(ComponentHealth)
                .values(
                    aircraft_id=row_obj.id, cycle=next_cycle,
                    fan=prediction["component_health"]["fan"],
                    hpc=prediction["component_health"]["hpc"],
                    hpt=prediction["component_health"]["hpt"],
                    lpt=prediction["component_health"]["lpt"],
                    recorded_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[ComponentHealth.aircraft_id, ComponentHealth.cycle],
                    set_={"fan": prediction["component_health"]["fan"],
                          "hpc": prediction["component_health"]["hpc"],
                          "hpt": prediction["component_health"]["hpt"],
                          "lpt": prediction["component_health"]["lpt"]},
                )
            )
            db.execute(
                pg_insert(MlPrediction)
                .values(
                    aircraft_id=row_obj.id, cycle=next_cycle, rul=prediction["rul"],
                    fan=prediction["component_health"]["fan"],
                    hpc=prediction["component_health"]["hpc"],
                    hpt=prediction["component_health"]["hpt"],
                    lpt=prediction["component_health"]["lpt"],
                    top_sensors=prediction["top_sensors"],
                    deviation=prediction["deviation"],
                    model_version=prediction["model"]["version"],
                    latency_ms=prediction["latency_ms"], created_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[MlPrediction.aircraft_id, MlPrediction.cycle],
                    set_={"rul": prediction["rul"], "latency_ms": prediction["latency_ms"]},
                )
            )
            db.execute(
                pg_insert(HealthSnapshot)
                .values(
                    aircraft_id=row_obj.id, part_id=engine_part.id, cycle=next_cycle,
                    health=health, risk_level=risk, recorded_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[
                        HealthSnapshot.aircraft_id,
                        HealthSnapshot.part_id,
                        HealthSnapshot.cycle,
                    ],
                    set_={"health": health, "risk_level": risk},
                )
            )

            db.execute(
                AircraftPart.__table__.update()
                .where(AircraftPart.aircraft_id == row_obj.id,
                       AircraftPart.part_id == engine_part.id)
                .values(health=health, risk_level=risk, rul=prediction["rul"],
                        do_by_cycle=do_by_cycle(prediction["rul"], next_cycle, risk),
                        worst_component=prediction["weakest_component"],
                        updated_at=now)
            )
            row_obj.current_cycle = next_cycle
            row_obj.rul = prediction["rul"]
            row_obj.updated_at = now
            db.commit()

        await bus.publish(cycle_tick(next_cycle))
        await bus.publish(health_updated(
            aircraft.code, aircraft.id, "engine", health, risk, prediction["rul"], next_cycle
        ))

        if risk != previous_risk and risk != "healthy":
            await self._raise_alert(aircraft, risk, health, prediction["rul"],
                                    next_cycle, now)

    async def _raise_alert(self, aircraft: Aircraft, risk: str, health: float,
                           rul: int, cycle: int, now: datetime) -> None:
        """One live alert per aircraft+part (uq_alert_live)."""
        session = get_sessionmaker(self.settings)
        with session() as db:
            part = db.scalar(select(Part).where(Part.code == "engine"))
            existing = db.scalar(
                select(Alert).where(
                    Alert.aircraft_id == aircraft.id,
                    Alert.part_id == part.id,
                    Alert.acknowledged.is_(False),
                )
            )
            message = (
                f"Engine health {health:.2f} — RUL {rul}. "
                f"{'Replace now' if risk == 'critical' else 'Plan inspection'}."
            )
            if existing:
                existing.level = risk
                existing.message = message
                existing.health = health
                existing.cycle = cycle
            else:
                existing = Alert(
                    aircraft_id=aircraft.id, part_id=part.id, level=risk,
                    message=message, cycle=cycle, health=health, created_at=now,
                )
                db.add(existing)
            db.commit()
            payload = {
                "id": existing.id, "aircraft": aircraft.code, "aircraft_id": aircraft.id,
                "part": "engine", "level": risk, "message": message,
                "health": health, "rul": rul, "cycle": cycle,
            }
        await bus.publish(alert_raised(payload))

    # ── controls ──────────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "tick": self.tick_count,
            "interval_seconds": self.settings.demo_tick_seconds,
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


PART_SEQUENCE = PART_ORDER
TODAY = date.today()
"""Telemetry ingest (spec 40) and internal ML predict (spec 41)."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...core.config import get_settings
from ...core.errors import NotFoundError
from ...domain.health import EmaState, engine_health_from_rul
from ...domain.rules import do_by_cycle, risk_level
from ...ml import inference
from ...models.alert import Alert
from ...models.fleet import AircraftPart, Part
from ...models.telemetry import ComponentHealth, EngineTelemetry, HealthSnapshot, MlPrediction
from ...realtime.bus import bus
from ...realtime.events import alert_raised, cycle_tick, health_updated
from ...repositories import fleet_repo as repo
from ...schemas.ops import PredictRequest, PredictResponse, TelemetryAccepted, TelemetryBatch
from ..deps import CanMutate, DbSession

router = APIRouter(tags=["telemetry"], prefix="/api/v1")


@router.post("/telemetry", response_model=TelemetryAccepted, status_code=202)
def ingest_telemetry(db: DbSession, user: CanMutate, batch: TelemetryBatch):
    """One aircraft per batch (spec 40). Upserts, infers, persists, publishes."""
    aircraft = repo.get_aircraft(db, batch.aircraft)
    if aircraft is None:
        raise NotFoundError(f"Aircraft {batch.aircraft} not found")
    engine_part = repo.get_part(db, "engine")
    now = datetime.now(UTC)
    last_cycle = batch.rows[-1].cycle
    s6_median = get_settings().s6_median_fd001

    # spec 45 lists 14 sensors; the model also needs s6 (docs/01 §3)
    rows = []
    for r in batch.rows:
        sensors = dict(r.sensors)
        if sensors.get("s6") is None:
            sensors["s6"] = s6_median
        rows.append({"cycle": r.cycle,
                     "settings": r.settings.model_dump(),
                     "sensors": sensors})
    prediction = inference.predict(rows, current_cycle=last_cycle)
    health = engine_health_from_rul(prediction["rul"])
    risk = risk_level(health)

    for i, r in enumerate(batch.rows):
        db.execute(
            pg_insert(EngineTelemetry)
            .values(
                aircraft_id=aircraft.id, cycle=r.cycle,
                cmapss_unit_id=aircraft.cmapss_unit_id,
                setting_1=r.settings.setting_1, setting_2=r.settings.setting_2,
                setting_3=r.settings.setting_3,
                regime=int(prediction["model"].get("regime") or 0), source="api",
                recorded_at=now, **rows[i]["sensors"],
            )
            .on_conflict_do_update(
                index_elements=[EngineTelemetry.aircraft_id, EngineTelemetry.cycle],
                set_={"recorded_at": now},
            )
        )
    db.execute(
        pg_insert(ComponentHealth)
        .values(aircraft_id=aircraft.id, cycle=last_cycle,
                fan=prediction["component_health"]["fan"],
                hpc=prediction["component_health"]["hpc"],
                hpt=prediction["component_health"]["hpt"],
                lpt=prediction["component_health"]["lpt"], recorded_at=now)
        .on_conflict_do_update(
            index_elements=[ComponentHealth.aircraft_id, ComponentHealth.cycle],
            set_=dict(prediction["component_health"]),
        )
    )
    db.execute(
        pg_insert(MlPrediction)
        .values(aircraft_id=aircraft.id, cycle=last_cycle, rul=prediction["rul"],
                fan=prediction["component_health"]["fan"],
                hpc=prediction["component_health"]["hpc"],
                hpt=prediction["component_health"]["hpt"],
                lpt=prediction["component_health"]["lpt"],
                top_sensors=prediction["top_sensors"], deviation=prediction["deviation"],
                model_version=prediction["model"]["version"],
                latency_ms=prediction["latency_ms"], created_at=now)
        .on_conflict_do_update(
            index_elements=[MlPrediction.aircraft_id, MlPrediction.cycle],
            set_={"rul": prediction["rul"]},
        )
    )
    db.execute(
        pg_insert(HealthSnapshot)
        .values(aircraft_id=aircraft.id, part_id=engine_part.id, cycle=last_cycle,
                health=health, risk_level=risk, recorded_at=now)
        .on_conflict_do_update(
            index_elements=[HealthSnapshot.aircraft_id, HealthSnapshot.part_id,
                            HealthSnapshot.cycle],
            set_={"health": health, "risk_level": risk},
        )
    )
    db.execute(
        AircraftPart.__table__.update()
        .where(AircraftPart.aircraft_id == aircraft.id,
               AircraftPart.part_id == engine_part.id)
        .values(health=health, risk_level=risk, rul=prediction["rul"],
                do_by_cycle=do_by_cycle(prediction["rul"], last_cycle, risk),
                worst_component=prediction["weakest_component"], updated_at=now)
    )
    aircraft.current_cycle = last_cycle
    aircraft.rul = prediction["rul"]

    alerts_raised = 0
    alert_id = None
    if risk != "healthy":
        existing = (
            db.query(Alert)
            .filter(
                Alert.aircraft_id == aircraft.id,
                Alert.part_id == engine_part.id,
                Alert.acknowledged.is_(False),
            )
            .one_or_none()
        )
        message = f"Engine health {health:.2f} — RUL {prediction['rul']}."
        if existing:
            existing.level, existing.message = risk, message
            existing.health, existing.cycle = health, last_cycle
        else:
            alert = Alert(aircraft_id=aircraft.id, part_id=engine_part.id, level=risk,
                          message=message, cycle=last_cycle, health=health, created_at=now)
            db.add(alert)
            db.flush()
            alert_id = alert.id
            alerts_raised = 1
    db.commit()

    bus.publish_soon(cycle_tick(last_cycle))
    bus.publish_soon(health_updated(
        aircraft.code, aircraft.id, "engine", health, risk, prediction["rul"], last_cycle))
    if alerts_raised:
        bus.publish_soon(alert_raised({
            "id": alert_id, "aircraft": aircraft.code, "aircraft_id": aircraft.id,
            "part": "engine", "level": risk,
            "message": f"Engine health {health:.2f} — RUL {prediction['rul']}.",
            "health": health, "rul": prediction["rul"], "cycle": last_cycle,
        }))

    return {
        "aircraft": aircraft.code, "rows_written": len(batch.rows),
        "current_cycle": last_cycle, "rul": prediction["rul"], "health": health,
        "risk": risk, "components": prediction["component_health"],
        "top_sensors": prediction["top_sensors"],
        "model": prediction["model"]["version"],
        "alerts_raised": alerts_raised, "latency_ms": prediction["latency_ms"],
    }


@router.post("/internal/ml/predict", response_model=PredictResponse)
def predict(db: DbSession, user: CanMutate, payload: PredictRequest):
    rows = [
        {"cycle": r.cycle, "settings": r.settings.model_dump() if r.settings else {},
         "sensors": r.sensors}
        for r in payload.window
    ]
    result = inference.predict(rows, regime=payload.regime, subset=payload.subset,
                               current_cycle=rows[-1].get("cycle"))
    result["aircraft"] = payload.aircraft
    if payload.persist and payload.aircraft:
        aircraft = repo.get_aircraft(db, payload.aircraft)
        if aircraft is not None:
            db.execute(
                pg_insert(MlPrediction)
                .values(aircraft_id=aircraft.id, cycle=result["cycle"], rul=result["rul"],
                        fan=result["component_health"]["fan"],
                        hpc=result["component_health"]["hpc"],
                        hpt=result["component_health"]["hpt"],
                        lpt=result["component_health"]["lpt"],
                        top_sensors=result["top_sensors"], deviation=result["deviation"],
                        model_version=result["model"]["version"],
                        latency_ms=result["latency_ms"], created_at=datetime.now(UTC))
                .on_conflict_do_update(
                    index_elements=[MlPrediction.aircraft_id, MlPrediction.cycle],
                    set_={"rul": result["rul"]},
                )
            )
            db.commit()
    return result


__all__ = ["router", "EmaState", "Part"]
"""Data access. No business logic, no rule evaluation — load and persist only.

The fixed query count per endpoint is deliberate: the N+1 guard asserted by
tests/performance/test_budgets.py (docs/11 §5.3).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session, selectinload

from ..models.alert import Alert
from ..models.fleet import Aircraft, AircraftPart, Part
from ..models.maintenance import (
    Agency,
    AgencyBooking,
    Spare,
    StockMovement,
    WorkOrder,
)
from ..models.reference import FlightOpsMonthly, TechnicalRecord
from ..models.telemetry import ComponentHealth, HealthSnapshot, MlPrediction


# ── fleet ──────────────────────────────────────────────────────────────────────
def list_aircraft(db: Session) -> list[Aircraft]:
    return list(db.scalars(select(Aircraft).order_by(Aircraft.code)))


def get_aircraft(db: Session, code_or_id: str | int) -> Aircraft | None:
    if isinstance(code_or_id, int) or str(code_or_id).isdigit():
        return db.get(Aircraft, int(code_or_id))
    return db.scalar(select(Aircraft).where(Aircraft.code == code_or_id))


def get_part(db: Session, code: str) -> Part | None:
    """By part CODE ('engine', 'hyd', …) — not the surrogate id."""
    return db.scalar(select(Part).where(Part.code == code))


def get_part_by_id(db: Session, part_id: int) -> Part | None:
    """By surrogate id, for rows that carry only the foreign key."""
    return db.get(Part, part_id)


def list_parts(db: Session) -> list[Part]:
    return list(db.scalars(select(Part).order_by(Part.sort_order)))


def parts_for_aircraft(db: Session, aircraft_id: int) -> list[AircraftPart]:
    return list(
        db.scalars(
            select(AircraftPart)
            .join(Part, Part.id == AircraftPart.part_id)
            .where(AircraftPart.aircraft_id == aircraft_id)
            .options(selectinload(AircraftPart.part))
            .order_by(Part.sort_order)
        )
    )


def all_parts_by_aircraft(db: Session) -> dict[int, list[AircraftPart]]:
    """Every aircraft's parts in ONE query — the N+1 guard for heatmap/schedule.

    `selectinload` pulls the five `Part` rows in the same round trip: without it
    every `row.part.code` access lazy-loads, which is a per-row query storm the
    first time a session touches the fleet.
    """
    grouped: dict[int, list[AircraftPart]] = {}
    rows = db.execute(
        select(AircraftPart)
        .join(Part, Part.id == AircraftPart.part_id)
        .options(selectinload(AircraftPart.part))
        .order_by(AircraftPart.aircraft_id, Part.sort_order)
    ).scalars()
    for row in rows:
        grouped.setdefault(row.aircraft_id, []).append(row)
    return grouped


def open_work_orders(db: Session) -> dict[tuple[int, int], WorkOrder]:
    """(aircraft_id, part_id) -> open work order, in ONE query."""
    return {
        (w.aircraft_id, w.part_id): w
        for w in db.scalars(select(WorkOrder).where(WorkOrder.status != "done"))
    }


def agencies_by_id(db: Session) -> dict[int, Agency]:
    return {agency.id: agency for agency in db.scalars(select(Agency))}


def all_parts_with_aircraft(db: Session) -> list[tuple[Aircraft, AircraftPart, Part]]:
    return list(
        db.execute(
            select(Aircraft, AircraftPart, Part)
            .join(AircraftPart, AircraftPart.aircraft_id == Aircraft.id)
            .join(Part, Part.id == AircraftPart.part_id)
            .order_by(Aircraft.code, Part.sort_order)
        ).tuples()
    )


def open_work_order(db: Session, aircraft_id: int, part_id: int) -> WorkOrder | None:
    return db.scalar(
        select(WorkOrder).where(
            WorkOrder.aircraft_id == aircraft_id,
            WorkOrder.part_id == part_id,
            WorkOrder.status != "done",
        )
    )


# ── time-series ────────────────────────────────────────────────────────────────
def engine_history(
    db: Session, aircraft_id: int, window: int
) -> list[tuple[HealthSnapshot, MlPrediction | None, ComponentHealth | None]]:
    # Phase 3 (docs/16 M3): the engine-history reader must not collapse radar
    # rows into the "engine health" shown to an operator. Resolve the engine
    # part once, then filter snapshots to that part and order deterministically
    # by cycle so the dict keyed by cycle can only ever hold engine rows.
    engine_part = db.scalar(select(Part).where(Part.code == "engine"))
    engine_part_id = engine_part.id if engine_part is not None else None
    cycles = db.scalars(
        select(HealthSnapshot.cycle)
        .where(
            HealthSnapshot.aircraft_id == aircraft_id,
            *(
                [HealthSnapshot.part_id == engine_part_id]
                if engine_part_id is not None
                else [Part.code == "engine"]
            ),
        )
        .join(Part, Part.id == HealthSnapshot.part_id)
        .where(Part.code == "engine")
        .order_by(HealthSnapshot.cycle.desc())
        .limit(window)
    ).all()
    if not cycles:
        return []
    lo, hi = min(cycles), max(cycles)

    snap_stmt = select(HealthSnapshot).where(
        HealthSnapshot.aircraft_id == aircraft_id,
        HealthSnapshot.cycle.between(lo, hi),
    )
    if engine_part_id is not None:
        snap_stmt = snap_stmt.where(HealthSnapshot.part_id == engine_part_id)
    snap_stmt = snap_stmt.order_by(HealthSnapshot.part_id, HealthSnapshot.cycle)
    snapshots = {s.cycle: s for s in db.scalars(snap_stmt)}
    preds = {
        p.cycle: p
        for p in db.scalars(
            select(MlPrediction)
            .where(
                MlPrediction.aircraft_id == aircraft_id,
                MlPrediction.cycle.between(lo, hi),
            )
            .order_by(MlPrediction.cycle)
        )
    }
    comps = {
        c.cycle: c
        for c in db.scalars(
            select(ComponentHealth)
            .where(
                ComponentHealth.aircraft_id == aircraft_id,
                ComponentHealth.cycle.between(lo, hi),
            )
            .order_by(ComponentHealth.cycle)
        )
    }
    return [(snapshots[c], preds.get(c), comps.get(c)) for c in sorted(snapshots)]


def fleet_snapshots(db: Session, window: int) -> dict[int, list[dict[str, Any]]]:
    """Last `window` engine snapshots per aircraft, in one query.

    Windowed in SQL (ROW_NUMBER per aircraft), not sliced in Python: the old
    version scanned the entire append-only history on every /fleet/summary call,
    and that table grows at ~36 KB/s under the replay engine — the most-polled
    endpoint had become a full table scan that got slower every hour.
    """
    ranked = (
        select(
            HealthSnapshot.aircraft_id,
            HealthSnapshot.cycle,
            HealthSnapshot.health,
            func.row_number()
            .over(
                partition_by=HealthSnapshot.aircraft_id,
                order_by=HealthSnapshot.cycle.desc(),
            )
            .label("rn"),
        )
        .join(Part, Part.id == HealthSnapshot.part_id)
        .where(Part.code == "engine")
        .subquery()
    )
    rows = db.execute(
        select(ranked.c.aircraft_id, ranked.c.cycle, ranked.c.health)
        .where(ranked.c.rn <= window)
        .order_by(ranked.c.aircraft_id, ranked.c.cycle)
    ).all()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for aircraft_id, cycle, health in rows:
        grouped.setdefault(aircraft_id, []).append({"cycle": cycle, "health": float(health)})
    return grouped


# ── maintenance ────────────────────────────────────────────────────────────────
def list_spares(db: Session) -> list[Spare]:
    return list(db.scalars(select(Spare).order_by(Spare.part_ref_id)))


def last_stock_movements(db: Session) -> dict[int, StockMovement]:
    """Latest movement per spare in ONE query — the N+1 guard for GET /spares.

    Phase 3 (docs/16 M3): portable ROW_NUMBER window — one row per spare,
    newest first — instead of loading the whole table (the one table with no
    retention job) and sorting in Python. DISTINCT ON would be Postgres-only;
    ROW_NUMBER works on Postgres and SQLite alike.
    """
    # Re-select the entity from the ranked subquery: the ORM entity plus rn.
    # Simpler portable form: max(created_at) per spare, then join back.
    latest_ts = (
        select(StockMovement.spare_id, func.max(StockMovement.created_at).label("mx"))
        .group_by(StockMovement.spare_id)
        .subquery()
    )
    rows = db.scalars(
        select(StockMovement)
        .join(
            latest_ts,
            (StockMovement.spare_id == latest_ts.c.spare_id)
            & (StockMovement.created_at == latest_ts.c.mx),
        )
        .order_by(StockMovement.spare_id)
    ).all()
    return {row.spare_id: row for row in rows}


def list_agencies(db: Session) -> list[Agency]:
    return list(db.scalars(select(Agency).order_by(Agency.agency_ref_id)))


def open_bookings(db: Session, agency_id: int) -> list[AgencyBooking]:
    return list(
        db.scalars(
            select(AgencyBooking).where(
                AgencyBooking.agency_id == agency_id,
                AgencyBooking.completed_at.is_(None),
            )
        )
    )


def spare_for_component(db: Session, component_name: str | None) -> Spare | None:
    """Rule 25 — resolve the spare for a component family (docs/05 §7)."""
    if not component_name:
        return None
    return db.scalar(
        select(Spare)
        .where(Spare.component_name == component_name)
        .order_by(
            Spare.criticality.desc().nullslast(),
            Spare.stock.asc(),
        )
        .limit(1)
    )


def spares_by_component(db: Session) -> dict[str, Spare]:
    """component_name -> best spare, in ONE query (rule 25).

    Ordering matches spare_for_component: highest criticality, then lowest stock,
    so the part most likely to be missing is the one surfaced.
    """
    ordered = db.scalars(
        select(Spare)
        .where(Spare.component_name.is_not(None))
        .order_by(Spare.criticality.desc().nullslast(), Spare.stock.asc())
    )
    out: dict[str, Spare] = {}
    for spare in ordered:
        out.setdefault(str(spare.component_name), spare)
    return out


# ── alerts ─────────────────────────────────────────────────────────────────────
def list_alerts(db: Session, acknowledged: bool | None, limit: int) -> list[Alert]:
    # Phase 3 (docs/16 M3): WHERE before ORDER BY/LIMIT — SQLAlchemy reorders
    # clauses, but stating filters first keeps the intent (pre-LIMIT filtering)
    # obvious and lets the (created_at DESC) index serve the sort.
    stmt = select(Alert)
    if acknowledged is not None:
        stmt = stmt.where(Alert.acknowledged.is_(acknowledged))
    stmt = stmt.order_by(Alert.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def get_alert(db: Session, alert_id: int) -> Alert | None:
    return db.get(Alert, alert_id)


def unacked_count(db: Session) -> int:
    # Phase 3: COUNT(*) permits an index-only scan where COUNT(id) does not.
    return db.scalar(select(func.count()).where(Alert.acknowledged.is_(False))) or 0


# ── technical records ──────────────────────────────────────────────────────────
def recent_records(
    db: Session, aircraft_ref_id: int, part: str, limit: int = 2
) -> list[tuple[TechnicalRecord, str | None]]:
    """Last `limit` records for the parts mapped to `part` (docs/06 §2)."""
    from ..domain.health import FAULT_MAP

    if part == "engine":
        rows = db.scalars(
            select(TechnicalRecord)
            .where(TechnicalRecord.aircraft_ref_id == aircraft_ref_id)
            .order_by(TechnicalRecord.event_date.desc())
            .limit(limit)
        ).all()
        return [(r, r.agency_ref_id) for r in rows]

    faults = [f for f, (p, _) in FAULT_MAP.items() if p == part]
    if not faults:
        return []
    rows = db.scalars(
        select(TechnicalRecord)
        .where(
            TechnicalRecord.aircraft_ref_id == aircraft_ref_id,
            TechnicalRecord.fault_type.in_(faults),
        )
        .order_by(TechnicalRecord.event_date.desc())
        .limit(limit)
    ).all()
    return [(r, r.agency_ref_id) for r in rows]


def availabilities(db: Session, aircraft_ref_ids: list[int]) -> dict[int, float]:
    """Mean availability per reference id in ONE query — the N+1 guard for
    fleet_summary, which used to issue one AVG per aircraft."""
    if not aircraft_ref_ids:
        return {}
    # Phase 3 (docs/16 M3): SmallInteger / SmallInteger is integer division in
    # Postgres — latent while days_unavailable=0. Cast to Numeric so real data
    # (830/3300 rows the moment it lands) averages correctly.
    ratio = cast(FlightOpsMonthly.days_available, Numeric) / func.nullif(
        cast(FlightOpsMonthly.days_available, Numeric)
        + cast(FlightOpsMonthly.days_unavailable, Numeric),
        0,
    )
    rows = db.execute(
        select(
            FlightOpsMonthly.aircraft_ref_id,
            func.avg(ratio),
        )
        .where(FlightOpsMonthly.aircraft_ref_id.in_(aircraft_ref_ids))
        .group_by(FlightOpsMonthly.aircraft_ref_id)
    ).all()
    return {ref: round(float(value), 4) for ref, value in rows if value is not None}


def availability(db: Session, aircraft_ref_id: int) -> float | None:
    """days_available / (available + unavailable) over flight_operations (docs/01 §9)."""
    ratio = cast(FlightOpsMonthly.days_available, Numeric) / func.nullif(
        cast(FlightOpsMonthly.days_available, Numeric)
        + cast(FlightOpsMonthly.days_unavailable, Numeric),
        0,
    )
    row = db.execute(
        select(func.avg(ratio)).where(FlightOpsMonthly.aircraft_ref_id == aircraft_ref_id)
    ).scalar()
    return round(float(row), 4) if row is not None else None


def high_stress_sorties(db: Session, aircraft_ref_id: int, months: int = 12) -> int | None:
    rows = db.scalars(
        select(FlightOpsMonthly.high_stress_sorties)
        .where(FlightOpsMonthly.aircraft_ref_id == aircraft_ref_id)
        .order_by(FlightOpsMonthly.month.desc())
        .limit(months)
    ).all()
    return sum(v for v in rows if v is not None) if rows else None


# ── reference ──────────────────────────────────────────────────────────────────
def count_aircraft(db: Session) -> int:
    return db.scalar(select(func.count(Aircraft.id))) or 0

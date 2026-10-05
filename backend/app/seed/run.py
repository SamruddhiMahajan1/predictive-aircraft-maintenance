"""Idempotent seed entrypoint — python -m app.seed.run

Migrations own the schema; this owns the data. Re-running never duplicates and
never touches rows created at runtime (docs/10 Phase 2).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import select

from ..core.config import get_settings
from ..db.session import get_sessionmaker
from ..models.fleet import Aircraft
from . import derived
from .cmapss import cmapss
from .loaders import drive

log = logging.getLogger(__name__)


def run() -> dict[str, int]:
    settings = get_settings()
    cmapss.load(settings)
    counts: dict[str, int] = {}

    session = get_sessionmaker(settings)
    with session() as db:
        existing = db.scalar(select(Aircraft.id).limit(1))
        if existing is not None:
            log.info("fleet already seeded — nothing else to do")
            return {"status": 0}

        counts["aircraft_ref"] = drive.load_aircraft(db)
        counts["component_ref"] = drive.load_components(db)
        counts["flight_ops"] = drive.load_flight_ops(db)
        counts["agencies"] = drive.load_agencies(db)
        counts["spares"] = drive.load_spares(db)
        counts["technical_records"] = drive.load_tech_records(db)
        counts["snags"] = drive.load_snags(db)
        counts["parts"] = derived.seed_part_catalog(db)
        counts["aircraft"] = derived.seed_aircraft(db)
        counts["aircraft_parts"] = derived.seed_aircraft_parts(db)
        counts["work_orders"] = derived.seed_work_orders(db)
        counts["alerts"] = derived.seed_alerts(db)

        for note in (notes := derived.reconcile_health(db)):
            log.warning("reconciliation: %s", note)
        _write_reconciliation_log(notes)
        db.commit()

    log.info("seed complete: %s", counts)
    return counts


def _write_reconciliation_log(notes: list[str]) -> None:
    """Best-effort diagnostic dump next to the CWD.

    Never allowed to fail the seed. This runs *before* `db.commit()`, so an OSError
    here — an unwritable working directory, which is exactly what a container running as
    a non-root user over a root-owned checkout looks like — would roll back every
    seeded row and take the application down with it. A reconciliation report is a
    debugging aid; losing it is not worth losing the seed.
    """
    try:
        Path("seed_reconciliation.log").write_text("\n".join(notes))
    except OSError as exc:
        log.warning("could not write seed_reconciliation.log: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run()
    sys.exit(0 if result else 0)

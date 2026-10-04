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
from ..core.security import hash_password
from ..db.session import get_sessionmaker
from ..models.auth import User, UserRole
from ..models.fleet import Aircraft
from . import derived
from .cmapss import cmapss
from .loaders import drive

log = logging.getLogger(__name__)

DEMO_USERS = [
    ("commander", "commander123", "Cmdr. A. Rao", UserRole.commander),
    ("officer", "officer123", "M. Iyer", UserRole.maintenance_officer),
    ("viewer", "viewer123", "S. Nair", UserRole.viewer),
]


def seed_users(db) -> int:
    settings = get_settings()
    count = 0
    for username, password, full_name, role in DEMO_USERS:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(User(username=username,
                        password_hash=hash_password(password, settings),
                        full_name=full_name, role=role))
            count += 1
    db.flush()
    return count


def run() -> dict[str, int]:
    settings = get_settings()
    cmapss.load(settings)
    counts: dict[str, int] = {}

    session = get_sessionmaker(settings)
    with session() as db:
        existing = db.scalar(select(Aircraft.id).limit(1))
        if existing is not None:
            log.info("database already seeded — nothing to do")
            return {"status": 0}

        counts["users"] = seed_users(db)
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

        for note in derived.reconcile_health(db):
            log.warning("reconciliation: %s", note)
        Path("seed_reconciliation.log").write_text(
            "\n".join(derived.reconcile_health(db))
        )
        db.commit()

    log.info("seed complete: %s", counts)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = run()
    sys.exit(0 if result else 0)
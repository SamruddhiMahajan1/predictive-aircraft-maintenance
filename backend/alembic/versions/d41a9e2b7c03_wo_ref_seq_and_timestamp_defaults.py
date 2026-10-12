"""wo_ref_seq + timestamp server defaults (docs/16 Phase 3 M3).

Revision ID: d41a9e2b7c03
Revises: c69f5fe8dc18
Create Date: 2026-10-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d41a9e2b7c03"
down_revision = "c69f5fe8dc18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Atomic work-order references: count(*)+1 collides under concurrent
    # creates → IntegrityError → bare 500. Seed from max existing id so
    # deployed rows keep monotonic references.
    op.execute("CREATE SEQUENCE IF NOT EXISTS wo_ref_seq START 1")
    op.execute(
        """
        SELECT setval(
            'wo_ref_seq',
            COALESCE((SELECT MAX(id) FROM work_order), 0) + 1,
            false
        )
        """
    )
    # Timezone-safe server defaults for all timestamptz columns that the ORM
    # now also defaults client-side with datetime.now(UTC). ALTER ... SET
    # DEFAULT is idempotent and safe on populated tables.
    for table, col in [
        ("aircraft", "created_at"),
        ("aircraft", "updated_at"),
        ("aircraft_part", "updated_at"),
        ("health_snapshot", "recorded_at"),
        ("engine_telemetry", "recorded_at"),
        ("component_health", "recorded_at"),
        ("ml_prediction", "created_at"),
        ("alert", "created_at"),
        ("work_order", "created_at"),
        ("work_order", "updated_at"),
        ("agency_booking", "created_at"),
        ("stock_movement", "created_at"),
        ("audit_log", "at"),
    ]:
        try:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} SET DEFAULT now()")
        except Exception:
            pass


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS wo_ref_seq")

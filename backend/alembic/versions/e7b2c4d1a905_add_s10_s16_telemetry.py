"""add s10/s16 to engine_telemetry (sensor-selection skew fix).

s10/s16 are constant in FD001 but live in FD002/FD003/FD004, and the pooled
contract scores them there. The read path dropped them, feeding 0.0-raw into
the z-scorer for exactly the subsets where training saw real values (FD003
22.5 vs 20.2, FD002/FD004 ~28-30). Nullable: existing rows backfill NULL
(unknown), never 0.0 — 0.0 would z-score into a garbage feature.

Revision ID: e7b2c4d1a905
Revises: d41a9e2b7c03
Create Date: 2026-10-12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e7b2c4d1a905"
down_revision = "d41a9e2b7c03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("engine_telemetry", sa.Column("s10", sa.Numeric(12, 4), nullable=True))
    op.add_column("engine_telemetry", sa.Column("s16", sa.Numeric(12, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("engine_telemetry", "s16")
    op.drop_column("engine_telemetry", "s10")

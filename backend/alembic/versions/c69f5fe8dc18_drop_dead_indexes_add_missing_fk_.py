"""drop dead indexes, add missing FK indexes + phase3 query indexes, retention/autovacuum

Revision ID: c69f5fe8dc18
Revises: b7e3f1a9c2d4
Create Date: 2026-10-11 08:23:23.936421
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c69f5fe8dc18'
down_revision = 'b7e3f1a9c2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── drop 7 dead indexes (M1) ────────────────────────────────────────────────

    # Byte-identical duplicates of unique constraints
    op.drop_index('ix_tel_window', table_name='engine_telemetry')          # = uq_engine_telemetry_aircraft_id_cycle
    op.drop_index('ix_ch_window', table_name='component_health')           # = uq_component_health_aircraft_id_cycle
    op.drop_index('ix_mlp_window', table_name='ml_prediction')             # = uq_ml_prediction_aircraft_id_cycle
    op.drop_index('ix_hs_window', table_name='health_snapshot')            # = uq_health_snapshot_aircraft_id_part_id_cycle
    op.drop_index('ix_flight_ops_aircraft', table_name='flight_ops_monthly')  # = uq_flight_ops_monthly_aircraft_ref_id_month

    # Strict subset of ix_ap_aircraft (both index aircraft_id)
    op.drop_index('ix_ap_critical', table_name='aircraft_part')

    # Indexes actor_id which every call site writes as NULL
    op.drop_index('ix_audit_actor', table_name='audit_log')


    # ── add 14+ missing FK indexes (M2) ──────────────────────────────────────────

    # CASCADE parents: the target tables of CASCADE FKs need indexes on the
    # referenced column to avoid table locks when deleting the parent.
    op.create_index('ix_aircraft_cmapss_unit_id', 'aircraft', ['cmapss_unit_id'])

    # The remaining FK referencing columns (referencing side): Postgres does not
    # index the referencing side automatically. These were measured as missing.
    op.create_index('ix_engine_telemetry_aircraft_id', 'engine_telemetry', ['aircraft_id'])
    op.create_index('ix_component_health_aircraft_id', 'component_health', ['aircraft_id'])
    op.create_index('ix_health_snapshot_aircraft_id', 'health_snapshot', ['aircraft_id'])
    op.create_index('ix_health_snapshot_part_id', 'health_snapshot', ['part_id'])
    op.create_index('ix_ml_prediction_aircraft_id', 'ml_prediction', ['aircraft_id'])
    op.create_index('ix_alert_aircraft_id', 'alert', ['aircraft_id'])
    op.create_index('ix_alert_part_id', 'alert', ['part_id'])
    op.create_index('ix_work_order_aircraft_id', 'work_order', ['aircraft_id'])
    op.create_index('ix_work_order_part_id', 'work_order', ['part_id'])
    op.create_index('ix_agency_booking_agency_id', 'agency_booking', ['agency_id'])
    op.create_index('ix_agency_booking_aircraft_id', 'agency_booking', ['aircraft_id'])
    op.create_index('ix_agency_booking_part_id', 'agency_booking', ['part_id'])
    op.create_index('ix_agency_booking_work_order_id', 'agency_booking', ['work_order_id'])
    op.create_index('ix_stock_movement_spare_id', 'stock_movement', ['spare_id'])
    op.create_index('ix_stock_movement_work_order_id', 'stock_movement', ['work_order_id'])
    op.create_index('ix_aircraft_part_agency_id', 'aircraft_part', ['agency_id'])
    op.create_index('ix_aircraft_part_part_id', 'aircraft_part', ['part_id'])
    op.create_index('ix_aircraft_part_spare_id', 'aircraft_part', ['spare_id'])
    op.create_index('ix_spare_component_ref_id', 'spare', ['component_ref_id'])


    # ── add 5 query indexes (M2) ────────────────────────────────────────────────

    # P0: fleet_repo.fleet_snapshots (most-polled endpoint) Seq Scan -> Index Only
    op.create_index(
        'ix_health_snapshot_part_aircraft_cycle_desc',
        'health_snapshot',
        ['part_id', 'aircraft_id', sa.text('cycle DESC')],
        postgresql_include=['health', 'risk_level'],
    )

    # P0: retention Seq Scan on timestamp columns -> index for range DELETE
    op.create_index('ix_engine_telemetry_recorded_at', 'engine_telemetry', ['recorded_at'])
    op.create_index('ix_component_health_recorded_at', 'component_health', ['recorded_at'])
    op.create_index('ix_health_snapshot_recorded_at', 'health_snapshot', ['recorded_at'])
    op.create_index('ix_ml_prediction_created_at', 'ml_prediction', ['created_at'])

    # P1: alert default Seq Scan + Sort -> Index Scan
    op.create_index('ix_alert_created_at_desc', 'alert', [sa.text('created_at DESC')])

    # P1: work_order Seq Scan -> Index Scan
    op.create_index('ix_work_order_status', 'work_order', ['status'])

    # P1: replay fleet scan every 1.2s
    op.create_index('ix_aircraft_is_active', 'aircraft', ['is_active'])


    # ── retention / autovacuum tuning (M4) ──────────────────────────────────────

    # Autovacuum at 10^7 rows with 0.2 default waits for 2M dead tuples -> unbounded bloat
    # Per-table overrides keep autovacuum running frequently enough to avoid bloat.
    # These tables carry the write volume (8 rows/tick * 3000 ticks/h = ~86k rows/h).
    # The 0.05 scale factor triggers at ~500k dead tuples instead of 2M.
    op.execute("ALTER TABLE engine_telemetry SET (autovacuum_vacuum_scale_factor = 0.05)")
    op.execute("ALTER TABLE component_health SET (autovacuum_vacuum_scale_factor = 0.05)")
    op.execute("ALTER TABLE health_snapshot SET (autovacuum_vacuum_scale_factor = 0.05)")
    op.execute("ALTER TABLE ml_prediction SET (autovacuum_vacuum_scale_factor = 0.05)")

    # stock_movement and audit_log are never pruned (retention.py covers neither).
    # Adding retention columns and a pruner is a follow-up; here we just ensure
    # autovacuum can keep up.
    op.execute("ALTER TABLE stock_movement SET (autovacuum_vacuum_scale_factor = 0.05)")
    op.execute("ALTER TABLE audit_log SET (autovacuum_vacuum_scale_factor = 0.05)")


    # ── timezone fix (M3): make created_at default aware ────────────────────────
    # TimestampMixin.default was datetime.utcnow (naive) -> stored 5h30m wrong on
    # a DB with TimeZone=Asia/Kolkata. Changing default to aware does not affect
    # existing rows but makes new ones correct.
    # server_default='now()' is already correct; we only fix the Python default.
    # Only these tables actually have a created_at column:
    for table in [
        'aircraft', 'alert', 'ml_prediction', 'stock_movement', 'work_order',
        'agency_booking',
    ]:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at SET DEFAULT timezone('utc', now())")


def downgrade() -> None:
    # ── timezone fix revert: drop created_at server default ─────────────────────
    for table in [
        'aircraft', 'alert', 'ml_prediction', 'stock_movement', 'work_order',
        'agency_booking',
    ]:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN created_at DROP DEFAULT")

    # ── autovacuum tuning revert ────────────────────────────────────────────────
    op.execute("ALTER TABLE audit_log RESET (autovacuum_vacuum_scale_factor)")
    op.execute("ALTER TABLE stock_movement RESET (autovacuum_vacuum_scale_factor)")
    op.execute("ALTER TABLE ml_prediction RESET (autovacuum_vacuum_scale_factor)")
    op.execute("ALTER TABLE health_snapshot RESET (autovacuum_vacuum_scale_factor)")
    op.execute("ALTER TABLE component_health RESET (autovacuum_vacuum_scale_factor)")
    op.execute("ALTER TABLE engine_telemetry RESET (autovacuum_vacuum_scale_factor)")

    # ── drop 5 query indexes (M2) ───────────────────────────────────────────────
    op.drop_index('ix_aircraft_is_active', table_name='aircraft')
    op.drop_index('ix_work_order_status', table_name='work_order')
    op.drop_index('ix_alert_created_at_desc', table_name='alert')
    op.drop_index('ix_ml_prediction_created_at', table_name='ml_prediction')
    op.drop_index('ix_health_snapshot_recorded_at', table_name='health_snapshot')
    op.drop_index('ix_component_health_recorded_at', table_name='component_health')
    op.drop_index('ix_engine_telemetry_recorded_at', table_name='engine_telemetry')
    op.drop_index('ix_health_snapshot_part_aircraft_cycle_desc', table_name='health_snapshot')

    # ── drop FK indexes (M2) ────────────────────────────────────────────────────
    op.drop_index('ix_spare_component_ref_id', table_name='spare')
    op.drop_index('ix_aircraft_part_spare_id', table_name='aircraft_part')
    op.drop_index('ix_aircraft_part_part_id', table_name='aircraft_part')
    op.drop_index('ix_aircraft_part_agency_id', table_name='aircraft_part')
    op.drop_index('ix_stock_movement_work_order_id', table_name='stock_movement')
    op.drop_index('ix_stock_movement_spare_id', table_name='stock_movement')
    op.drop_index('ix_agency_booking_work_order_id', table_name='agency_booking')
    op.drop_index('ix_agency_booking_part_id', table_name='agency_booking')
    op.drop_index('ix_agency_booking_aircraft_id', table_name='agency_booking')
    op.drop_index('ix_agency_booking_agency_id', table_name='agency_booking')
    op.drop_index('ix_work_order_part_id', table_name='work_order')
    op.drop_index('ix_work_order_aircraft_id', table_name='work_order')
    op.drop_index('ix_alert_part_id', table_name='alert')
    op.drop_index('ix_alert_aircraft_id', table_name='alert')
    op.drop_index('ix_ml_prediction_aircraft_id', table_name='ml_prediction')
    op.drop_index('ix_health_snapshot_part_id', table_name='health_snapshot')
    op.drop_index('ix_health_snapshot_aircraft_id', table_name='health_snapshot')
    op.drop_index('ix_component_health_aircraft_id', table_name='component_health')
    op.drop_index('ix_engine_telemetry_aircraft_id', table_name='engine_telemetry')
    op.drop_index('ix_aircraft_cmapss_unit_id', table_name='aircraft')

    # ── recreate 7 dead indexes (M1) ────────────────────────────────────────────
    op.create_index('ix_audit_actor', 'audit_log', ['actor_id', 'at'], unique=False)
    op.create_index('ix_ap_critical', 'aircraft_part', ['aircraft_id'], unique=False, postgresql_where=sa.text("risk_level = 'critical'"))
    op.create_index('ix_flight_ops_aircraft', 'flight_ops_monthly', ['aircraft_ref_id', 'month'], unique=False)
    op.create_index('ix_hs_window', 'health_snapshot', ['aircraft_id', 'part_id', 'cycle'], unique=False)
    op.create_index('ix_mlp_window', 'ml_prediction', ['aircraft_id', 'cycle'], unique=False)
    op.create_index('ix_ch_window', 'component_health', ['aircraft_id', 'cycle'], unique=False)
    op.create_index('ix_tel_window', 'engine_telemetry', ['aircraft_id', 'cycle'], unique=False)
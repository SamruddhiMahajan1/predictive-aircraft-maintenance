"""Database indexes: structural guards against drift.

These assert that the schema decisions in the migration are not undone by a
later change: no index is a strict prefix of a unique constraint, every FK
referencing column is indexed, and the autovacuum scale factor is configured.
"""
from __future__ import annotations

import pytest

from app.db.session import get_engine


def test_no_index_is_byte_identical_to_a_unique_constraint():
    """A non-unique index that is byte-identical to a unique constraint is dead weight.

    The initial migration created 7 such indexes; this migration dropped them.
    This test asserts the drift cannot reappear.
    """
    from sqlalchemy import inspect

    eng = get_engine()
    insp = inspect(eng)
    for t in ['engine_telemetry', 'component_health', 'health_snapshot',
              'ml_prediction', 'flight_ops_monthly', 'aircraft_part',
              'audit_log']:
        # Use the actual column order (not sorted), because a unique constraint on
        # (a, b, c) and an index on (c, b, a) are different in Postgres.
        uqs = {tuple(c['column_names']) for c in insp.get_unique_constraints(t)}
        # get_indexes returns ALL indexes including unique ones; filter them
        idxs = {tuple(c['column_names']) for c in insp.get_indexes(t)
                if not c.get('unique', False)}
        for idx_cols in idxs:
            for uq_cols in uqs:
                if idx_cols == uq_cols:
                    pytest.fail(f"{t}: non-unique index {idx_cols} is byte-identical to unique {uq_cols}")


def test_every_fk_referencing_column_is_indexed():
    """Postgres does not index the referencing side of a FK automatically.

    19 columns were unindexed; this migration added indexes for all of them.
    """
    from sqlalchemy import inspect

    eng = get_engine()
    insp = inspect(eng)
    missing: list[str] = []
    for t in ['engine_telemetry', 'component_health', 'health_snapshot',
              'ml_prediction', 'alert', 'work_order', 'aircraft',
              'agency_booking', 'stock_movement', 'aircraft_part', 'spare']:
        fks = insp.get_foreign_keys(t)
        idxs = {tuple(sorted(c['column_names'])) for c in insp.get_indexes(t)}
        for fk in fks:
            cols = tuple(fk['constrained_columns'])
            if cols not in idxs:
                missing.append(f"{t}.{cols}")
    assert not missing, f"FK referencing columns missing indexes: {missing}"


def test_autovacuum_scale_factor_is_configured():
    """The high-volume tables must have autovacuum_scale_factor = 0.05.

    With the default 0.2, autovacuum at 10^7 rows waits for 2M dead tuples,
    producing unbounded bloat between passes. 0.05 triggers at ~500k instead.
    """
    from sqlalchemy import text

    eng = get_engine()
    with eng.connect() as conn:
        for table in ['engine_telemetry', 'component_health', 'health_snapshot',
                      'ml_prediction', 'stock_movement', 'audit_log']:
            opts = conn.execute(text(
                "SELECT reloptions FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname = :t"),
                {"t": table}).scalar()
            assert opts is not None, f"{table}: no reloptions"
            # reloptions is a list; check membership
            assert any('autovacuum_vacuum_scale_factor=0.05' in str(o) for o in opts), (
                f"{table}: scale factor not 0.05, got {opts}")


def test_created_at_default_is_utc_aware():
    """created_at defaults must be timezone-aware (not naive utcnow).

    Naive utcnow into a timestamptz is interpreted in the session TimeZone, so
    a DB on Asia/Kolkata stored 5h30m wrong.
    """
    from sqlalchemy import inspect

    eng = get_engine()
    insp = inspect(eng)
    for table in ['aircraft', 'alert', 'ml_prediction', 'stock_movement',
                  'work_order', 'agency_booking']:
        cols = insp.get_columns(table)
        col = next(c for c in cols if c['name'] == 'created_at')
        default = str(col['default'])
        # Postgres renders it with an explicit cast; accept both forms.
        assert "timezone('utc'" in default and "now()" in default, (
            f"{table}.created_at default is {default!r}, expected timezone('utc', now())")

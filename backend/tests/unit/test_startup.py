"""Startup isolation: one failing boot phase must not abort the rest.

A migration import error once propagated out of the shared try block in
`_background_init` and skipped the model load, the seed and the replay engine
in one stroke — the service reported healthy while serving an empty fallback
fleet with no live stream. Each phase is now guarded independently; these tests
pin that.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import app.main as main_module


def _fake_app():
    return SimpleNamespace(state=SimpleNamespace())


def test_background_init_survives_every_phase_failing(monkeypatch):
    """Migration + model + seed all raise; the replay must still start."""
    monkeypatch.setenv("RENDER", "true")

    def boom_migrate():
        raise RuntimeError("migration exploded")

    def boom_load(*args, **kwargs):
        raise RuntimeError("model missing")

    async def boom_seed(settings):
        raise RuntimeError("db down")

    started = []

    async def ok_replay():
        started.append(True)

    monkeypatch.setattr(main_module, "_migrate_schema", boom_migrate)
    monkeypatch.setattr(main_module.model_store, "load", boom_load)
    monkeypatch.setattr(main_module.cmapss, "load", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(main_module, "_seed_if_empty", boom_seed)
    monkeypatch.setattr(main_module, "start_replay", ok_replay)

    app = _fake_app()
    asyncio.run(main_module._background_init(app, object()))

    assert started == [True]
    assert app.state.startup_done is True
    assert "migration failed" in app.state.startup_error
    assert "model load failed" in app.state.startup_error
    assert "seed failed" in app.state.startup_error


def test_migrate_schema_without_binary_never_raises(monkeypatch, tmp_path):
    """No `alembic` on PATH must be a logged skip, not an exception."""
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    monkeypatch.chdir(tmp_path)
    main_module._migrate_schema()  # must return, not raise


def test_migrate_schema_without_ini_never_raises(monkeypatch, tmp_path):
    """Wrong CWD (no alembic.ini) must be a logged skip, not an exception."""
    monkeypatch.chdir(tmp_path)
    main_module._migrate_schema()  # must return, not raise

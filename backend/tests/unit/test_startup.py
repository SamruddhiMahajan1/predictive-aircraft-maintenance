"""Startup isolation: one failing boot phase must not abort the rest.

A migration import error once propagated out of the shared try block in
`_background_init` and skipped the model load, the seed and the replay engine
in one stroke — the service reported healthy while serving an empty fallback
fleet with no live stream. Each phase is now guarded independently; these tests
pin that.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import app.main as main_module

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROBE = (
    "import app, os; print(os.environ['OMP_NUM_THREADS'], "
    "os.environ['OPENBLAS_NUM_THREADS'], os.environ['MKL_NUM_THREADS'], "
    "os.environ['MALLOC_ARENA_MAX'])"
)


def _probe_env(extra: dict[str, str]) -> str:
    """Run a bare `import app` in a fresh interpreter and report the pins."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "MALLOC_ARENA_MAX",
        )
    }
    env.update(extra)
    proc = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        cwd=BACKEND_DIR,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_package_init_pins_math_threads():
    """`import app` alone must set single-threaded math: dashboard-created
    services never see blueprint env vars, so code is the only reliable carrier
    for this. Without it the BLAS/OpenMP pools size from host CPUs and OOM the
    512 MB instance under a second client's load."""
    assert _probe_env({}) == "1 1 1 2"


def test_package_init_respects_explicit_threading():
    """An operator's explicit setting always wins over the default."""
    assert _probe_env({"OMP_NUM_THREADS": "99"}) == "99 1 1 2"


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

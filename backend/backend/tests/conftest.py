"""Shared test fixtures — real PostgreSQL, migrated + seeded once per session.

Tests exercise the actual database (partial indexes, row locks, CHECK constraints)
rather than a mock, because most of what is worth verifying lives in the schema.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── environment must be set before app.core.config is imported ──────────────────
os.environ.setdefault(
    "FDT_DATABASE_URL", "postgresql+psycopg://fdt@/fdt?host=/tmp/opencode&port=55432"
)
os.environ.setdefault("FDT_JWT_SECRET", "test-secret-0123456789abcdefghijklmnop")
os.environ.setdefault("FDT_DEMO_MODE", "false")
os.environ.setdefault("FDT_ML_FALLBACK", "true")
os.environ.setdefault("FDT_DATA_DIR", "data")


def _staged_variant() -> str | None:
    """Which variant actually has artifacts, without importing the app.

    `Settings` is cached and `.env` is not read here, so this is a plain filesystem
    probe of data/ml/<variant>/ against the loader's own filename table. Duplicated as
    a literal rather than imported: importing app.core.config before the env defaults
    above are set would freeze a Settings built from a different environment.
    """
    root = pathlib.Path(os.environ["FDT_DATA_DIR"]) / "ml"
    known = {
        "full": "xgboost_fd001_full.json",
        "holdout": "xgboost_fd001_rul.json",
        "all": "xgboost_all_full.json",
    }
    return next((v for v, f in known.items() if (root / v / f).is_file()), None)


# Point the suite at whichever variant is staged. Without this the app under test
# loads the default `full` variant, silently falls back when only `all` is present,
# and the artifact tests then fail on fallback behaviour rather than on the artifact.
_STAGED = _staged_variant()
if _STAGED:
    os.environ.setdefault("FDT_ML_VARIANT", _STAGED)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402

DEMO_PASSWORD = {"commander": "commander123", "officer": "officer123",
                 "viewer": "viewer123"}


def _alembic(*args: str) -> None:
    # the console script, not `-m alembic`: ROOT/alembic/ shadows the package
    alembic_bin = pathlib.Path(sys.executable).parent / "alembic"
    result = subprocess.run(
        [str(alembic_bin), *args],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )


def _seed() -> dict:
    from app.seed.run import run

    return run()


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    """Migrate a clean schema and seed it once for the whole session."""
    session = get_sessionmaker()()
    try:
        with session.begin():
            session.execute(text("DROP SCHEMA public CASCADE"))
            session.execute(text("CREATE SCHEMA public"))
        session.commit()
    finally:
        session.close()

    _alembic("upgrade", "head")
    counts = _seed()
    assert counts.get("aircraft") == 8, f"seed failed: {counts}"
    yield


@pytest.fixture(scope="session")
def client(database) -> Iterator[TestClient]:
    """A TestClient that has run the application lifespan."""
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client) -> dict[str, str]:
    out: dict[str, str] = {}
    for role, password in DEMO_PASSWORD.items():
        response = client.post(
            "/api/v1/auth/login",
            json={"username": role, "password": password},
        )
        assert response.status_code == 200, response.text
        out[role] = response.json()["access_token"]
    return out


@pytest.fixture
def auth(tokens):
    def _headers(role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens[role]}"}

    return _headers


@pytest.fixture
def db():
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def wait_for():
    """Poll until `predicate` holds or the timeout expires."""
    def _wait(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return False

    return _wait


__all__ = ["DEMO_PASSWORD", "ROOT"]
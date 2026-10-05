"""Configuration guards — settings that must behave sanely in every environment."""
from __future__ import annotations

import pytest

from app.core.config import Settings


def test_production_allows_demo_mode():
    """`demo_mode` picks a telemetry source; it is not a security control."""
    settings = Settings(environment="production", demo_mode=True)
    assert settings.demo_mode is True
    assert settings.environment == "production"


def test_cors_origins_accepts_a_comma_separated_string():
    """Operators set this as one env var; it must not arrive as one long string."""
    settings = Settings(
        cors_origins="https://a.example, https://b.example ,")
    assert settings.cors_origins == ["https://a.example", "https://b.example"]


# ── database URL ───────────────────────────────────────────────────────────────
#
# Render, Aiven, Neon, Supabase and Heroku all hand out a bare libpq URL. Handing that to
# SQLAlchemy 2 with only `psycopg` (v3) installed fails at startup with a `ModuleNotFoundError`
# or "Can't load plugin" that reads like a broken build, not a copied-and-pasted URL. The
# operator should be able to paste what the provider gave them.
@pytest.mark.parametrize(
    "given",
    [
        "postgres://u:p@host/db",
        "postgresql://u:p@host/db",
        "postgres://u:p@host:5432/db?sslmode=require",
    ])
def test_a_bare_provider_url_gets_the_pinned_driver(given):
    assert Settings(database_url=given).database_url.startswith("postgresql+psycopg://")


def test_the_explicit_pinned_url_is_left_alone():
    given = "postgresql+psycopg://u:p@host/db?sslmode=require"
    assert Settings(database_url=given).database_url == given


def test_another_driver_is_respected():
    """Only the bare libpq schemes are rewritten; a deliberate choice is not overridden."""
    given = "postgresql+asyncpg://u:p@host/db"
    assert Settings(database_url=given).database_url == given


def test_the_development_default_is_unchanged():
    assert Settings().database_url.startswith("postgresql+psycopg://")

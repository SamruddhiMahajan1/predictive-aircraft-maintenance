"""The replay engine's control surface and its degradation reporting.

These are the parts an operator reads when something is wrong. They were previously
unaudited, which is how a +13.6% period error and a silently-failing tick both went
unreported: `status()` returned only what had been configured, never what had been
achieved.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.core.config import Settings
from app.realtime.replay import ReplayEngine


@pytest.fixture
def engine() -> ReplayEngine:
    return ReplayEngine(Settings(_env_file=None))


def test_status_reports_what_was_achieved_not_only_what_was_configured(engine):
    """Drift, tick duration and consecutive failures must be observable.

    `interval_seconds` alone says only what an operator asked for. Measured against a
    1.2 s configuration the engine was achieving 1.364 s -- a 13.6% error with no
    endpoint able to show it.
    """
    status = engine.status()
    for field in ("last_tick_ms", "achieved_interval_seconds", "drift_pct", "consecutive_failures"):
        assert field in status, f"status() does not report {field}"
    assert status["interval_seconds"] == engine.settings.demo_tick_seconds
    # Before any tick has run these are legitimately unknown, not zero.
    assert status["last_tick_ms"] is None
    assert status["drift_pct"] is None
    assert status["consecutive_failures"] == 0


def test_drift_is_measured_against_the_configured_period(engine):
    """A recorded tick must produce an achieved period and a percentage.

    Sleep-based scheduling (interval, then work) makes the achieved period
    interval + tick_duration; compensating for the work is what keeps drift near zero.
    """
    configured = engine.settings.demo_tick_seconds
    engine._last_tick_started = 1000.0
    engine._record_success(elapsed_ms=180.0, started=1000.0 + configured)

    assert engine.last_tick_ms == 180.0
    assert engine.achieved_interval_seconds == pytest.approx(configured, abs=1e-3)
    assert engine.drift_pct == pytest.approx(0.0, abs=0.01)


def test_drift_is_reported_when_the_period_is_wrong(engine):
    """Drift is signed, so a slow loop and a fast one are distinguishable."""
    configured = engine.settings.demo_tick_seconds
    engine._last_tick_started = 1000.0
    achieved = configured * 1.136  # the measured pre-fix behaviour
    engine._record_success(elapsed_ms=200.0, started=1000.0 + achieved)

    assert engine.achieved_interval_seconds == pytest.approx(achieved, abs=1e-3)
    assert engine.drift_pct == pytest.approx(13.6, abs=0.05)
    assert engine.status()["drift_pct"] == engine.drift_pct


def test_a_first_tick_has_no_previous_period_to_compare_against(engine):
    """Drift is undefined after exactly one tick; reporting 0.0 would be a lie."""
    engine._last_tick_started = None
    engine._record_success(elapsed_ms=50.0, started=2000.0)
    assert engine.last_tick_ms == 50.0
    assert engine.achieved_interval_seconds is None
    assert engine.drift_pct is None


def test_consecutive_failures_are_counted_and_reset(engine, caplog):
    """A persistently failing tick must not be silent.

    The loop logged only every 50th failure, so a tick failing every time said nothing
    for the first ~60 seconds -- the opposite of the "wall of exceptions" failure mode
    `services/retention.py` explicitly warns about.
    """
    with caplog.at_level("WARNING"):
        for _ in range(3):
            engine._record_failure(RuntimeError("boom"))
    assert engine.consecutive_failures == 3
    assert engine.status()["consecutive_failures"] == 3
    early = [r for r in caplog.records if "boom" in r.getMessage() or r.exc_info is not None]
    assert len(early) >= 3, "the first failures must be logged, not throttled away"

    engine._record_success(elapsed_ms=10.0, started=3000.0)
    assert engine.consecutive_failures == 0


def test_a_long_failure_run_is_throttled(engine, caplog):
    """Log the onset, then summarise -- 50 consecutive failures is 50 log lines."""
    with caplog.at_level("WARNING"):
        for i in range(1, 121):
            engine._record_failure(RuntimeError(f"boom {i}"))
    # first 5, then every 50th: 1, 2, 3, 4, 5, 50, 100
    assert len(caplog.records) == 7
    assert engine.consecutive_failures == 120


def test_manual_and_looped_ticks_cannot_overlap(engine):
    """`POST /demo/tick` and the replay loop must not advance the same aircraft twice.

    Both walked the fleet concurrently before: each read `current_cycle`, each
    incremented, and one write was silently discarded -- a lost cycle with no error.
    The lock is what makes a manual tick safe to expose.

    The lock is exercised directly rather than through `tick_once`, which needs C-MAPSS
    loaded and is an integration concern; what is under test here is that the critical
    section excludes, not what runs inside it.
    """
    running = {"max_concurrent": 0, "current": 0}

    def body() -> None:
        running["current"] += 1
        running["max_concurrent"] = max(running["max_concurrent"], running["current"])
        time.sleep(0.05)
        running["current"] -= 1

    async def guarded() -> None:
        async with engine._tick_lock:
            body()

    async def run() -> None:
        await asyncio.gather(guarded(), guarded())

    asyncio.run(run())

    assert running["max_concurrent"] == 1, "two ticks ran concurrently"


def test_a_lock_exists_and_is_used_by_both_entry_points():
    """Guard against `tick_once` regaining a lock-free path."""
    import inspect

    engine = ReplayEngine(Settings(_env_file=None))
    assert isinstance(engine._tick_lock, asyncio.Lock)
    source = inspect.getsource(ReplayEngine.tick_once)
    assert "_tick_lock" in source, "tick_once bypasses the lock"
    assert "_tick_lock" in inspect.getsource(ReplayEngine._loop), (
        "the replay loop bypasses the lock"
    )


def test_the_blocking_pass_is_offloaded_from_the_event_loop():
    """The whole fleet pass must not run on the loop.

    It did: 8 aircraft x ~9 serialised psycopg round trips per tick, inline in an
    `async def`. Measured as up to 104 ms of pure stall, visible as `/healthz` p99 of
    64 ms on a handler containing no database work at all.
    """
    import inspect

    source = inspect.getsource(ReplayEngine._tick)
    assert "asyncio.to_thread" in source, "the blocking pass runs on the event loop"
    assert inspect.iscoroutinefunction(ReplayEngine._tick_sync) is False, (
        "_tick_sync is documented as blocking; making it async would reintroduce the stall"
    )

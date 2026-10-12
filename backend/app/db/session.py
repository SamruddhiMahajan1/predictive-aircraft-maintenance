"""Database base, session and the unit-of-work transaction boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..core.config import Settings, get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    # `datetime.utcnow` returns a NAIVE datetime. Written into a `timestamptz`
    # column, psycopg sends it without an offset and Postgres interprets it in the
    # *session* TimeZone -- so on a database set to Asia/Kolkata the audit trail was
    # stored 5h30m wrong, while `services/retention.py` (which used an aware
    # datetime) was correct. The two disagreed by exactly the offset.
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), server_default="now()"
    )


_engine: Engine | None = None
_replay_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None
_ReplaySession: sessionmaker[Session] | None = None


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        s = settings or get_settings()
        # Bound the TCP connect so a cold/sleeping managed database fails fast
        # instead of hanging a request (and Render's health check) for the OS
        # default. sqlite has no such parameter, so only send it for Postgres.
        is_postgres = str(s.database_url).startswith(("postgresql", "postgres"))
        connect_args = {"connect_timeout": 5, "application_name": "fdt-api"} if is_postgres else {}
        _engine = create_engine(
            s.database_url,
            echo=s.db_echo,
            pool_pre_ping=True,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            # Without this the default is 30 s, and an exhausted pool fails the
            # request that has waited longest rather than the one that arrived when
            # there was no capacity. See db_pool_timeout in core/config.py.
            pool_timeout=s.db_pool_timeout,
            # Recycle before an intermediary drops an idle connection, so the pool
            # does not hand out a socket that is already closed.
            pool_recycle=s.db_pool_recycle_seconds,
            connect_args=connect_args,
        )
    return _engine


def bound_threadpool(capacity: int | None = None) -> None:
    """Cap anyio's threadpool to the connection pool's size.

    anyio's default is 40 threads, and every sync endpoint plus every
    `asyncio.to_thread` call runs on one. Each thread doing database work holds a
    pooled connection for as long as its query takes. Left at 40 against a pool of
    5+10, the extra 30 threads wait for connections that cannot exist -- so the pool
    reports exhaustion while most of its waiters are not yet running a query. Matching
    the two means requests queue on the pool, where `pool_timeout` applies and the
    failure is reported, rather than queueing invisibly on threads.

    Called from the FastAPI lifespan, where an event loop is running; `get_engine` is
    also called from sync contexts (tests, scripts), where anyio's limiter raises
    rather than returning something adjustable.
    """
    import anyio.to_thread

    limit = capacity or (get_settings().db_pool_size + get_settings().db_max_overflow)
    limiter = anyio.to_thread.current_default_thread_limiter()
    if limiter.total_tokens < limit:
        limiter.total_tokens = limit


def get_sessionmaker(settings: Settings | None = None) -> sessionmaker[Session]:
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(settings), autoflush=False, expire_on_commit=False)
    return _Session


def get_replay_engine(settings: Settings | None = None) -> Engine:
    """Dedicated engine for the replay loop (docs/16 Phase 2.2).

    The replay holds ~2 connections permanently and issues 8 serialised round
    trips per tick on a worker thread. Sharing the request pool meant the
    lightest read endpoint 500ed at 20 concurrent clients; a separate pool
    isolates the steady-state replay load from request bursts. Small on purpose:
    ticks are serialised by `_tick_lock`, so depth > 2 is queue, not throughput.
    """
    global _replay_engine
    if _replay_engine is None:
        s = settings or get_settings()
        is_postgres = str(s.database_url).startswith(("postgresql", "postgres"))
        connect_args = (
            {"connect_timeout": 5, "application_name": "fdt-replay"} if is_postgres else {}
        )
        _replay_engine = create_engine(
            s.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
            pool_timeout=s.db_pool_timeout,
            pool_recycle=s.db_pool_recycle_seconds,
            connect_args=connect_args,
        )
    return _replay_engine


def get_replay_sessionmaker(settings: Settings | None = None) -> sessionmaker[Session]:
    global _ReplaySession
    if _ReplaySession is None:
        _ReplaySession = sessionmaker(
            bind=get_replay_engine(settings), autoflush=False, expire_on_commit=False
        )
    return _ReplaySession


def get_db() -> Iterator[Any]:
    """FastAPI dependency — one session per request, rolled back on error."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()

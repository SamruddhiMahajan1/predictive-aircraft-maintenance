"""Audit table."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.session import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[int | None] = mapped_column()
    actor_name: Mapped[str] = mapped_column(String(48))  # denormalised: survives deletion
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.utcnow())
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        Index("ix_audit_entity", "entity", "entity_id", "at"),
        Index("ix_audit_actor", "actor_id", "at"),
        Index("ix_audit_at", "at"),
    )

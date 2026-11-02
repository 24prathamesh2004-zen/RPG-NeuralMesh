"""ORM models. Replace / extend these with your domain entities.

The example ``Session`` model mirrors the accelerator's session-centric pattern:
each interactive run is a row keyed by ``session_id`` with a JSON ``state`` blob
that holds the agent graph state, plus indexed columns for querying.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Session(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    current_step: Mapped[str] = mapped_column(String(64), default="start")
    # Full agent-graph state, persisted for resume + audit.
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

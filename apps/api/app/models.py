"""SQLAlchemy 2.0 ORM models for StockIt.

The pydantic Plan (apps/api/app/pipeline/schema.py) is the wire/contract
shape; here we persist a serialized snapshot in `Plan.payload` plus a few
indexed columns for filtering (ticker, user_id, generated_at).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    risk_config: Mapped[UserRiskConfig | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class UserRiskConfig(Base):
    __tablename__ = "user_risk_configs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    max_position_pct: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    preferred_llm: Mapped[str] = mapped_column(String(32), nullable=False, default="claude")

    user: Mapped[User] = relationship(back_populates="risk_config")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    capital: Mapped[Any] = mapped_column(Numeric(20, 4), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    revisions: Mapped[list[PlanRevision]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    notes: Mapped[list[Note]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class PlanRevision(Base):
    __tablename__ = "plan_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    diff_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    plan: Mapped[Plan] = relationship(back_populates="revisions")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    last_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    plan: Mapped[Plan] = relationship(back_populates="notes")


class DataCache(Base):
    __tablename__ = "data_cache"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = [
    "Base",
    "DataCache",
    "Note",
    "Plan",
    "PlanRevision",
    "User",
    "UserRiskConfig",
    "WatchlistItem",
]

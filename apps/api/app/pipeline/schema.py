"""Core pydantic v2 schemas for the StockIt pipeline.

Single source of truth for Plan + analyst output shapes. Downstream code
(analysts, synthesizer, risk post-processor, API routes, generated TS types)
binds to these models.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

DecimalStr = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v), return_type=str, when_used="json"),
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


Horizon = Literal["intraday", "swing", "long_term"]
Conviction = Literal["low", "medium", "high"]
EntryKind = Literal["limit", "market", "stop_limit"]
StopKind = Literal["technical", "atr", "fixed_pct"]
ExitKind = Literal["scale_out", "time_stop", "invalidation"]
CatalystKind = Literal["earnings", "macro", "corporate", "other"]
RiskSeverity = Literal["info", "warn"]


class Citation(_Base):
    url: str
    title: str
    source: str
    fetched_at: datetime


class Entry(_Base):
    kind: EntryKind
    levels: list[DecimalStr]
    conditions: str


class Sizing(_Base):
    risk_pct: float = Field(ge=0.0, le=100.0)
    shares: int = Field(ge=0)
    dollar_exposure: DecimalStr
    R_value: DecimalStr  # dollar risk per share


class Stop(_Base):
    price: DecimalStr
    kind: StopKind
    rationale: str


class ExitLevel(_Base):
    kind: ExitKind
    price: DecimalStr | None = None
    trigger: str
    portion: float | None = Field(default=None, ge=0.0, le=1.0)


class Catalyst(_Base):
    date: date
    description: str
    kind: CatalystKind


class RiskFlag(_Base):
    severity: RiskSeverity
    code: str
    message: str


class Plan(_Base):
    ticker: str
    horizon: Horizon
    capital: DecimalStr
    generated_at: datetime
    thesis: str
    conviction: Conviction
    entry: Entry
    sizing: Sizing
    stop: Stop
    exits: list[ExitLevel]
    catalysts: list[Catalyst]
    risk_flags: list[RiskFlag]
    review_cadence: str
    sources: list[Citation]


class AnalystOutput(_Base):
    findings: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    key_metrics: dict[str, Any]
    citations: list[Citation]


__all__ = [
    "AnalystOutput",
    "Catalyst",
    "Citation",
    "Conviction",
    "Entry",
    "EntryKind",
    "ExitKind",
    "ExitLevel",
    "Horizon",
    "Plan",
    "RiskFlag",
    "RiskSeverity",
    "Sizing",
    "Stop",
    "StopKind",
]

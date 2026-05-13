"""Tests for the M5a risk post-processor."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models import UserRiskConfig, WatchlistItem
from app.pipeline.risk import RiskRuleViolation, apply_risk_rules
from app.pipeline.schema import Entry, Plan, Sizing, Stop


def _plan(
    *,
    ticker: str = "ACME",
    entry: Decimal = Decimal("100"),
    stop: Decimal | None = Decimal("95"),
) -> Plan:
    plan = Plan(
        ticker=ticker,
        horizon="swing",
        capital=Decimal("10000"),
        generated_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        thesis="placeholder thesis",
        conviction="medium",
        entry=Entry(kind="limit", levels=[entry], conditions="on pullback"),
        sizing=Sizing(
            risk_pct=1.0,
            shares=0,
            dollar_exposure=Decimal("0"),
            R_value=Decimal("0"),
        ),
        stop=Stop(price=stop or Decimal("0"), kind="technical", rationale="below swing low"),
        exits=[],
        catalysts=[],
        risk_flags=[],
        review_cadence="weekly",
        sources=[],
    )
    if stop is None:
        # model_copy does not re-validate in pydantic v2, so we can simulate
        # the "stop missing" path without bypassing schema construction above.
        plan = plan.model_copy(update={"stop": None})
    return plan


def _risk_config(
    *, risk_per_trade_pct: float = 1.0, max_position_pct: float = 10.0
) -> UserRiskConfig:
    return UserRiskConfig(
        user_id=uuid.uuid4(),
        risk_per_trade_pct=risk_per_trade_pct,
        max_position_pct=max_position_pct,
        preferred_llm="claude",
    )


def _watchlist(ticker: str) -> WatchlistItem:
    return WatchlistItem(id=uuid.uuid4(), user_id=uuid.uuid4(), ticker=ticker)


def test_rule1_missing_stop_raises() -> None:
    with pytest.raises(RiskRuleViolation) as exc:
        apply_risk_rules(
            _plan(stop=None),
            capital=Decimal("10000"),
            risk_config=_risk_config(),
            existing_watchlist=[],
            existing_plans=[],
        )
    assert exc.value.code == "stop_required"


@pytest.mark.parametrize(
    "stop_price",
    [Decimal("100"), Decimal("100.01"), Decimal("120")],
)
def test_rule1_stop_at_or_above_entry_raises(stop_price: Decimal) -> None:
    with pytest.raises(RiskRuleViolation) as exc:
        apply_risk_rules(
            _plan(entry=Decimal("100"), stop=stop_price),
            capital=Decimal("10000"),
            risk_config=_risk_config(),
            existing_watchlist=[],
            existing_plans=[],
        )
    assert exc.value.code == "stop_required"


def test_rule2_r_sizing_math() -> None:
    # capital=10_000, risk_pct=1% -> $100 risk; entry=100 stop=95 -> R=$5; shares=20.
    updated, flags = apply_risk_rules(
        _plan(entry=Decimal("100"), stop=Decimal("95")),
        capital=Decimal("10000"),
        risk_config=_risk_config(risk_per_trade_pct=1.0, max_position_pct=100.0),
        existing_watchlist=[],
        existing_plans=[],
    )
    assert updated.sizing.shares == 20
    assert updated.sizing.R_value == Decimal("5")
    assert updated.sizing.dollar_exposure == Decimal("2000")
    assert updated.sizing.risk_pct == pytest.approx(1.0)
    assert flags == []


def test_rule2_r_sizing_floors_fractional_shares() -> None:
    # capital=10_000, 1% -> $100 risk; entry=100 stop=97 -> R=$3; floor(100/3)=33.
    updated, _ = apply_risk_rules(
        _plan(entry=Decimal("100"), stop=Decimal("97")),
        capital=Decimal("10000"),
        risk_config=_risk_config(max_position_pct=100.0),
        existing_watchlist=[],
        existing_plans=[],
    )
    assert updated.sizing.shares == 33
    assert updated.sizing.dollar_exposure == Decimal("3300")


def test_rule3_sector_concentration_triggers_above_threshold() -> None:
    sectors = {
        "ACME": "tech",
        "AAA": "tech",
        "BBB": "tech",
        "CCC": "tech",
        "DDD": "energy",
    }
    _, flags = apply_risk_rules(
        _plan(ticker="ACME"),
        capital=Decimal("10000"),
        risk_config=_risk_config(max_position_pct=100.0),
        existing_watchlist=[_watchlist("AAA"), _watchlist("BBB")],
        existing_plans=[_plan(ticker="CCC"), _plan(ticker="DDD")],
        sector_lookup=sectors.get,
    )
    codes = [f.code for f in flags]
    assert "sector_concentration" in codes


def test_rule3_sector_concentration_silent_at_threshold() -> None:
    sectors = {"ACME": "tech", "AAA": "tech", "BBB": "tech", "CCC": "energy"}
    _, flags = apply_risk_rules(
        _plan(ticker="ACME"),
        capital=Decimal("10000"),
        risk_config=_risk_config(max_position_pct=100.0),
        existing_watchlist=[_watchlist("AAA"), _watchlist("BBB")],
        existing_plans=[_plan(ticker="CCC")],
        sector_lookup=sectors.get,
    )
    assert [f.code for f in flags] == []


def test_rule4_oversized_position_warn() -> None:
    # capital=10_000, max 5% -> $500 cap; 1% risk, entry=100 stop=95 -> 20 shares = $2_000.
    _, flags = apply_risk_rules(
        _plan(entry=Decimal("100"), stop=Decimal("95")),
        capital=Decimal("10000"),
        risk_config=_risk_config(risk_per_trade_pct=1.0, max_position_pct=5.0),
        existing_watchlist=[],
        existing_plans=[],
    )
    codes = [f.code for f in flags]
    assert "oversized_position" in codes


def test_clean_plan_emits_no_flags_and_preserves_existing() -> None:
    base = _plan(entry=Decimal("100"), stop=Decimal("95"))
    updated, new_flags = apply_risk_rules(
        base,
        capital=Decimal("10000"),
        risk_config=_risk_config(risk_per_trade_pct=1.0, max_position_pct=100.0),
        existing_watchlist=[],
        existing_plans=[],
    )
    assert new_flags == []
    # plan.risk_flags is overwritten with combined list; here that's empty.
    assert updated.risk_flags == []
    # Sizing was overridden (original was zeroed in the factory).
    assert updated.sizing.shares == 20

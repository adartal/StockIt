"""End-to-end pipeline smoke test (AAPL / swing happy path).

This test exercises the full orchestrator with **real** LLM provider(s)
and **real** data fetchers (yfinance / EDGAR / NewsAPI / FRED). It is
gated behind the ``--run-llm`` pytest flag so it never runs in CI by
default.

Run locally with::

    cd apps/api
    uv run pytest tests/test_e2e_pipeline.py --run-llm -s

Requires at least ``ANTHROPIC_API_KEY`` (or ``OPENAI_API_KEY`` /
``GEMINI_API_KEY``) in the environment.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.llm.config import default_router
from app.models import Base, User, UserRiskConfig
from app.pipeline.orchestrator import generate_plan
from app.pipeline.schema import Plan

pytestmark = pytest.mark.llm_e2e


@pytest_asyncio.fixture
async def live_session() -> AsyncIterator[AsyncSession]:
    db_id = uuid.uuid4().hex
    url = (
        f"sqlite+aiosqlite:///file:e2e-{db_id}"
        "?mode=memory&cache=shared&uri=true"
    )
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            user = User(email="e2e@stockit.local")
            s.add(user)
            await s.commit()
            await s.refresh(user)
            risk = UserRiskConfig(user_id=user.id)
            s.add(risk)
            await s.commit()
            await s.refresh(risk)
            yield s
    finally:
        await engine.dispose()


def _has_any_llm_key() -> bool:
    return any(
        os.getenv(name)
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")
    )


@pytest.mark.asyncio
async def test_aapl_swing_happy_path(live_session: AsyncSession) -> None:
    """AAPL/swing → real Plan in <90s with sane sizing + stop math."""
    if not _has_any_llm_key():
        pytest.skip("no LLM API keys set in environment")

    from sqlalchemy import select

    res = await live_session.execute(select(User))
    user = res.scalar_one()
    res = await live_session.execute(
        select(UserRiskConfig).where(UserRiskConfig.user_id == user.id)
    )
    risk = res.scalar_one()

    router = default_router()
    capital = Decimal("10000")

    started = time.monotonic()
    plan = await generate_plan(
        user_id=user.id,
        ticker="AAPL",
        horizon="swing",
        capital=capital,
        risk_config=risk,
        session=live_session,
        llm=router,
    )
    elapsed = time.monotonic() - started

    # Soft latency budget — log but only fail if egregiously slow (3× target).
    assert elapsed < 270, f"pipeline took {elapsed:.1f}s (>3× the 90s target)"
    if elapsed > 90:
        print(f"\n[warn] pipeline took {elapsed:.1f}s (target <90s)\n")

    # Roundtrip through pydantic to assert schema validity.
    Plan.model_validate(plan.model_dump())

    assert plan.ticker == "AAPL"
    assert plan.horizon == "swing"
    assert plan.capital == capital

    # Stop must be below entry for a long.
    entry_price = plan.entry.levels[0]
    assert plan.stop.price < entry_price, (
        f"stop {plan.stop.price} must be below entry {entry_price}"
    )

    # R-based sizing check: shares × (entry − stop) ≈ capital × risk_pct
    r_per_share = entry_price - plan.stop.price
    expected_dollar_risk = capital * Decimal(str(risk.risk_per_trade_pct / 100.0))
    actual_dollar_risk = Decimal(plan.sizing.shares) * r_per_share
    # Allow one share of slack (floor-rounding in the risk module).
    assert abs(actual_dollar_risk - expected_dollar_risk) <= r_per_share, (
        f"R-math off: shares={plan.sizing.shares}, R={r_per_share}, "
        f"expected≈{expected_dollar_risk}, actual={actual_dollar_risk}"
    )

    # Every analyst pillar should have left a trace via sources or thesis.
    assert plan.thesis.strip(), "plan thesis is empty"
    assert plan.review_cadence.strip(), "plan review_cadence is empty"

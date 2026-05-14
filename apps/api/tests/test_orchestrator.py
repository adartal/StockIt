"""Unit tests for the M6 orchestrator with mocked data fetchers + LLM."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import pytest
import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base, User, UserRiskConfig
from app.pipeline import orchestrator
from app.pipeline.data.fundamentals import FundamentalsBundle
from app.pipeline.data.macro import MacroBundle, RateReading
from app.pipeline.data.news import NewsItem
from app.pipeline.schema import AnalystOutput, Citation
from tests.conftest import build_plan


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    db_id = uuid.uuid4().hex
    url = (
        f"sqlite+aiosqlite:///file:orch-{db_id}"
        "?mode=memory&cache=shared&uri=true"
    )
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            user = User(email="orch@test.local")
            s.add(user)
            await s.commit()
            await s.refresh(user)
            yield s
    finally:
        await engine.dispose()


def _ohlcv() -> pd.DataFrame:
    idx = pd.date_range("2026-04-01", periods=30, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "open": range(100, 130),
            "high": range(101, 131),
            "low": range(99, 129),
            "close": range(100, 130),
            "volume": [1_000_000] * 30,
        },
        index=idx,
    )


def _fundamentals() -> FundamentalsBundle:
    return FundamentalsBundle(
        sector="Information Technology",
        industry="Software",
        market_cap=3.0e12,
        pe_ttm=30.0,
    )


def _macro() -> MacroBundle:
    return MacroBundle(
        rates={
            "DGS2": RateReading(latest=4.5, delta_30d=-0.1),
            "DGS10": RateReading(latest=4.2, delta_30d=-0.05),
        },
        vix=15.0,
        sector_etf_ticker="XLK",
        sector_etf_perf_30d=0.02,
        spy_perf_30d=0.01,
    )


class FakeLLM:
    name = "fake"

    def __init__(self) -> None:
        self.calls = 0

    async def complete_structured(
        self,
        messages,
        response_model: type[BaseModel],
        *,
        cache_blocks=None,
        max_retries: int = 1,
    ) -> BaseModel:
        self.calls += 1
        if response_model is AnalystOutput:
            return AnalystOutput(
                findings=["fake finding"],
                confidence=0.5,
                key_metrics={},
                citations=[
                    Citation(
                        url="https://example.com",
                        title="t",
                        source="src",
                        fetched_at=datetime(2026, 5, 13, tzinfo=UTC),
                    )
                ],
            )
        if response_model.__name__ == "_NewsAnalystResponse":
            return response_model(
                findings=["fake news finding"],
                confidence=0.5,
                key_metrics={
                    "sentiment_score": 0.0,
                    "num_items": 1,
                    "dominant_themes": ["x"],
                },
                citations=[
                    Citation(
                        url="https://news.example/x",
                        title="t",
                        source="src",
                        fetched_at=datetime(2026, 5, 13, tzinfo=UTC),
                    )
                ],
            )
        # Synthesizer: return a full Plan.
        return build_plan()


@pytest.mark.asyncio
async def test_generate_plan_happy_path(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ohlcv(*args, **kwargs):
        return _ohlcv()

    async def fake_fundamentals(*args, **kwargs):
        return _fundamentals()

    async def fake_news(*args, **kwargs):
        return [
            NewsItem(
                url="https://news.example/x",
                title="t",
                source="src",
                published_at=datetime(2026, 5, 12, tzinfo=UTC),
            )
        ]

    async def fake_macro(*args, **kwargs):
        return _macro()

    monkeypatch.setattr(orchestrator, "fetch_ohlcv", fake_ohlcv)
    monkeypatch.setattr(orchestrator, "_safe_fetch_fundamentals", fake_fundamentals)
    monkeypatch.setattr(orchestrator, "_safe_fetch_news", fake_news)
    monkeypatch.setattr(orchestrator, "_safe_fetch_macro", fake_macro)

    from sqlalchemy import select
    result = await session.execute(select(User))
    user = result.scalar_one()
    risk = UserRiskConfig(user_id=user.id)
    session.add(risk)
    await session.commit()
    await session.refresh(risk)

    plan = await orchestrator.generate_plan(
        user_id=user.id,
        ticker="AAPL",
        horizon="swing",
        capital=Decimal("10000"),
        risk_config=risk,
        session=session,
        llm=FakeLLM(),
    )
    assert plan.ticker == "AAPL"
    # Risk module overrides sizing — risk per trade = 1%, R = 100 - 95 = 5 →
    # shares = floor(100 / 5) = 20.
    assert plan.sizing.shares == 20

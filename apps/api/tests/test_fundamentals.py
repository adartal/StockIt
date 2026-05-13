"""Tests for the fundamentals fetcher.

Both upstreams (yfinance, edgartools) are mocked. The cache uses a fresh
in-memory SQLite per test, wired in via the same `session_factory`
fixture pattern as the prices tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base, DataCache
from app.pipeline.data import cache as cache_module
from app.pipeline.data import fundamentals as fundamentals_module
from app.pipeline.data.cache import RateLimitError
from app.pipeline.data.fundamentals import FundamentalsBundle, fetch_fundamentals


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    with patch.object(cache_module, "async_session_factory", factory):
        yield factory
    await engine.dispose()


def _sample_yf_info() -> dict[str, Any]:
    return {
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "marketCap": 2_900_000_000_000,
        "trailingPE": 32.5,
        "priceToBook": 48.1,
        "priceToSalesTrailing12Months": 8.4,
        "profitMargins": 0.253,
        "revenueGrowth": 0.061,
        "debtToEquity": 145.2,
        "freeCashflow": 96_000_000_000,
    }


def _sample_edgar_meta(
    *,
    tenk_url: str = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
    tenq_url: str = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000050/aapl-20250329.htm",
    tenq_filed: datetime | None = None,
) -> fundamentals_module._EdgarMeta:
    if tenq_filed is None:
        tenq_filed = datetime(2025, 4, 30, tzinfo=UTC)
    return fundamentals_module._EdgarMeta(
        latest_10k_url=tenk_url,
        latest_10q_url=tenq_url,
        latest_10q_filed_at=tenq_filed,
    )


def _patch_yf_info(info: dict[str, Any]) -> Any:
    ticker_mock = MagicMock()
    ticker_mock.info = info
    return patch(
        "app.pipeline.data.fundamentals.yf.Ticker", return_value=ticker_mock
    )


def _patch_yf_info_raising(exc: BaseException) -> Any:
    ticker_mock = MagicMock()
    type(ticker_mock).info = property(
        lambda self: (_ for _ in ()).throw(exc)
    )
    return patch(
        "app.pipeline.data.fundamentals.yf.Ticker", return_value=ticker_mock
    )


def _patch_edgar(meta: fundamentals_module._EdgarMeta) -> Any:
    return patch(
        "app.pipeline.data.fundamentals._edgar_lookup_sync", return_value=meta
    )


@pytest.mark.asyncio
async def test_fetch_fundamentals_combines_yfinance_and_edgar(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    info = _sample_yf_info()
    meta = _sample_edgar_meta()
    with _patch_yf_info(info), _patch_edgar(meta):
        bundle = await fetch_fundamentals("AAPL")

    assert isinstance(bundle, FundamentalsBundle)
    assert bundle.sector == "Technology"
    assert bundle.industry == "Consumer Electronics"
    assert bundle.market_cap == pytest.approx(2_900_000_000_000)
    assert bundle.pe_ttm == pytest.approx(32.5)
    assert bundle.pb == pytest.approx(48.1)
    assert bundle.ps == pytest.approx(8.4)
    assert bundle.profit_margin == pytest.approx(0.253)
    assert bundle.revenue_growth_yoy == pytest.approx(0.061)
    assert bundle.debt_to_equity == pytest.approx(145.2)
    assert bundle.free_cash_flow_ttm == pytest.approx(96_000_000_000)
    assert bundle.latest_10k_url == meta.latest_10k_url
    assert bundle.latest_10q_url == meta.latest_10q_url
    assert bundle.latest_10q_filed_at == meta.latest_10q_filed_at


@pytest.mark.asyncio
async def test_fetch_fundamentals_second_call_hits_cache(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    info = _sample_yf_info()
    meta = _sample_edgar_meta()
    with _patch_yf_info(info) as yf_mock, _patch_edgar(meta) as edgar_mock:
        first = await fetch_fundamentals("AAPL")
        second = await fetch_fundamentals("AAPL")

        assert yf_mock.call_count == 1
        assert edgar_mock.call_count == 1

    assert first == second
    async with session_factory() as session:
        rows = (await session.execute(select(DataCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "fundamentals"
    assert rows[0].key == "AAPL"


@pytest.mark.asyncio
async def test_fetch_fundamentals_refetches_after_ttl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    info = _sample_yf_info()
    meta = _sample_edgar_meta()
    with _patch_yf_info(info) as yf_mock, _patch_edgar(meta):
        await fetch_fundamentals("AAPL")

        async with session_factory() as session:
            await session.execute(
                update(DataCache).values(
                    fetched_at=datetime.now(UTC) - timedelta(days=2)
                )
            )
            await session.commit()

        await fetch_fundamentals("AAPL")
        assert yf_mock.call_count == 2


@pytest.mark.asyncio
async def test_fetch_fundamentals_handles_partial_yfinance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """yfinance routinely omits PE/PB for unprofitable names — keep going."""
    partial = {
        "sector": "Energy",
        "industry": "Oil & Gas E&P",
        "marketCap": 12_000_000_000,
        "trailingPE": None,
        "profitMargins": float("nan"),
        "freeCashflow": "not-a-number",
    }
    with _patch_yf_info(partial), _patch_edgar(_sample_edgar_meta()):
        bundle = await fetch_fundamentals("XOM")

    assert bundle.sector == "Energy"
    assert bundle.market_cap == pytest.approx(12_000_000_000)
    assert bundle.pe_ttm is None
    assert bundle.pb is None
    assert bundle.profit_margin is None  # NaN dropped
    assert bundle.free_cash_flow_ttm is None  # un-coercible string dropped


@pytest.mark.asyncio
async def test_fetch_fundamentals_survives_edgar_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If EDGAR errors out, we still return the yfinance half."""
    with _patch_yf_info(_sample_yf_info()), _patch_edgar(
        fundamentals_module._EdgarMeta()
    ):
        bundle = await fetch_fundamentals("AAPL")

    assert bundle.sector == "Technology"
    assert bundle.latest_10k_url is None
    assert bundle.latest_10q_url is None
    assert bundle.latest_10q_filed_at is None


@pytest.mark.asyncio
async def test_fetch_fundamentals_yfinance_rate_limit_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """First call: no stale entry, RateLimitError propagates."""
    with _patch_yf_info_raising(
        RuntimeError("HTTP 429 Too Many Requests")
    ), _patch_edgar(_sample_edgar_meta()), pytest.raises(RateLimitError):
        await fetch_fundamentals("AAPL")


@pytest.mark.asyncio
async def test_fetch_fundamentals_serves_stale_on_rate_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    info = _sample_yf_info()
    meta = _sample_edgar_meta()
    with _patch_yf_info(info), _patch_edgar(meta):
        first = await fetch_fundamentals("AAPL")

    async with session_factory() as session:
        await session.execute(
            update(DataCache).values(
                fetched_at=datetime.now(UTC) - timedelta(days=2)
            )
        )
        await session.commit()

    with _patch_yf_info_raising(RuntimeError("HTTP 429")), _patch_edgar(meta):
        stale = await fetch_fundamentals("AAPL")

    assert stale == first


@pytest.mark.asyncio
async def test_fetch_fundamentals_normalizes_ticker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    info = _sample_yf_info()
    with _patch_yf_info(info), _patch_edgar(_sample_edgar_meta()):
        await fetch_fundamentals("  aapl ")

    async with session_factory() as session:
        rows = (await session.execute(select(DataCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].key == "AAPL"


@pytest.mark.asyncio
async def test_fetch_fundamentals_empty_ticker_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(ValueError):
        await fetch_fundamentals("   ")


def test_edgar_lookup_handles_filing_objects() -> None:
    """`_edgar_lookup_sync` extracts URL + date from edgartools-shaped objects."""

    class FakeFiling:
        def __init__(self, url: str, filed: date) -> None:
            self.filing_url = url
            self.filing_date = filed

    class FakeFilings:
        def __init__(self, filing: FakeFiling) -> None:
            self._filing = filing

        def latest(self) -> FakeFiling:
            return self._filing

    class FakeCompany:
        def __init__(self, ticker: str) -> None:
            self.ticker = ticker

        def get_filings(self, form: str) -> FakeFilings:
            if form == "10-K":
                return FakeFilings(
                    FakeFiling("https://sec.gov/10k.htm", date(2024, 9, 28))
                )
            return FakeFilings(
                FakeFiling("https://sec.gov/10q.htm", date(2025, 3, 29))
            )

    fake_edgar = MagicMock()
    fake_edgar.Company = FakeCompany
    fake_edgar.set_identity = MagicMock()
    with patch.dict(
        "sys.modules", {"edgar": fake_edgar}
    ):
        meta = fundamentals_module._edgar_lookup_sync("AAPL")

    assert meta.latest_10k_url == "https://sec.gov/10k.htm"
    assert meta.latest_10q_url == "https://sec.gov/10q.htm"
    assert meta.latest_10q_filed_at == datetime(2025, 3, 29, tzinfo=UTC)
    fake_edgar.set_identity.assert_called_once()


def test_edgar_lookup_handles_missing_module() -> None:
    """When edgartools isn't installed, return empty meta — don't crash."""
    with patch.dict("sys.modules", {"edgar": None}):
        meta = fundamentals_module._edgar_lookup_sync("AAPL")
    assert meta == fundamentals_module._EdgarMeta()

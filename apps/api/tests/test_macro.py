"""Tests for the macro fetcher.

FRED is mocked via the `_make_fred` injection point in `macro.py`;
yfinance is mocked via `yf.download`. The cache backing store is a
fresh in-memory SQLite per test, wired in by patching the session
factory that `Cached` reads.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base, DataCache
from app.pipeline.data import cache as cache_module
from app.pipeline.data.macro import (
    SECTOR_TO_ETF,
    MacroBundle,
    fetch_macro_context,
)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    with patch.object(cache_module, "async_session_factory", factory):
        yield factory
    await engine.dispose()


def _fred_series(prior_value: float, latest_value: float) -> pd.Series:
    """60 daily points ending 2026-05-12; first 30 are `prior_value`,
    next 30 are `latest_value`. With this layout `latest_ts - 30d` lands
    inside the `prior_value` block, giving a predictable delta."""
    idx = pd.date_range(end="2026-05-12", periods=60, freq="D")
    values = [prior_value] * 30 + [latest_value] * 30
    return pd.Series(values, index=idx, dtype=float)


def _yf_frame(prior_close: float, latest_close: float) -> pd.DataFrame:
    """45 daily bars ending 2026-05-12; first 30 closes are `prior_close`,
    next 15 are `latest_close`. `latest_ts - 30d` lands ~15 bars from the
    end, i.e. inside the `prior_close` block."""
    idx = pd.date_range(end="2026-05-12", periods=45, freq="D", tz="UTC")
    closes = [prior_close] * 30 + [latest_close] * 15
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def _flat_yf_frame(close: float) -> pd.DataFrame:
    idx = pd.date_range(end="2026-05-12", periods=45, freq="D", tz="UTC")
    closes = [close] * 45
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def _fake_fred(
    *,
    dgs2_prior: float = 4.7,
    dgs2_latest: float = 4.5,
    dgs10_prior: float = 4.0,
    dgs10_latest: float = 4.1,
) -> MagicMock:
    fake = MagicMock()

    def _get_series(name: str, *args: Any, **kwargs: Any) -> pd.Series:
        if name == "DGS2":
            return _fred_series(dgs2_prior, dgs2_latest)
        if name == "DGS10":
            return _fred_series(dgs10_prior, dgs10_latest)
        raise AssertionError(f"unexpected FRED series: {name}")

    fake.get_series.side_effect = _get_series
    return fake


@pytest.mark.asyncio
async def test_fetch_macro_context_populates_bundle(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    fake = _fake_fred()

    vix_frame = _yf_frame(prior_close=18.0, latest_close=20.0)
    xlk_frame = _yf_frame(prior_close=100.0, latest_close=110.0)
    spy_frame = _yf_frame(prior_close=400.0, latest_close=420.0)

    with (
        patch("app.pipeline.data.macro._make_fred", return_value=fake),
        patch(
            "app.pipeline.data.macro.yf.download",
            side_effect=[vix_frame, xlk_frame, spy_frame],
        ),
    ):
        bundle = await fetch_macro_context("Information Technology")

    assert isinstance(bundle, MacroBundle)
    assert bundle.sector_etf_ticker == "XLK"
    assert bundle.vix == pytest.approx(20.0)
    assert bundle.sector_etf_perf_30d == pytest.approx(0.10)
    assert bundle.spy_perf_30d == pytest.approx(0.05)
    assert bundle.rates["DGS2"].latest == pytest.approx(4.5)
    assert bundle.rates["DGS2"].delta_30d == pytest.approx(-0.2)
    assert bundle.rates["DGS10"].latest == pytest.approx(4.1)
    assert bundle.rates["DGS10"].delta_30d == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_fetch_macro_context_caches_second_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    fake = _fake_fred()

    frames = [
        _yf_frame(18.0, 20.0),
        _yf_frame(100.0, 110.0),
        _yf_frame(400.0, 420.0),
    ]

    with (
        patch("app.pipeline.data.macro._make_fred", return_value=fake) as fred_mock,
        patch("app.pipeline.data.macro.yf.download", side_effect=frames) as yf_mock,
    ):
        first = await fetch_macro_context("Information Technology")
        second = await fetch_macro_context("Information Technology")

    assert first == second
    assert yf_mock.call_count == 3
    assert fred_mock.call_count == 1

    async with session_factory() as session:
        rows = (await session.execute(select(DataCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "macro"
    assert rows[0].key == "Information Technology"


@pytest.mark.asyncio
async def test_fetch_macro_context_separate_keys_per_sector(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "fake-key")
    fake = _fake_fred()

    frames = [
        _flat_yf_frame(20.0),
        _flat_yf_frame(100.0),
        _flat_yf_frame(400.0),
        _flat_yf_frame(20.0),
        _flat_yf_frame(50.0),
        _flat_yf_frame(400.0),
    ]

    with (
        patch("app.pipeline.data.macro._make_fred", return_value=fake),
        patch("app.pipeline.data.macro.yf.download", side_effect=frames),
    ):
        tech = await fetch_macro_context("Information Technology")
        energy = await fetch_macro_context("Energy")

    assert tech.sector_etf_ticker == "XLK"
    assert energy.sector_etf_ticker == "XLE"

    async with session_factory() as session:
        rows = (await session.execute(select(DataCache))).scalars().all()
    keys = {(r.source, r.key) for r in rows}
    assert keys == {("macro", "Information Technology"), ("macro", "Energy")}


@pytest.mark.asyncio
async def test_fetch_macro_context_unknown_sector_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(ValueError, match="unknown GICS sector"):
        await fetch_macro_context("Crypto")


@pytest.mark.asyncio
async def test_fetch_macro_context_missing_fred_key_raises(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with patch(
        "app.pipeline.data.macro.yf.download",
        return_value=_flat_yf_frame(100.0),
    ):
        with pytest.raises(RuntimeError, match="FRED_API_KEY"):
            await fetch_macro_context("Information Technology")


@pytest.mark.asyncio
async def test_fetch_macro_context_empty_vix_raises(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    empty = pd.DataFrame()
    frames = [empty, _flat_yf_frame(100.0), _flat_yf_frame(400.0)]
    with (
        patch("app.pipeline.data.macro._make_fred", return_value=_fake_fred()),
        patch("app.pipeline.data.macro.yf.download", side_effect=frames),
    ):
        with pytest.raises(RuntimeError, match="VIX close series unavailable"):
            await fetch_macro_context("Information Technology")


def test_sector_map_covers_eleven_gics_sectors() -> None:
    """All 11 GICS L1 sectors are mapped; ETF tickers are unique."""
    expected_sectors = {
        "Information Technology",
        "Health Care",
        "Financials",
        "Consumer Discretionary",
        "Communication Services",
        "Industrials",
        "Consumer Staples",
        "Energy",
        "Utilities",
        "Real Estate",
        "Materials",
    }
    assert set(SECTOR_TO_ETF) == expected_sectors
    assert len(set(SECTOR_TO_ETF.values())) == len(SECTOR_TO_ETF)

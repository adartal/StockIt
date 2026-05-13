"""Tests for the prices fetcher + shared Cached wrapper.

yfinance and Alpha Vantage are both mocked. The cache backing store is a
fresh in-memory SQLite per test, wired in by monkeypatching the session
factory that `Cached` imports at module load.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import pandas as pd
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base, DataCache
from app.pipeline.data import cache as cache_module
from app.pipeline.data.cache import Cached, RateLimitError
from app.pipeline.data.prices import fetch_ohlcv


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    with patch.object(cache_module, "async_session_factory", factory):
        yield factory
    await engine.dispose()


def _sample_yf_frame(rows: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-05-01", periods=rows, freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(rows)],
            "High": [101.0 + i for i in range(rows)],
            "Low": [99.0 + i for i in range(rows)],
            "Close": [100.5 + i for i in range(rows)],
            "Volume": [1_000_000 + i * 1000 for i in range(rows)],
        },
        index=idx,
    )
    return df


def _patch_yf_download(returning: pd.DataFrame | Callable[..., pd.DataFrame]) -> Any:
    if callable(returning):
        return patch("app.pipeline.data.prices.yf.download", side_effect=returning)
    return patch("app.pipeline.data.prices.yf.download", return_value=returning)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.asyncio
async def test_fetch_ohlcv_normalizes_yfinance_frame(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw = _sample_yf_frame()
    with _patch_yf_download(raw):
        df = await fetch_ohlcv("AAPL", "1d", 30)

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    idx = cast(pd.DatetimeIndex, df.index)
    assert idx.tz is not None and str(idx.tz) == "UTC"
    assert idx.name == "timestamp"
    assert len(df) == 5
    assert df.iloc[0]["open"] == 100.0


@pytest.mark.asyncio
async def test_fetch_ohlcv_second_call_hits_cache(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw = _sample_yf_frame()
    with _patch_yf_download(raw) as mocked:
        first = await fetch_ohlcv("AAPL", "1d", 30)
        second = await fetch_ohlcv("AAPL", "1d", 30)
        assert mocked.call_count == 1

    pd.testing.assert_frame_equal(first, second, check_dtype=False)

    async with session_factory() as session:
        rows = (await session.execute(select(DataCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "yfinance"


@pytest.mark.asyncio
async def test_fetch_ohlcv_refetches_when_cache_expired(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw = _sample_yf_frame()
    with _patch_yf_download(raw) as mocked:
        await fetch_ohlcv("AAPL", "1d", 30)

        async with session_factory() as session:
            row = (await session.execute(select(DataCache))).scalars().first()
            assert row is not None
            await session.execute(
                update(DataCache).values(
                    fetched_at=datetime.now(UTC) - timedelta(days=2)
                )
            )
            await session.commit()

        await fetch_ohlcv("AAPL", "1d", 30)
        assert mocked.call_count == 2


@pytest.mark.asyncio
async def test_fetch_ohlcv_yfinance_429_without_fallback_propagates(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)

    def _raise(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise RuntimeError("HTTP 429 Too Many Requests")

    with _patch_yf_download(_raise), pytest.raises(RateLimitError):
        await fetch_ohlcv("AAPL", "1d", 30)


@pytest.mark.asyncio
async def test_fetch_ohlcv_intraday_falls_back_to_alpha_vantage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")

    def _raise(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise RuntimeError("Yahoo blocked request: 429")

    av_payload = {
        "Meta Data": {"1. Information": "Intraday (5min)"},
        "Time Series (5min)": {
            "2026-05-12 19:55:00": {
                "1. open": "182.10",
                "2. high": "182.40",
                "3. low": "182.00",
                "4. close": "182.30",
                "5. volume": "12345",
            },
            "2026-05-12 19:50:00": {
                "1. open": "181.80",
                "2. high": "182.20",
                "3. low": "181.75",
                "4. close": "182.10",
                "5. volume": "8765",
            },
        },
    }

    async def _fake_av(self_client: Any, url: str, params: dict[str, Any]) -> Any:
        return _FakeResponse(av_payload)

    with _patch_yf_download(_raise), patch(
        "httpx.AsyncClient.get", new=_fake_av
    ):
        df = await fetch_ohlcv("AAPL", "5m", 7)

    assert len(df) == 2
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.iloc[0]["close"] == pytest.approx(182.10)


@pytest.mark.asyncio
async def test_fetch_ohlcv_serves_stale_on_rate_limit(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)

    raw = _sample_yf_frame()
    with _patch_yf_download(raw):
        first = await fetch_ohlcv("AAPL", "1d", 30)

    async with session_factory() as session:
        await session.execute(
            update(DataCache).values(
                fetched_at=datetime.now(UTC) - timedelta(days=2)
            )
        )
        await session.commit()

    def _raise(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise RuntimeError("HTTP 429")

    with _patch_yf_download(_raise):
        stale = await fetch_ohlcv("AAPL", "1d", 30)

    pd.testing.assert_frame_equal(first, stale, check_dtype=False)


@pytest.mark.asyncio
async def test_fetch_ohlcv_empty_intraday_uses_alpha_vantage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")

    empty = pd.DataFrame()
    av_payload = {
        "Time Series (1min)": {
            "2026-05-12 19:59:00": {
                "1. open": "182.10",
                "2. high": "182.40",
                "3. low": "182.00",
                "4. close": "182.30",
                "5. volume": "12345",
            },
        },
    }

    async def _fake_av(self_client: Any, url: str, params: dict[str, Any]) -> Any:
        return _FakeResponse(av_payload)

    with _patch_yf_download(empty), patch("httpx.AsyncClient.get", new=_fake_av):
        df = await fetch_ohlcv("AAPL", "1m", 1)

    assert len(df) == 1


@pytest.mark.asyncio
async def test_cached_serializes_and_deserializes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Direct Cached check — values round-trip through DataCache."""

    cache: Cached[dict[str, int]] = Cached(source="unit", ttl_seconds=60)

    calls = 0

    async def fetcher() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"n": 42}

    first = await cache.fetch(key="x", fetcher=fetcher)
    second = await cache.fetch(key="x", fetcher=fetcher)
    assert first == {"n": 42}
    assert second == {"n": 42}
    assert calls == 1


@pytest.mark.asyncio
async def test_cached_rate_limit_without_cache_reraises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cache: Cached[dict[str, int]] = Cached(source="unit", ttl_seconds=60)

    async def fetcher() -> dict[str, int]:
        raise RateLimitError("nope")

    with pytest.raises(RateLimitError):
        await cache.fetch(key="x", fetcher=fetcher)


def test_event_loop_smoke() -> None:
    """Sanity: pytest-asyncio is wired up."""
    assert asyncio.iscoroutinefunction(fetch_ohlcv)

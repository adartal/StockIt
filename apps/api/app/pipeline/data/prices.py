"""OHLCV price fetching for the StockIt pipeline.

Primary source: yfinance (no API key, scrapes Yahoo Finance). For
intraday intervals (1m/5m) where yfinance is unreliable — see
docs/m2-data-source-survey.md for the rate-limit/blocking history — we
fall back to Alpha Vantage when `ALPHAVANTAGE_API_KEY` is set.

Everything routes through `Cached` so repeat calls within the TTL hit
the `data_cache` table instead of the upstream provider. TTLs are tight
for fresh intervals (60s for 1m bars) and generous for slow-moving ones
(1 day for daily/weekly).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import httpx
import pandas as pd
import yfinance as yf

from app.pipeline.data.cache import Cached, RateLimitError

logger = logging.getLogger(__name__)

Interval = Literal["1m", "5m", "1h", "1d", "1wk"]

_TTL_BY_INTERVAL: dict[Interval, int] = {
    "1m": 60,
    "5m": 300,
    "1h": 3600,
    "1d": 86400,
    "1wk": 86400,
}

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


async def fetch_ohlcv(
    ticker: str,
    interval: Interval,
    lookback_days: int,
) -> pd.DataFrame:
    """Fetch OHLCV bars for `ticker` over the last `lookback_days`.

    Returns a DataFrame indexed by UTC timestamp with columns
    `open, high, low, close, volume`. Empty DataFrame (same shape) if
    the upstream has no data for the symbol/interval.

    For 1m/5m bars, falls back to Alpha Vantage on yfinance rate-limit
    when `ALPHAVANTAGE_API_KEY` is set in env.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if interval not in _TTL_BY_INTERVAL:
        raise ValueError(f"unsupported interval: {interval!r}")

    key = f"{ticker}:{interval}:{lookback_days}"
    ttl = _TTL_BY_INTERVAL[interval]

    yf_cache = Cached[pd.DataFrame](
        source="yfinance",
        ttl_seconds=ttl,
        serialize=_df_to_payload,
        deserialize=_df_from_payload,
    )

    try:
        df = await yf_cache.fetch(
            key=key,
            fetcher=lambda: _fetch_yfinance(ticker, interval, lookback_days),
        )
    except RateLimitError:
        if interval in ("1m", "5m") and os.getenv("ALPHAVANTAGE_API_KEY"):
            logger.warning(
                "yfinance rate-limited for %s %s; falling back to Alpha Vantage",
                ticker,
                interval,
            )
            return await _fetch_via_alpha_vantage(ticker, interval, lookback_days, ttl)
        raise

    if df.empty and interval in ("1m", "5m") and os.getenv("ALPHAVANTAGE_API_KEY"):
        logger.info(
            "yfinance returned empty for %s %s; trying Alpha Vantage",
            ticker,
            interval,
        )
        return await _fetch_via_alpha_vantage(ticker, interval, lookback_days, ttl)

    return df


async def _fetch_via_alpha_vantage(
    ticker: str,
    interval: Interval,
    lookback_days: int,
    ttl_seconds: int,
) -> pd.DataFrame:
    av_cache = Cached[pd.DataFrame](
        source="alpha_vantage",
        ttl_seconds=ttl_seconds,
        serialize=_df_to_payload,
        deserialize=_df_from_payload,
    )
    return await av_cache.fetch(
        key=f"{ticker}:{interval}:{lookback_days}",
        fetcher=lambda: _fetch_alpha_vantage(ticker, interval, lookback_days),
    )


async def _fetch_yfinance(
    ticker: str,
    interval: Interval,
    lookback_days: int,
) -> pd.DataFrame:
    """Pull OHLCV from yfinance. Runs the sync call in a thread."""
    period_or_dates = _yf_period_args(interval, lookback_days)

    def _call() -> pd.DataFrame:
        try:
            raw = yf.download(
                ticker,
                interval=interval,
                progress=False,
                auto_adjust=False,
                threads=False,
                **period_or_dates,
            )
        except Exception as exc:  # noqa: BLE001
            if _looks_like_rate_limit(exc):
                raise RateLimitError(str(exc)) from exc
            raise
        return _normalize_yf_frame(raw)

    return await asyncio.to_thread(_call)


def _yf_period_args(interval: Interval, lookback_days: int) -> dict[str, Any]:
    """yfinance limits intraday lookbacks; clamp + translate to start/end."""
    end = datetime.now(UTC)
    if interval == "1m":
        lookback_days = min(lookback_days, 7)
    elif interval == "5m":
        lookback_days = min(lookback_days, 59)
    elif interval == "1h":
        lookback_days = min(lookback_days, 729)
    start = end - timedelta(days=lookback_days)
    return {"start": start.date().isoformat(), "end": end.date().isoformat()}


def _normalize_yf_frame(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return _empty_ohlcv()

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns = [str(c).lower() for c in df.columns]
    missing = [c for c in _OHLCV_COLUMNS if c not in df.columns]
    if missing:
        logger.warning("yfinance frame missing columns: %s", missing)
        return _empty_ohlcv()
    df = df[_OHLCV_COLUMNS]

    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"
    return df


async def _fetch_alpha_vantage(
    ticker: str,
    interval: Interval,
    lookback_days: int,
) -> pd.DataFrame:
    api_key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY not set")
    if interval not in ("1m", "5m"):
        raise ValueError(f"alpha vantage path is intraday-only, got {interval}")

    av_interval = "1min" if interval == "1m" else "5min"
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": ticker,
        "interval": av_interval,
        "outputsize": "full",
        "apikey": api_key,
        "datatype": "json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get("https://www.alphavantage.co/query", params=params)
        resp.raise_for_status()
        payload = resp.json()

    if "Note" in payload or "Information" in payload:
        raise RateLimitError(payload.get("Note") or payload.get("Information") or "throttled")
    if "Error Message" in payload:
        raise RuntimeError(f"alpha vantage error: {payload['Error Message']}")

    series_key = f"Time Series ({av_interval})"
    series = payload.get(series_key)
    if not series:
        return _empty_ohlcv()

    df = pd.DataFrame.from_dict(series, orient="index")
    df = df.rename(
        columns={
            "1. open": "open",
            "2. high": "high",
            "3. low": "low",
            "4. close": "close",
            "5. volume": "volume",
        }
    )
    df = df[_OHLCV_COLUMNS].astype(float)
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"
    df = df.sort_index()

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    df = df[df.index >= cutoff]
    return df


def _looks_like_rate_limit(exc: BaseException) -> bool:
    cls_name = type(exc).__name__.lower()
    if "ratelimit" in cls_name:
        return True
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


def _df_to_payload(df: pd.DataFrame) -> dict[str, Any]:
    """JSON-friendly view of an OHLCV frame. Index → ISO8601 strings."""
    if df.empty:
        return {"index": [], "columns": list(_OHLCV_COLUMNS), "data": []}
    idx_iso = [ts.isoformat() for ts in cast(pd.DatetimeIndex, df.index)]
    return {
        "index": idx_iso,
        "columns": list(df.columns),
        "data": df.astype(float).values.tolist(),
    }


def _df_from_payload(payload: dict[str, Any]) -> pd.DataFrame:
    if not payload.get("index"):
        return _empty_ohlcv()
    df = pd.DataFrame(
        data=payload["data"],
        columns=payload["columns"],
        index=pd.to_datetime(payload["index"], utc=True),
    )
    df.index.name = "timestamp"
    return df


def _empty_ohlcv() -> pd.DataFrame:
    df = pd.DataFrame(columns=_OHLCV_COLUMNS, dtype=float)
    df.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return df


__all__ = ["Interval", "fetch_ohlcv"]

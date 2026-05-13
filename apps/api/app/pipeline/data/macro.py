"""Macro context fetcher: treasury rates, VIX, sector vs market performance.

Pulls a `MacroBundle` for a given GICS sector, used downstream by the
macro analyst. Treasury yields come from FRED (DGS2 + DGS10) via
`fredapi`; VIX and the sector/SPY ETF closes come from yfinance.

The 30-day "delta" / "perf" fields are computed off the most recent
observation versus the most recent observation on-or-before
(latest - 30 days). For rates this is an absolute delta in percentage
points; for ETFs it's a fractional return.

Everything is wrapped in `Cached` (TTL 1h, source="macro"). The cache
key is the sector name — macro context is the same for every ticker in
a sector.

`fredapi` is imported lazily inside `_make_fred()` so the module loads
without the package installed; tests monkeypatch `_make_fred` to inject
a fake. The lookup needs `FRED_API_KEY` set in env at fetch time.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from pydantic import BaseModel

from app.pipeline.data.cache import Cached

logger = logging.getLogger(__name__)

# GICS L1 sectors → State Street SPDR sector ETF.
# Yahoo/FactSet style sector strings; matches what yfinance returns
# under `Ticker(...).info["sector"]`.
SECTOR_TO_ETF: dict[str, str] = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}

_TTL_SECONDS = 3600
_LOOKBACK_DAYS = 45
_RATE_SERIES = ("DGS2", "DGS10")


class RateReading(BaseModel):
    """One FRED treasury series, summarized."""

    latest: float
    delta_30d: float


class MacroBundle(BaseModel):
    """Macro context snapshot for one GICS sector."""

    rates: dict[str, RateReading]
    vix: float
    sector_etf_ticker: str
    sector_etf_perf_30d: float
    spy_perf_30d: float


async def fetch_macro_context(sector: str) -> MacroBundle:
    """Return a `MacroBundle` for the given GICS sector name.

    Raises `ValueError` if `sector` is not one of the 11 GICS L1 sectors
    in `SECTOR_TO_ETF`. Raises `RuntimeError` if `FRED_API_KEY` is unset
    or upstream calls return empty series.
    """
    if sector not in SECTOR_TO_ETF:
        raise ValueError(
            f"unknown GICS sector: {sector!r}; "
            f"expected one of {sorted(SECTOR_TO_ETF)}"
        )
    etf = SECTOR_TO_ETF[sector]

    cache = Cached[MacroBundle](
        source="macro",
        ttl_seconds=_TTL_SECONDS,
        serialize=lambda b: b.model_dump(mode="json"),
        deserialize=lambda d: MacroBundle.model_validate(d),
    )
    return await cache.fetch(
        key=sector,
        fetcher=lambda: _build_macro_bundle(etf),
    )


async def _build_macro_bundle(etf: str) -> MacroBundle:
    rates, quotes = await asyncio.gather(
        asyncio.to_thread(_fetch_treasury_rates),
        asyncio.to_thread(_fetch_yf_quotes, etf),
    )
    return MacroBundle(
        rates=rates,
        vix=quotes["vix"],
        sector_etf_ticker=etf,
        sector_etf_perf_30d=quotes["etf_perf"],
        spy_perf_30d=quotes["spy_perf"],
    )


def _make_fred(api_key: str) -> Any:
    """Lazy fredapi import; patched in tests."""
    from fredapi import Fred  # type: ignore[import-not-found]

    return Fred(api_key=api_key)


def _fetch_treasury_rates() -> dict[str, RateReading]:
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY must be set to fetch macro rates")
    fred = _make_fred(api_key)

    out: dict[str, RateReading] = {}
    for series_id in _RATE_SERIES:
        raw = fred.get_series(series_id)
        series = pd.Series(raw).dropna()
        if series.empty:
            raise RuntimeError(f"FRED series {series_id} returned no data")
        series = series.sort_index()
        latest = float(series.iloc[-1])
        prior = _value_on_or_before(series, _offset_30d(series.index[-1]))
        out[series_id] = RateReading(latest=latest, delta_30d=latest - prior)
    return out


def _fetch_yf_quotes(etf: str) -> dict[str, float]:
    end = datetime.now(UTC)
    start = end - timedelta(days=_LOOKBACK_DAYS)
    args: dict[str, Any] = {
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "interval": "1d",
        "progress": False,
        "auto_adjust": False,
        "threads": False,
    }
    vix_close = _close_series(yf.download("^VIX", **args))
    etf_close = _close_series(yf.download(etf, **args))
    spy_close = _close_series(yf.download("SPY", **args))

    if vix_close.empty:
        raise RuntimeError("VIX close series unavailable")
    if etf_close.empty:
        raise RuntimeError(f"sector ETF {etf} close series unavailable")
    if spy_close.empty:
        raise RuntimeError("SPY close series unavailable")

    return {
        "vix": float(vix_close.iloc[-1]),
        "etf_perf": _perf_30d(etf_close),
        "spy_perf": _perf_30d(spy_close),
    }


def _close_series(raw: pd.DataFrame) -> pd.Series:
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    if "close" not in df.columns:
        return pd.Series(dtype=float)
    series = df["close"].dropna()
    series = series.sort_index()
    return series


def _perf_30d(series: pd.Series) -> float:
    latest = float(series.iloc[-1])
    prior = _value_on_or_before(series, _offset_30d(series.index[-1]))
    if prior == 0:
        return 0.0
    return (latest - prior) / prior


def _value_on_or_before(series: pd.Series, cutoff: Any) -> float:
    """Last value at index <= cutoff; falls back to oldest value."""
    prior = series[series.index <= cutoff]
    if not prior.empty:
        return float(prior.iloc[-1])
    return float(series.iloc[0])


def _offset_30d(latest_ts: Any) -> Any:
    return latest_ts - pd.Timedelta(days=30)


__all__ = [
    "SECTOR_TO_ETF",
    "MacroBundle",
    "RateReading",
    "fetch_macro_context",
]

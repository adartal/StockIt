"""Fundamentals fetcher for the StockIt pipeline.

Combines two upstreams behind a single 24h-TTL cached entry:

  * **yfinance** for fast valuation/quality metrics (PE, PB, margins,
    growth, FCF). Cheap and convenient but unreliable — see
    docs/m2-data-source-survey.md for the rate-limit / blocking history.
  * **edgartools** for the latest 10-K / 10-Q *metadata* (filing URL and
    date). The SEC enforces 10 req/sec; edgartools auto-throttles. We
    deliberately do NOT parse filing contents here — that's the analyst
    stage's job (M4a) if it needs full text.

Fundamentals change at most quarterly, so a 24h TTL is generous but safe.
On yfinance rate-limit, `Cached` will serve the prior bundle stale (see
`stale_extension_seconds` in cache.py).

A partial bundle (yfinance ok, EDGAR fails, or vice-versa) is preferred
over a hard failure — downstream analysts handle missing fields.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, date, datetime
from typing import Any

import yfinance as yf
from pydantic import BaseModel

from app.pipeline.data.cache import Cached, RateLimitError

logger = logging.getLogger(__name__)

_TTL_SECONDS = 86_400  # 24h

_DEFAULT_EDGAR_IDENTITY = "StockIt research@stockit.local"


class FundamentalsBundle(BaseModel):
    """Snapshot of valuation/quality metrics + latest SEC filing pointers.

    Every field is optional: upstreams routinely omit metrics (e.g. PE is
    `None` for unprofitable names) and EDGAR may not have a recent filing
    for non-US tickers.
    """

    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    ps: float | None = None
    profit_margin: float | None = None
    revenue_growth_yoy: float | None = None
    debt_to_equity: float | None = None
    free_cash_flow_ttm: float | None = None
    latest_10k_url: str | None = None
    latest_10q_url: str | None = None
    latest_10q_filed_at: datetime | None = None


async def fetch_fundamentals(ticker: str) -> FundamentalsBundle:
    """Fetch (or return cached) fundamentals for `ticker`.

    Wrapped in `Cached` with a 24h TTL keyed on the upper-cased ticker.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")

    cache = Cached[FundamentalsBundle](
        source="fundamentals",
        ttl_seconds=_TTL_SECONDS,
        serialize=lambda b: b.model_dump(mode="json"),
        deserialize=lambda raw: FundamentalsBundle.model_validate(raw),
    )
    return await cache.fetch(
        key=ticker,
        fetcher=lambda: _fetch_fundamentals(ticker),
    )


async def _fetch_fundamentals(ticker: str) -> FundamentalsBundle:
    yf_info, edgar_meta = await asyncio.gather(
        _fetch_yfinance_info(ticker),
        _fetch_edgar_metadata(ticker),
    )
    return FundamentalsBundle(
        sector=_get_str(yf_info, "sector"),
        industry=_get_str(yf_info, "industry"),
        market_cap=_get_float(yf_info, "marketCap"),
        pe_ttm=_get_float(yf_info, "trailingPE"),
        pb=_get_float(yf_info, "priceToBook"),
        ps=_get_float(yf_info, "priceToSalesTrailing12Months"),
        profit_margin=_get_float(yf_info, "profitMargins"),
        revenue_growth_yoy=_get_float(yf_info, "revenueGrowth"),
        debt_to_equity=_get_float(yf_info, "debtToEquity"),
        free_cash_flow_ttm=_get_float(yf_info, "freeCashflow"),
        latest_10k_url=edgar_meta.latest_10k_url,
        latest_10q_url=edgar_meta.latest_10q_url,
        latest_10q_filed_at=edgar_meta.latest_10q_filed_at,
    )


async def _fetch_yfinance_info(ticker: str) -> dict[str, Any]:
    """Pull the `Ticker.info` dict from yfinance in a worker thread.

    yfinance throws a wide variety of exceptions; we surface the
    rate-limit ones as `RateLimitError` so `Cached` can soft-degrade to
    a stale bundle. Other failures return an empty dict — downstream
    fields will be `None` rather than blowing up the whole bundle.
    """

    def _call() -> dict[str, Any]:
        try:
            info = yf.Ticker(ticker).info
        except Exception as exc:  # noqa: BLE001
            if _looks_like_rate_limit(exc):
                raise RateLimitError(str(exc)) from exc
            logger.warning("yfinance .info failed for %s: %s", ticker, exc)
            return {}
        if not info:
            return {}
        return dict(info)

    return await asyncio.to_thread(_call)


class _EdgarMeta(BaseModel):
    latest_10k_url: str | None = None
    latest_10q_url: str | None = None
    latest_10q_filed_at: datetime | None = None


async def _fetch_edgar_metadata(ticker: str) -> _EdgarMeta:
    """Latest 10-K / 10-Q URLs + 10-Q filing date from EDGAR.

    edgartools is synchronous; we run it in a thread. Any failure
    (import, network, missing filings) collapses to an empty `_EdgarMeta`
    rather than failing the whole bundle — EDGAR coverage is patchy for
    non-US tickers.
    """
    return await asyncio.to_thread(_edgar_lookup_sync, ticker)


def _edgar_lookup_sync(ticker: str) -> _EdgarMeta:
    try:
        from edgar import Company, set_identity
    except ImportError:
        logger.warning("edgartools not installed; skipping EDGAR lookup")
        return _EdgarMeta()

    set_identity(os.getenv("EDGAR_IDENTITY", _DEFAULT_EDGAR_IDENTITY))

    try:
        company = Company(ticker)
    except Exception as exc:  # noqa: BLE001
        logger.warning("edgar Company(%s) failed: %s", ticker, exc)
        return _EdgarMeta()

    tenk_url, _ = _latest_filing(company, "10-K")
    tenq_url, tenq_filed_at = _latest_filing(company, "10-Q")
    return _EdgarMeta(
        latest_10k_url=tenk_url,
        latest_10q_url=tenq_url,
        latest_10q_filed_at=tenq_filed_at,
    )


def _latest_filing(company: Any, form: str) -> tuple[str | None, datetime | None]:
    """Return (url, filed_at) for the most recent filing of `form`.

    edgartools' object shapes shift between releases — we defensively
    probe a few attribute names rather than locking onto one.
    """
    try:
        filings = company.get_filings(form=form)
    except Exception as exc:  # noqa: BLE001
        logger.warning("edgar get_filings(%s) failed: %s", form, exc)
        return (None, None)
    if filings is None:
        return (None, None)

    latest = _first_filing(filings)
    if latest is None:
        return (None, None)

    return (_filing_url(latest), _filing_datetime(latest))


def _first_filing(filings: Any) -> Any | None:
    for getter in ("latest", "first"):
        method = getattr(filings, getter, None)
        if callable(method):
            try:
                result = method() if getter == "latest" else method(1)
            except TypeError:
                try:
                    result = method(1)
                except Exception:  # noqa: BLE001
                    continue
            except Exception:  # noqa: BLE001
                continue
            if result is None:
                continue
            return _maybe_unwrap(result)
    try:
        return filings[0]
    except Exception:  # noqa: BLE001
        return None


def _maybe_unwrap(result: Any) -> Any:
    """`Filings.latest(n)` sometimes returns a Filings, sometimes a Filing."""
    if hasattr(result, "filing_date") or hasattr(result, "form"):
        return result
    try:
        return result[0]
    except Exception:  # noqa: BLE001
        return result


def _filing_url(filing: Any) -> str | None:
    for attr in ("filing_url", "homepage_url", "url"):
        value = getattr(filing, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:  # noqa: BLE001
                value = None
        if isinstance(value, str) and value:
            return value
    return None


def _filing_datetime(filing: Any) -> datetime | None:
    value = getattr(filing, "filing_date", None)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _get_str(info: dict[str, Any], key: str) -> str | None:
    value = info.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _get_float(info: dict[str, Any], key: str) -> float | None:
    value = info.get(key)
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # yfinance occasionally returns NaN/inf for missing data.
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _looks_like_rate_limit(exc: BaseException) -> bool:
    cls_name = type(exc).__name__.lower()
    if "ratelimit" in cls_name:
        return True
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


__all__ = ["FundamentalsBundle", "fetch_fundamentals"]

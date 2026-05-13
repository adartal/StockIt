"""News fetching for the StockIt pipeline.

Aggregates per-ticker headlines from up to three sources:

  * **NewsAPI** (`NEWSAPI_API_KEY` env) — broad publisher coverage with
    structured JSON. Skipped when no key is set.
  * **Yahoo Finance RSS** — always available, no auth.
  * **Google News RSS** — always available, no auth.

Results are merged, filtered to `lookback_days`, deduplicated by
canonicalized URL, and sorted newest-first. The whole list is wrapped
with `Cached` (30-minute TTL) so repeat calls within the window skip
the upstream HTTP entirely. Per-source failures are logged and
swallowed — one flaky feed doesn't poison the merged result.

Note: this module deliberately produces *structural* metadata only
(title, source, time, optional feed-supplied summary). LLM-based
sentiment scoring belongs to the news analyst (M4c); `sentiment_hint`
is reserved for a feed that ships its own score and stays `None`
otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import os
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from pydantic import BaseModel, Field

from app.pipeline.data.cache import Cached

logger = logging.getLogger(__name__)

_NEWS_TTL_SECONDS = 30 * 60


class NewsItem(BaseModel):
    """A single headline from one of the upstream feeds."""

    url: str
    title: str
    source: str
    published_at: datetime
    summary: str | None = None
    sentiment_hint: float | None = Field(default=None, ge=-1.0, le=1.0)


async def fetch_news(ticker: str, lookback_days: int = 30) -> list[NewsItem]:
    """Return deduplicated, recency-sorted headlines for `ticker`.

    Items are filtered to those published within the last
    `lookback_days`. Order is newest first. Empty list if every source
    fails or returns nothing relevant.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")

    cache = Cached[list[NewsItem]](
        source="news",
        ttl_seconds=_NEWS_TTL_SECONDS,
        serialize=_serialize_items,
        deserialize=_deserialize_items,
    )
    return await cache.fetch(
        key=f"{ticker}:{lookback_days}",
        fetcher=lambda: _gather_news(ticker, lookback_days),
    )


async def _gather_news(ticker: str, lookback_days: int) -> list[NewsItem]:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        results = await asyncio.gather(
            _fetch_newsapi(ticker, lookback_days, client),
            _fetch_yahoo_rss(ticker, client),
            _fetch_google_news_rss(ticker, client),
            return_exceptions=True,
        )

    merged: list[NewsItem] = []
    source_names = ("newsapi", "yahoo_rss", "google_news_rss")
    for source_name, result in zip(source_names, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("news source %s failed: %r", source_name, result)
            continue
        merged.extend(result)

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    filtered = [item for item in merged if item.published_at >= cutoff]

    seen: set[str] = set()
    deduped: list[NewsItem] = []
    for item in filtered:
        canonical = _canonical_url(item.url)
        if canonical in seen:
            continue
        seen.add(canonical)
        deduped.append(item)

    deduped.sort(key=lambda item: item.published_at, reverse=True)
    return deduped


async def _fetch_newsapi(
    ticker: str, lookback_days: int, client: httpx.AsyncClient
) -> list[NewsItem]:
    api_key = os.getenv("NEWSAPI_API_KEY")
    if not api_key:
        return []

    from_date = (datetime.now(UTC) - timedelta(days=lookback_days)).date().isoformat()
    params: dict[str, str] = {
        "q": ticker,
        "from": from_date,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": "100",
        "apiKey": api_key,
    }
    response = await client.get("https://newsapi.org/v2/everything", params=params)
    response.raise_for_status()
    payload = response.json()

    items: list[NewsItem] = []
    for article in payload.get("articles", []) or []:
        url = (article.get("url") or "").strip()
        title = (article.get("title") or "").strip()
        published_raw = article.get("publishedAt")
        if not url or not title or not published_raw:
            continue
        try:
            published = _parse_iso8601(published_raw)
        except ValueError:
            continue
        source_obj = article.get("source") or {}
        source_name = (source_obj.get("name") or "").strip() or "newsapi"
        description = article.get("description")
        items.append(
            NewsItem(
                url=url,
                title=title,
                source=source_name,
                published_at=published,
                summary=description.strip() if isinstance(description, str) else None,
            )
        )
    return items


async def _fetch_yahoo_rss(ticker: str, client: httpx.AsyncClient) -> list[NewsItem]:
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={ticker}&region=US&lang=en-US"
    )
    response = await client.get(url)
    response.raise_for_status()
    return _parse_rss(response.text, default_source="Yahoo Finance")


async def _fetch_google_news_rss(ticker: str, client: httpx.AsyncClient) -> list[NewsItem]:
    url = (
        "https://news.google.com/rss/search"
        f"?q={ticker}&hl=en-US&gl=US&ceid=US:en"
    )
    response = await client.get(url)
    response.raise_for_status()
    return _parse_rss(response.text, default_source="Google News")


def _parse_rss(text: str, *, default_source: str) -> list[NewsItem]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        logger.warning("RSS parse error for %s: %r", default_source, exc)
        return []

    items: list[NewsItem] = []
    for entry in root.iter("item"):
        link = (entry.findtext("link") or "").strip()
        title = (entry.findtext("title") or "").strip()
        pub_raw = entry.findtext("pubDate")
        if not link or not title or not pub_raw:
            continue
        try:
            published = parsedate_to_datetime(pub_raw)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        else:
            published = published.astimezone(UTC)

        # Google News exposes the originating publisher in <source>.
        source_el = entry.find("source")
        if source_el is not None and source_el.text:
            source_name = source_el.text.strip()
        else:
            source_name = default_source

        description = entry.findtext("description")
        summary = description.strip() if description else None

        items.append(
            NewsItem(
                url=link,
                title=title,
                source=source_name,
                published_at=published,
                summary=summary,
            )
        )
    return items


def _parse_iso8601(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _canonical_url(url: str) -> str:
    """Normalize so light variants (host case, trailing slash, query) collapse.

    Tracking params and fragments are dropped wholesale; many aggregators
    decorate the same article with utm_*/source params that would defeat
    naïve string equality.
    """
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", "", ""))


def _serialize_items(items: list[NewsItem]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


def _deserialize_items(raw: Any) -> list[NewsItem]:
    if not raw:
        return []
    return [NewsItem.model_validate(entry) for entry in raw]


__all__ = ["NewsItem", "fetch_news"]

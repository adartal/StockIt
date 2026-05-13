"""Tests for the news fetcher.

All three upstream feeds are mocked via a single `httpx.AsyncClient.get`
patch that dispatches by URL. The shared `Cached` wrapper is backed by
an in-memory SQLite per test, matching the pattern in test_prices.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base, DataCache
from app.pipeline.data import cache as cache_module
from app.pipeline.data.news import NewsItem, fetch_news


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    with patch.object(cache_module, "async_session_factory", factory):
        yield factory
    await engine.dispose()


class _FakeResponse:
    def __init__(self, *, json_data: dict[str, Any] | None = None, text: str = "") -> None:
        self._json = json_data
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        assert self._json is not None
        return self._json


def _rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _yahoo_rss(items: list[tuple[str, str, datetime, str]]) -> str:
    entries = "\n".join(
        f"""
        <item>
          <title>{title}</title>
          <link>{link}</link>
          <pubDate>{_rfc822(published)}</pubDate>
          <description>{summary}</description>
        </item>"""
        for (title, link, published, summary) in items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Yahoo! Finance: AAPL</title>
    {entries}
  </channel>
</rss>"""


def _google_rss(items: list[tuple[str, str, datetime, str, str]]) -> str:
    entries = "\n".join(
        f"""
        <item>
          <title>{title}</title>
          <link>{link}</link>
          <pubDate>{_rfc822(published)}</pubDate>
          <description>{summary}</description>
          <source url="https://example.com">{src}</source>
        </item>"""
        for (title, link, published, summary, src) in items
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News - AAPL</title>
    {entries}
  </channel>
</rss>"""


def _newsapi_payload(articles: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "ok", "totalResults": len(articles), "articles": articles}


def _dispatcher(
    *,
    yahoo: str = "",
    google: str = "",
    newsapi: dict[str, Any] | None = None,
    log: list[str] | None = None,
) -> Callable[..., Any]:
    """Build a side_effect that routes `client.get(url, params=...)` by host."""

    async def _get(self: Any, url: str, *args: Any, **kwargs: Any) -> _FakeResponse:
        if log is not None:
            log.append(url)
        if "newsapi.org" in url:
            return _FakeResponse(json_data=newsapi or {"articles": []})
        if "yahoo.com" in url:
            return _FakeResponse(text=yahoo)
        if "news.google.com" in url:
            return _FakeResponse(text=google)
        raise AssertionError(f"unexpected URL: {url}")

    return _get


@pytest.mark.asyncio
async def test_fetch_news_merges_three_sources_and_dedupes(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEWSAPI_API_KEY", "test-key")
    now = datetime.now(UTC).replace(microsecond=0)
    recent = now - timedelta(hours=2)

    yahoo_url_a = "https://Finance.Yahoo.com/news/apple-beat/"
    yahoo_url_b = "https://finance.yahoo.com/news/apple-sued"
    yahoo_xml = _yahoo_rss(
        [
            ("Apple beats earnings", yahoo_url_a, recent, "Beat."),
            ("Apple sued", yahoo_url_b, recent - timedelta(hours=1), "Lawsuit."),
        ]
    )
    google_xml = _google_rss(
        [
            (
                "Apple unveils chip",
                "https://www.reuters.com/tech/apple-chip",
                recent - timedelta(hours=3),
                "Snippet.",
                "Reuters",
            ),
        ]
    )
    newsapi = _newsapi_payload(
        [
            {
                "url": "https://finance.yahoo.com/news/apple-beat",
                "title": "Apple beats earnings",
                "publishedAt": recent.isoformat().replace("+00:00", "Z"),
                "description": "Same article via NewsAPI.",
                "source": {"name": "Yahoo Finance"},
            },
            {
                "url": "https://www.bloomberg.com/news/articles/apple-guidance",
                "title": "Apple guidance update",
                "publishedAt": (recent - timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
                "description": "Bloomberg reporting.",
                "source": {"name": "Bloomberg"},
            },
        ]
    )

    with patch(
        "httpx.AsyncClient.get",
        new=_dispatcher(yahoo=yahoo_xml, google=google_xml, newsapi=newsapi),
    ):
        items = await fetch_news("AAPL", lookback_days=7)

    # 5 raw items (2 yahoo + 1 google + 2 newsapi) - 1 duplicate = 4 unique
    assert len(items) == 4
    urls = [item.url for item in items]
    assert any("bloomberg.com" in u for u in urls)
    assert any("reuters.com" in u for u in urls)
    # Sorted newest first.
    assert all(
        items[i].published_at >= items[i + 1].published_at for i in range(len(items) - 1)
    )


@pytest.mark.asyncio
async def test_fetch_news_skips_newsapi_without_key(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    now = datetime.now(UTC)
    yahoo_xml = _yahoo_rss(
        [("Headline", "https://finance.yahoo.com/news/x", now, "desc")]
    )
    google_xml = _google_rss(
        [("Other", "https://news.example.com/x", now, "snip", "Example")]
    )

    log: list[str] = []
    with patch(
        "httpx.AsyncClient.get",
        new=_dispatcher(yahoo=yahoo_xml, google=google_xml, log=log),
    ):
        items = await fetch_news("AAPL", lookback_days=7)

    assert len(items) == 2
    assert not any("newsapi.org" in url for url in log)


@pytest.mark.asyncio
async def test_fetch_news_filters_by_lookback(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    now = datetime.now(UTC)
    yahoo_xml = _yahoo_rss(
        [
            ("Recent", "https://finance.yahoo.com/news/recent", now - timedelta(days=2), "d"),
            ("Stale", "https://finance.yahoo.com/news/stale", now - timedelta(days=45), "d"),
        ]
    )
    google_xml = _google_rss(
        [("Old", "https://news.example.com/old", now - timedelta(days=20), "s", "Example")]
    )

    with patch(
        "httpx.AsyncClient.get",
        new=_dispatcher(yahoo=yahoo_xml, google=google_xml),
    ):
        items = await fetch_news("AAPL", lookback_days=7)

    titles = {item.title for item in items}
    assert titles == {"Recent"}


@pytest.mark.asyncio
async def test_fetch_news_swallows_per_source_errors(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    now = datetime.now(UTC)
    yahoo_xml = _yahoo_rss(
        [("Yahoo only", "https://finance.yahoo.com/news/only", now, "d")]
    )

    async def _get(self: Any, url: str, *args: Any, **kwargs: Any) -> _FakeResponse:
        if "yahoo.com" in url:
            return _FakeResponse(text=yahoo_xml)
        raise RuntimeError("google is on fire")

    with patch("httpx.AsyncClient.get", new=_get):
        items = await fetch_news("AAPL", lookback_days=7)

    assert len(items) == 1
    assert items[0].title == "Yahoo only"


@pytest.mark.asyncio
async def test_fetch_news_cache_hit_on_second_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    now = datetime.now(UTC)
    yahoo_xml = _yahoo_rss(
        [("Hit", "https://finance.yahoo.com/news/hit", now, "d")]
    )
    google_xml = _google_rss(
        [("Run", "https://news.example.com/run", now, "s", "Example")]
    )

    calls: list[str] = []
    with patch(
        "httpx.AsyncClient.get",
        new=_dispatcher(yahoo=yahoo_xml, google=google_xml, log=calls),
    ):
        first = await fetch_news("AAPL", lookback_days=14)
        second = await fetch_news("AAPL", lookback_days=14)

    assert len(first) == 2
    # Second call hit the cache, so no additional upstream HTTP.
    assert len(calls) == 2  # one Yahoo + one Google from the first call only
    assert [item.url for item in first] == [item.url for item in second]
    assert [item.published_at for item in first] == [item.published_at for item in second]

    async with session_factory() as session:
        rows = (await session.execute(select(DataCache))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "news"


@pytest.mark.asyncio
async def test_fetch_news_invalid_input() -> None:
    with pytest.raises(ValueError):
        await fetch_news("", 7)
    with pytest.raises(ValueError):
        await fetch_news("AAPL", 0)


def test_news_item_round_trip() -> None:
    """Serialize / validate should round-trip — the cache relies on this."""
    item = NewsItem(
        url="https://example.com/a",
        title="t",
        source="src",
        published_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        summary="hi",
        sentiment_hint=0.5,
    )
    raw = item.model_dump(mode="json")
    restored = NewsItem.model_validate(raw)
    assert restored == item

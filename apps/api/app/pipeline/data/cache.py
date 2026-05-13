"""Shared read-through TTL cache for upstream data fetchers.

Every fetcher in `app/pipeline/data/` (prices, fundamentals, news, macro)
wraps its upstream calls with `Cached`. The cache is backed by the
`data_cache` table (composite PK on `key + source`) so cache entries
survive process restarts and are shared across workers.

Why a class wrapper rather than a `functools.lru_cache`-style decorator:

  * TTLs vary per call site (1m bars vs daily bars vs 24h fundamentals).
  * Payloads aren't all JSON-native (e.g. pandas DataFrame for prices) —
    the wrapper needs hooks to serialize/deserialize per fetcher.
  * On upstream rate-limit (`RateLimitError`), we want to *extend* the
    existing entry's TTL and serve the stale payload rather than blow up
    the caller. yfinance/Alpha Vantage are both prone to silent throttling
    (see docs/m2-data-source-survey.md), so soft-degrading to stale data is
    the right default.

Usage::

    cache = Cached(
        source="yfinance",
        ttl_seconds=86400,
        serialize=lambda df: df.to_json(),
        deserialize=lambda raw: pd.read_json(raw),
    )
    df = await cache.fetch(key="AAPL:1d:365", fetcher=lambda: _yf_call("AAPL"))
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import async_session_factory
from app.models import DataCache

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised by a wrapped fetcher when the upstream throttles or 429s.

    The `Cached` wrapper catches this, extends the TTL on the existing
    cache row (if any), and returns the stale payload. If no cache row
    exists, the exception is re-raised so the caller can decide.
    """


class Cached[T]:
    """Read-through TTL cache backed by the `data_cache` table.

    Parameters
    ----------
    source:
        Logical source name (e.g. "yfinance", "alpha_vantage"). Part of
        the cache row's composite primary key — two sources may share a
        `key` without colliding.
    ttl_seconds:
        Default TTL for new entries. Override per call by passing
        `ttl_seconds=` to `.fetch()` (used by prices.py where TTL varies
        by interval).
    serialize / deserialize:
        Optional conversions between the in-memory payload `T` and a
        JSON-storable value. Default = identity (assumes T is already
        JSON-serializable). For DataFrames, pass `df.to_json` /
        `pd.read_json`.
    stale_extension_seconds:
        How long to extend a stale entry's effective TTL when the
        upstream rate-limits. Default 1h — enough to ride out most
        free-tier throttles without serving badly stale data for too long.
    session_factory:
        Override the default async session factory. Tests inject an
        in-memory SQLite factory here.
    """

    def __init__(
        self,
        *,
        source: str,
        ttl_seconds: int,
        serialize: Callable[[T], Any] | None = None,
        deserialize: Callable[[Any], T] | None = None,
        stale_extension_seconds: int = 3600,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.source = source
        self.ttl_seconds = ttl_seconds
        self._serialize: Callable[[T], Any] = serialize or (lambda v: v)
        self._deserialize: Callable[[Any], T] = deserialize or (lambda v: v)
        self.stale_extension_seconds = stale_extension_seconds
        self._session_factory: async_sessionmaker[AsyncSession] = (
            session_factory or async_session_factory
        )

    async def fetch(
        self,
        *,
        key: str,
        fetcher: Callable[[], Awaitable[T]],
        ttl_seconds: int | None = None,
    ) -> T:
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        now = datetime.now(UTC)

        async with self._session_factory() as session:
            row = await self._load(session, key)

            if row is not None and self._is_fresh(row, now):
                return self._deserialize(row.payload)

            try:
                value = await fetcher()
            except RateLimitError:
                if row is not None:
                    await self._extend(session, row, now)
                    logger.warning(
                        "rate-limited; serving stale cache entry "
                        "source=%s key=%s age_seconds=%.0f",
                        self.source,
                        key,
                        (now - _aware(row.fetched_at)).total_seconds(),
                    )
                    return self._deserialize(row.payload)
                logger.warning(
                    "rate-limited and no cache entry to fall back to "
                    "source=%s key=%s",
                    self.source,
                    key,
                )
                raise

            serialized = self._serialize(value)
            await self._upsert(session, key, serialized, now, effective_ttl)
            return value

    async def _load(self, session: AsyncSession, key: str) -> DataCache | None:
        result = await session.execute(
            select(DataCache).where(
                DataCache.key == key, DataCache.source == self.source
            )
        )
        return result.scalar_one_or_none()

    def _is_fresh(self, row: DataCache, now: datetime) -> bool:
        expiry = _aware(row.fetched_at) + timedelta(seconds=row.ttl_seconds)
        return now < expiry

    async def _upsert(
        self,
        session: AsyncSession,
        key: str,
        payload: Any,
        now: datetime,
        ttl_seconds: int,
    ) -> None:
        existing = await self._load(session, key)
        if existing is None:
            session.add(
                DataCache(
                    key=key,
                    source=self.source,
                    payload=payload,
                    fetched_at=now,
                    ttl_seconds=ttl_seconds,
                )
            )
        else:
            existing.payload = payload
            existing.fetched_at = now
            existing.ttl_seconds = ttl_seconds
        await session.commit()

    async def _extend(self, session: AsyncSession, row: DataCache, now: datetime) -> None:
        age = (now - _aware(row.fetched_at)).total_seconds()
        row.ttl_seconds = int(age) + self.stale_extension_seconds
        await session.commit()


def _aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo on read; normalize back to UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


__all__ = ["Cached", "RateLimitError"]

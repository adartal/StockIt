"""Async database engine + session factory.

`DATABASE_URL` env var drives the engine. If unset, defaults to a local
sqlite+aiosqlite file so dev/CI can run with no Postgres. The URL is
normalized to an async driver if a sync scheme was supplied
(`postgresql://` → `postgresql+asyncpg://`, `sqlite://` → `sqlite+aiosqlite://`).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./stockit.db"


def _to_async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url[len("sqlite://") :]
    return url


def get_database_url() -> str:
    return _to_async_url(os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL)


engine: AsyncEngine = create_async_engine(get_database_url(), future=True)
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


__all__ = [
    "DEFAULT_DATABASE_URL",
    "async_session_factory",
    "engine",
    "get_database_url",
    "get_session",
]

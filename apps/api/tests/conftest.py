"""Shared fixtures for route integration tests.

Per-test sqlite-in-memory DB, ASGI client wired to it, and overrides for
the LLM provider dependency. Other test modules (e.g. ``test_auth.py``)
define their own ``session_factory`` / ``client`` fixtures locally; those
shadow the ones here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db import get_session
from app.main import app
from app.models import Base
from app.pipeline.schema import (
    Citation,
    Entry,
    ExitLevel,
    Horizon,
    Plan,
    Sizing,
    Stop,
)
from app.routes.deps import get_llm_provider


def build_plan(ticker: str = "AAPL", horizon: Horizon = "swing") -> Plan:
    return Plan(
        ticker=ticker,
        horizon=horizon,
        capital=Decimal("10000"),
        generated_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        thesis="placeholder thesis",
        conviction="medium",
        entry=Entry(kind="limit", levels=[Decimal("100")], conditions="on dip"),
        sizing=Sizing(
            risk_pct=1.0,
            shares=20,
            dollar_exposure=Decimal("2000"),
            R_value=Decimal("5"),
        ),
        stop=Stop(price=Decimal("95"), kind="technical", rationale="below swing low"),
        exits=[
            ExitLevel(
                kind="scale_out",
                price=Decimal("110"),
                trigger="resistance",
                portion=0.5,
            )
        ],
        catalysts=[],
        risk_flags=[],
        review_cadence="weekly",
        sources=[
            Citation(
                url="https://finance.yahoo.com/quote/AAPL",
                title="AAPL quote",
                source="Yahoo Finance",
                fetched_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
            )
        ],
    )


class FakeLLM:
    name = "fake"

    async def complete_structured(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("FakeLLM should never be called in route tests")


@pytest_asyncio.fixture
async def routes_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_id = uuid.uuid4().hex
    url = (
        f"sqlite+aiosqlite:///file:routes-{db_id}"
        "?mode=memory&cache=shared&uri=true"
    )
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def routes_client(
    routes_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        async with routes_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLM()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()

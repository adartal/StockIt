"""Integration tests for /plans routes (M6).

The orchestrator's `generate_plan` is monkey-patched on the route module
so we exercise the FastAPI wiring + DB persistence without invoking the
real data fetchers or LLM provider.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Plan as PlanRow
from app.routes import plans as plans_module
from tests.conftest import build_plan


async def _fake_generate_plan_factory(
    captured: list[dict[str, Any]] | None = None,
    *,
    ticker: str = "AAPL",
):
    async def _fake(**kwargs):
        if captured is not None:
            captured.append(kwargs)
        normalized = kwargs["ticker"].upper().strip()
        plan = build_plan(ticker=normalized, horizon=kwargs["horizon"])
        plan = plan.model_copy(update={"capital": kwargs["capital"]})
        session = kwargs["session"]
        user_id = kwargs["user_id"]
        row = PlanRow(
            user_id=user_id,
            ticker=plan.ticker,
            horizon=plan.horizon,
            capital=plan.capital,
            generated_at=plan.generated_at,
            payload=plan.model_dump(mode="json"),
        )
        session.add(row)
        await session.commit()
        return plan

    return _fake


@pytest.mark.asyncio
async def test_post_plan_returns_plan(
    routes_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plans_module, "generate_plan", await _fake_generate_plan_factory()
    )
    resp = await routes_client.post(
        "/plans",
        json={"ticker": "aapl", "horizon": "swing", "capital": "10000"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert body["horizon"] == "swing"
    assert body["stop"]["price"] == "95"


@pytest.mark.asyncio
async def test_post_plan_persists(
    routes_client: AsyncClient,
    routes_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plans_module, "generate_plan", await _fake_generate_plan_factory()
    )
    resp = await routes_client.post(
        "/plans",
        json={"ticker": "AAPL", "horizon": "swing", "capital": "10000"},
    )
    assert resp.status_code == 200, resp.text

    async with routes_session_factory() as session:
        result = await session.execute(select(PlanRow))
        rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].ticker == "AAPL"


@pytest.mark.asyncio
async def test_post_plan_validation_error_returns_422(
    routes_client: AsyncClient,
) -> None:
    resp = await routes_client.post(
        "/plans", json={"ticker": "AAPL", "horizon": "weekly", "capital": "10000"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_plan_invalid_capital_400_or_422(
    routes_client: AsyncClient,
) -> None:
    resp = await routes_client.post(
        "/plans", json={"ticker": "AAPL", "horizon": "swing", "capital": "-5"}
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_get_plan_by_id(
    routes_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plans_module, "generate_plan", await _fake_generate_plan_factory()
    )
    create = await routes_client.post(
        "/plans", json={"ticker": "MSFT", "horizon": "swing", "capital": "10000"}
    )
    assert create.status_code == 200
    # The Plan response shape has no id — fetch by listing then GET.
    listing = await routes_client.get("/plans?ticker=MSFT")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    # Look up the row id directly from the DB to test GET by id path.
    # We can't read the response id, but we can hit the listing then ask the
    # DB for the row's UUID through the session factory if we choose.
    # Instead, we hit a non-existent id and check 404.
    bogus = uuid.uuid4()
    resp = await routes_client.get(f"/plans/{bogus}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_plans_filter_by_ticker(
    routes_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plans_module, "generate_plan", await _fake_generate_plan_factory()
    )
    for ticker in ("AAPL", "AAPL", "MSFT"):
        await routes_client.post(
            "/plans",
            json={"ticker": ticker, "horizon": "swing", "capital": "10000"},
        )

    aapl = await routes_client.get("/plans?ticker=AAPL")
    msft = await routes_client.get("/plans?ticker=MSFT")
    everything = await routes_client.get("/plans")

    assert aapl.status_code == 200
    assert msft.status_code == 200
    assert everything.status_code == 200
    assert len(aapl.json()) == 2
    assert len(msft.json()) == 1
    assert len(everything.json()) == 3


@pytest.mark.asyncio
async def test_get_plan_by_id_round_trip(
    routes_client: AsyncClient,
    routes_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plans_module, "generate_plan", await _fake_generate_plan_factory()
    )
    create = await routes_client.post(
        "/plans", json={"ticker": "AAPL", "horizon": "swing", "capital": "10000"}
    )
    assert create.status_code == 200
    async with routes_session_factory() as session:
        result = await session.execute(select(PlanRow))
        row = result.scalar_one()
    fetch = await routes_client.get(f"/plans/{row.id}")
    assert fetch.status_code == 200
    body = fetch.json()
    assert body["ticker"] == "AAPL"
    assert body["horizon"] == "swing"

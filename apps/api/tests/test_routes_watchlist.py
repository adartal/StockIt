"""Integration tests for /watchlist routes (M6)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Plan as PlanRow
from app.models import PlanRevision as PlanRevisionRow
from app.models import WatchlistItem
from app.routes import watchlist as watchlist_module
from tests.conftest import build_plan


@pytest.mark.asyncio
async def test_post_watchlist_creates_item(routes_client: AsyncClient) -> None:
    resp = await routes_client.post("/watchlist", json={"ticker": "aapl"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert body["last_plan_id"] is None


@pytest.mark.asyncio
async def test_post_watchlist_is_idempotent(routes_client: AsyncClient) -> None:
    first = await routes_client.post("/watchlist", json={"ticker": "AAPL"})
    second = await routes_client.post("/watchlist", json={"ticker": "AAPL"})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_list_watchlist(routes_client: AsyncClient) -> None:
    for ticker in ("AAPL", "MSFT"):
        await routes_client.post("/watchlist", json={"ticker": ticker})
    resp = await routes_client.get("/watchlist")
    assert resp.status_code == 200
    body = resp.json()
    assert {item["ticker"] for item in body} == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_delete_watchlist_item(routes_client: AsyncClient) -> None:
    created = await routes_client.post("/watchlist", json={"ticker": "AAPL"})
    assert created.status_code == 201
    item_id = created.json()["id"]
    resp = await routes_client.delete(f"/watchlist/{item_id}")
    assert resp.status_code == 204
    listing = await routes_client.get("/watchlist")
    assert listing.json() == []


@pytest.mark.asyncio
async def test_delete_missing_404(routes_client: AsyncClient) -> None:
    resp = await routes_client.delete(f"/watchlist/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_refresh_without_existing_plan_returns_409(
    routes_client: AsyncClient,
) -> None:
    created = await routes_client.post("/watchlist", json={"ticker": "AAPL"})
    item_id = created.json()["id"]
    resp = await routes_client.post(f"/watchlist/{item_id}/refresh")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_refresh_creates_revision(
    routes_client: AsyncClient,
    routes_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch generate_plan on the watchlist module to insert a new plan row
    # with a tweaked thesis so diff_json is non-empty.
    call_count = {"n": 0}

    async def _fake(**kwargs):
        call_count["n"] += 1
        plan = build_plan(ticker=kwargs["ticker"], horizon=kwargs["horizon"])
        plan = plan.model_copy(
            update={
                "capital": kwargs["capital"],
                "thesis": f"refresh #{call_count['n']}",
            }
        )
        session = kwargs["session"]
        row = PlanRow(
            user_id=kwargs["user_id"],
            ticker=plan.ticker,
            horizon=plan.horizon,
            capital=plan.capital,
            generated_at=plan.generated_at,
            payload=plan.model_dump(mode="json"),
        )
        session.add(row)
        await session.commit()
        return plan

    monkeypatch.setattr(watchlist_module, "generate_plan", _fake)

    # Seed a prior plan + watchlist item.
    seeded_plan = build_plan(ticker="AAPL").model_copy(
        update={"thesis": "original"}
    )
    async with routes_session_factory() as session:
        # Find or create the test user via the routes' default-user path:
        # easiest is to POST the watchlist first to ensure the user row.
        pass

    create_watch = await routes_client.post("/watchlist", json={"ticker": "AAPL"})
    item_id = create_watch.json()["id"]

    # Insert a prior Plan row owned by the same user.
    async with routes_session_factory() as session:
        item = await session.get(WatchlistItem, uuid.UUID(item_id))
        assert item is not None
        prior = PlanRow(
            user_id=item.user_id,
            ticker="AAPL",
            horizon=seeded_plan.horizon,
            capital=seeded_plan.capital,
            generated_at=seeded_plan.generated_at,
            payload=seeded_plan.model_dump(mode="json"),
        )
        session.add(prior)
        await session.commit()

    resp = await routes_client.post(f"/watchlist/{item_id}/refresh")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "diff_json" in body
    assert body["diff_json"].get("thesis") == {
        "before": "original",
        "after": "refresh #1",
    }

    async with routes_session_factory() as session:
        result = await session.execute(select(PlanRevisionRow))
        revisions = result.scalars().all()
    assert len(revisions) == 1

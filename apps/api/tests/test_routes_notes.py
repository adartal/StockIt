"""Integration tests for /plans/{id}/notes routes (M6)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Plan as PlanRow
from app.models import User
from tests.conftest import build_plan


async def _seed_plan(
    session_factory: async_sessionmaker[AsyncSession],
    routes_client: AsyncClient,
) -> uuid.UUID:
    """Ensure the default test user exists and seed one Plan row."""
    # Hitting any route triggers default-user creation.
    await routes_client.get("/watchlist")
    async with session_factory() as session:
        result = await session.execute(select(User))
        user = result.scalar_one()
        plan = build_plan(ticker="AAPL")
        row = PlanRow(
            user_id=user.id,
            ticker="AAPL",
            horizon=plan.horizon,
            capital=plan.capital,
            generated_at=plan.generated_at,
            payload=plan.model_dump(mode="json"),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


@pytest.mark.asyncio
async def test_post_and_list_notes(
    routes_client: AsyncClient,
    routes_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    plan_id = await _seed_plan(routes_session_factory, routes_client)

    resp = await routes_client.post(
        f"/plans/{plan_id}/notes", json={"text": "first note"}
    )
    assert resp.status_code == 201
    assert resp.json()["body"] == "first note"

    await routes_client.post(
        f"/plans/{plan_id}/notes", json={"text": "second note"}
    )
    listing = await routes_client.get(f"/plans/{plan_id}/notes")
    assert listing.status_code == 200
    bodies = [n["body"] for n in listing.json()]
    assert bodies == ["first note", "second note"]


@pytest.mark.asyncio
async def test_note_on_missing_plan_404(routes_client: AsyncClient) -> None:
    resp = await routes_client.post(
        f"/plans/{uuid.uuid4()}/notes", json={"text": "x"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_empty_text_rejected(
    routes_client: AsyncClient,
    routes_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    plan_id = await _seed_plan(routes_session_factory, routes_client)
    resp = await routes_client.post(
        f"/plans/{plan_id}/notes", json={"text": ""}
    )
    assert resp.status_code == 422

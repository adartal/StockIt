"""Routes for the per-user watchlist."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.llm.router import NoProviderAvailableError
from app.models import Plan as PlanRow
from app.models import PlanRevision as PlanRevisionRow
from app.models import WatchlistItem
from app.pipeline.orchestrator import generate_plan
from app.pipeline.risk import RiskRuleViolation
from app.routes.deps import (
    CurrentUser,
    LLMDep,
    SessionDep,
    get_user_risk_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistItemCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)


class WatchlistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticker: str
    last_plan_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PlanRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    created_at: datetime
    payload: dict[str, Any]
    diff_json: dict[str, Any]


@router.get("", response_model=list[WatchlistItemRead])
async def list_watchlist(
    user: CurrentUser, session: SessionDep
) -> list[WatchlistItem]:
    result = await session.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == user.id)
        .order_by(WatchlistItem.created_at)
    )
    return list(result.scalars().all())


@router.post(
    "", response_model=WatchlistItemRead, status_code=status.HTTP_201_CREATED
)
async def create_watchlist_item(
    payload: WatchlistItemCreate,
    user: CurrentUser,
    session: SessionDep,
) -> WatchlistItem:
    ticker = payload.ticker.upper().strip()
    existing = await session.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user.id, WatchlistItem.ticker == ticker
        )
    )
    item = existing.scalar_one_or_none()
    if item is not None:
        return item
    item = WatchlistItem(user_id=user.id, ticker=ticker)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist_item(
    item_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Response:
    item = await session.get(WatchlistItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist item not found",
        )
    await session.delete(item)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _diff_plans(prev: dict[str, Any], curr: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow {key: {before, after}} diff for top-level Plan fields."""
    diff: dict[str, Any] = {}
    keys = set(prev) | set(curr)
    for key in keys:
        before = prev.get(key)
        after = curr.get(key)
        if before != after:
            diff[key] = {"before": before, "after": after}
    return diff


@router.post(
    "/{item_id}/refresh",
    response_model=PlanRevisionRead,
    status_code=status.HTTP_200_OK,
)
async def refresh_watchlist_item(
    item_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    session: SessionDep,
    llm: LLMDep,
) -> PlanRevisionRow:
    item = await session.get(WatchlistItem, item_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Watchlist item not found",
        )

    prev_plan_row: PlanRow | None = None
    if item.last_plan_id is not None:
        prev_plan_row = await session.get(PlanRow, item.last_plan_id)
    if prev_plan_row is None:
        # Pick the most recent existing plan for this ticker, if any.
        result = await session.execute(
            select(PlanRow)
            .where(PlanRow.user_id == user.id, PlanRow.ticker == item.ticker)
            .order_by(PlanRow.generated_at.desc())
            .limit(1)
        )
        prev_plan_row = result.scalar_one_or_none()

    if prev_plan_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Watchlist item has no existing Plan; create a plan first "
                "before requesting a refresh."
            ),
        )

    risk_config = await get_user_risk_config(session, user.id)
    horizon = prev_plan_row.horizon  # str matches Horizon literal
    capital = Decimal(str(prev_plan_row.capital))
    try:
        new_plan = await generate_plan(
            user_id=user.id,
            ticker=item.ticker,
            horizon=horizon,  # type: ignore[arg-type]
            capital=capital,
            risk_config=risk_config,
            session=session,
            llm=llm,
        )
    except RiskRuleViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"risk-rule violation: {exc.code}",
        ) from exc
    except NoProviderAvailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM provider available",
        ) from exc

    # The generated plan was persisted by the orchestrator as a fresh Plan
    # row. Look it up so we can attach a PlanRevision to it.
    result = await session.execute(
        select(PlanRow)
        .where(PlanRow.user_id == user.id, PlanRow.ticker == item.ticker)
        .order_by(PlanRow.generated_at.desc())
        .limit(1)
    )
    new_plan_row = result.scalar_one()

    payload = new_plan.model_dump(mode="json")
    diff = _diff_plans(prev_plan_row.payload, payload)
    revision = PlanRevisionRow(
        plan_id=new_plan_row.id,
        payload=payload,
        diff_json=diff,
    )
    session.add(revision)
    item.last_plan_id = new_plan_row.id
    await session.commit()
    await session.refresh(revision)
    return revision


__all__ = ["router"]

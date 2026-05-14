"""Routes for the per-user watchlist."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.llm.router import NoProviderAvailableError
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
from app.scheduler import NoPriorPlanError, refresh_watchlist_item

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


@router.post(
    "/{item_id}/refresh",
    response_model=PlanRevisionRead,
    status_code=status.HTTP_200_OK,
)
async def refresh_watchlist_item_route(
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

    risk_config = await get_user_risk_config(session, user.id)
    try:
        # Pass the module-local `generate_plan` symbol explicitly so the
        # existing test that monkeypatches `watchlist.generate_plan` still
        # routes through the patched implementation.
        return await refresh_watchlist_item(
            session=session,
            llm=llm,
            item=item,
            risk_config=risk_config,
            generate_plan_fn=generate_plan,
        )
    except NoPriorPlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Watchlist item has no existing Plan; create a plan first "
                "before requesting a refresh."
            ),
        ) from exc
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


__all__ = ["router"]

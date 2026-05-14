"""Routes for plan generation, lookup, and listing."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.llm.router import NoProviderAvailableError
from app.models import Plan as PlanRow
from app.pipeline.orchestrator import generate_plan
from app.pipeline.risk import RiskRuleViolation
from app.pipeline.schema import Horizon, Plan
from app.routes.deps import (
    CurrentUser,
    LLMDep,
    SessionDep,
    get_user_risk_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plans", tags=["plans"])


class PlanCreateRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    horizon: Horizon
    capital: Decimal = Field(gt=Decimal("0"))


@router.post("", response_model=Plan, status_code=status.HTTP_200_OK)
async def create_plan(
    payload: PlanCreateRequest,
    user: CurrentUser,
    session: SessionDep,
    llm: LLMDep,
) -> Plan:
    risk_config = await get_user_risk_config(session, user.id)
    try:
        return await generate_plan(
            user_id=user.id,
            ticker=payload.ticker,
            horizon=payload.horizon,
            capital=payload.capital,
            risk_config=risk_config,
            session=session,
            llm=llm,
        )
    except RiskRuleViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"risk-rule violation: {exc.code}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except NoProviderAvailableError as exc:
        logger.exception("LLM router exhausted")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No LLM provider available",
        ) from exc
    except InvalidOperation as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("", response_model=list[Plan])
async def list_plans(
    user: CurrentUser,
    session: SessionDep,
    ticker: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Plan]:
    stmt = select(PlanRow).where(PlanRow.user_id == user.id)
    if ticker:
        stmt = stmt.where(PlanRow.ticker == ticker.upper().strip())
    stmt = stmt.order_by(desc(PlanRow.generated_at)).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    plans: list[Plan] = []
    for row in rows:
        try:
            plans.append(Plan.model_validate(row.payload))
        except Exception:
            logger.warning("could not validate stored plan %s — skipping", row.id)
    return plans


@router.get("/{plan_id}", response_model=Plan)
async def get_plan(
    plan_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> Plan:
    row = await session.get(PlanRow, plan_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found"
        )
    try:
        return Plan.model_validate(row.payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored plan payload is invalid",
        ) from exc


__all__ = ["router"]

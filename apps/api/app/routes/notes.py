"""Routes for free-form notes attached to a Plan."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.models import Note as NoteRow
from app.models import Plan as PlanRow
from app.routes.deps import CurrentUser, SessionDep

router = APIRouter(prefix="/plans", tags=["notes"])


class NoteCreate(BaseModel):
    text: str = Field(min_length=1)


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    body: str
    created_at: datetime
    updated_at: datetime


async def _ensure_owned_plan(
    session, user_id: uuid.UUID, plan_id: uuid.UUID
) -> PlanRow:
    row = await session.get(PlanRow, plan_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found"
        )
    return row


@router.post(
    "/{plan_id}/notes",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_note(
    plan_id: Annotated[uuid.UUID, Path()],
    payload: NoteCreate,
    user: CurrentUser,
    session: SessionDep,
) -> NoteRow:
    await _ensure_owned_plan(session, user.id, plan_id)
    note = NoteRow(plan_id=plan_id, body=payload.text)
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


@router.get("/{plan_id}/notes", response_model=list[NoteRead])
async def list_notes(
    plan_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    session: SessionDep,
) -> list[NoteRow]:
    await _ensure_owned_plan(session, user.id, plan_id)
    result = await session.execute(
        select(NoteRow)
        .where(NoteRow.plan_id == plan_id)
        .order_by(NoteRow.created_at)
    )
    return list(result.scalars().all())


__all__ = ["router"]

"""Routes for per-user settings (UserRiskConfig).

GET /settings  - return current config (created with defaults on first read).
PATCH /settings - update any subset of fields.

Coordinated with M8c: tiny route added so the web /settings page can read/write.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.routes.deps import CurrentUser, SessionDep, get_user_risk_config

router = APIRouter(prefix="/settings", tags=["settings"])

PreferredLLM = Literal["claude", "openai", "gemini"]


class UserRiskConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    risk_per_trade_pct: float
    max_position_pct: float
    preferred_llm: str


class UserRiskConfigPatch(BaseModel):
    risk_per_trade_pct: float | None = Field(default=None, gt=0, le=100)
    max_position_pct: float | None = Field(default=None, gt=0, le=100)
    preferred_llm: PreferredLLM | None = None


@router.get("", response_model=UserRiskConfigRead)
async def read_settings(user: CurrentUser, session: SessionDep) -> UserRiskConfigRead:
    cfg = await get_user_risk_config(session, user.id)
    return UserRiskConfigRead.model_validate(cfg)


@router.patch("", response_model=UserRiskConfigRead)
async def update_settings(
    payload: UserRiskConfigPatch,
    user: CurrentUser,
    session: SessionDep,
) -> UserRiskConfigRead:
    cfg = await get_user_risk_config(session, user.id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(cfg, key, value)
    await session.commit()
    await session.refresh(cfg)
    return UserRiskConfigRead.model_validate(cfg)


__all__ = ["router"]

"""Shared route dependencies for M6.

This module provides the temporary user resolution used until M7 wires the
real Auth.js JWT middleware. Until then, routes accept an ``X-User-Id``
header (or fall back to a fixed test user) and look up/create the row.
"""
# TODO(M7): replace with the real `app.auth.get_current_user` dependency.

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.llm.config import default_router
from app.llm.provider import LLMProvider
from app.llm.router import LLMRouter
from app.models import User, UserRiskConfig

_TEST_USER_EMAIL = "test@stockit.local"


async def _ensure_test_user(session: AsyncSession) -> User:
    result = await session.execute(select(User).where(User.email == _TEST_USER_EMAIL))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(email=_TEST_USER_EMAIL)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> User:
    """Resolve the request's user.

    For M6, identification is by header (or a default test user). M7 will
    replace this with a JWT-validating dependency.
    """
    if x_user_id:
        try:
            user_uuid = uuid.UUID(x_user_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-User-Id must be a UUID",
            ) from exc
        result = await session.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_uuid} not found",
            )
        return user
    return await _ensure_test_user(session)


async def get_user_risk_config(
    session: AsyncSession, user_id: uuid.UUID
) -> UserRiskConfig:
    """Return the user's risk config, creating a default row on first use."""
    result = await session.execute(
        select(UserRiskConfig).where(UserRiskConfig.user_id == user_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is not None:
        return cfg
    cfg = UserRiskConfig(user_id=user_id)
    session.add(cfg)
    await session.commit()
    await session.refresh(cfg)
    return cfg


# Module-level singleton built lazily so importing this module doesn't fail
# when API keys are unset (e.g. in unit tests that override this dependency).
_router_instance: LLMRouter | None = None


def get_llm_provider() -> LLMProvider:
    """Return the process-wide LLM router.

    Tests override this dependency on the FastAPI app rather than touching
    env vars.
    """
    global _router_instance
    if _router_instance is None:
        _router_instance = default_router()
    return _router_instance


CurrentUser = Annotated[User, Depends(get_current_user)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]


__all__ = [
    "CurrentUser",
    "LLMDep",
    "SessionDep",
    "get_current_user",
    "get_llm_provider",
    "get_user_risk_config",
]


def _testing() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST"))

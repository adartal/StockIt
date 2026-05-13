"""FastAPI auth dependency.

Validates the Auth.js v5 session JWT (HS256 signed with AUTH_SECRET) and
resolves it to a `User` row, creating one on first sight. Also enforces the
ALLOWED_EMAILS allowlist server-side so a leaked token for a non-allowlisted
address can't reach the API.

Auth.js v5 by default issues an *encrypted* JWE session token. To make tokens
verifiable here with the same secret, the web app overrides `jwt.encode` and
`jwt.decode` to produce HS256-signed JWTs (see apps/web/auth.ts).

The `sub` claim holds the user's email (Auth.js sets it to the user id, which
for the Resend email provider is the email address).
"""

from __future__ import annotations

import os
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User

ALGORITHM = "HS256"


def _allowed_emails() -> set[str]:
    raw = os.getenv("ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _auth_secret() -> str:
    secret = os.getenv("AUTH_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AUTH_SECRET is not configured",
        )
    return secret


def _extract_email(claims: dict[str, Any]) -> str:
    for key in ("email", "sub"):
        value = claims.get(key)
        if isinstance(value, str) and "@" in value:
            return value.lower()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token missing email claim",
    )


def _decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _auth_secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


async def _get_or_create_user(session: AsyncSession, email: str) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    user = User(email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    claims = _decode_token(token)
    email = _extract_email(claims)

    allowlist = _allowed_emails()
    if allowlist and email not in allowlist:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not in allowlist",
        )

    return await _get_or_create_user(session, email)


CurrentUser = Annotated[User, Depends(get_current_user)]


__all__ = ["ALGORITHM", "CurrentUser", "get_current_user"]

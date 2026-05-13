"""Tests for the FastAPI auth dependency.

Covers:
- Valid HS256 token for an allowlisted email resolves (and creates) a User.
- A second request for the same email reuses the existing row.
- Missing / malformed Authorization header → 401.
- Token signed with a different secret → 401.
- Expired token → 401.
- Allowlisted-but-wrong-algorithm token → 401.
- Non-allowlisted email with a valid token → 403.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator

import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth import ALGORITHM, CurrentUser
from app.db import get_session
from app.models import Base, User

ALLOWED_EMAIL = "alice@example.com"
OTHER_EMAIL = "mallory@example.com"
SECRET = "test-secret-do-not-use-in-prod-32bytes-min"
WRONG_SECRET = "different-secret-also-32-bytes-minimum"


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # Unique in-memory DB per test, shared between connections via the
    # `cache=shared` URI so concurrent sessions see the same data.
    db_id = uuid.uuid4().hex
    url = f"sqlite+aiosqlite:///file:auth-{db_id}?mode=memory&cache=shared&uri=true"
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("AUTH_SECRET", SECRET)
    monkeypatch.setenv("ALLOWED_EMAILS", f"{ALLOWED_EMAIL},  bob@example.com  ")

    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user: CurrentUser) -> dict[str, str]:
        return {"id": str(user.id), "email": user.email}

    # Also exercise via the CurrentUser alias on a second route (mirrors how
    # real routes will declare the dependency).
    @app.get("/whoami-explicit")
    async def whoami_explicit(user: CurrentUser) -> dict[str, str]:
        return {"id": str(user.id), "email": user.email}

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _make_token(
    email: str,
    *,
    secret: str = SECRET,
    algorithm: str = ALGORITHM,
    ttl_seconds: int = 3600,
) -> str:
    now = int(time.time())
    payload = {
        "sub": email,
        "email": email,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest.mark.asyncio
async def test_valid_token_resolves_user(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = _make_token(ALLOWED_EMAIL)
    resp = await client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == ALLOWED_EMAIL

    # Row persisted exactly once.
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == ALLOWED_EMAIL))
        users = result.scalars().all()
    assert len(users) == 1
    assert str(users[0].id) == body["id"]


@pytest.mark.asyncio
async def test_second_request_reuses_user(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = _make_token(ALLOWED_EMAIL)
    first = await client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    second = await client.get(
        "/whoami-explicit", headers={"Authorization": f"Bearer {token}"}
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == ALLOWED_EMAIL))
        users = result.scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_missing_authorization_header(client: AsyncClient) -> None:
    resp = await client.get("/whoami")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_malformed_authorization_header(client: AsyncClient) -> None:
    resp = await client.get(
        "/whoami", headers={"Authorization": "Token abc"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_signature(client: AsyncClient) -> None:
    token = _make_token(ALLOWED_EMAIL, secret=WRONG_SECRET)
    resp = await client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_token(client: AsyncClient) -> None:
    token = _make_token(ALLOWED_EMAIL, ttl_seconds=-60)
    resp = await client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_algorithm_rejected(client: AsyncClient) -> None:
    # `none` alg must never be accepted regardless of payload contents.
    token = jwt.encode({"sub": ALLOWED_EMAIL, "email": ALLOWED_EMAIL}, "", algorithm="none")
    resp = await client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_non_allowlisted_email_rejected(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = _make_token(OTHER_EMAIL)
    resp = await client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403

    # Must not have created a User row for the rejected email.
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.email == OTHER_EMAIL))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_case_insensitive_allowlist(client: AsyncClient) -> None:
    token = _make_token("Alice@Example.COM")
    resp = await client.get(
        "/whoami", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == ALLOWED_EMAIL

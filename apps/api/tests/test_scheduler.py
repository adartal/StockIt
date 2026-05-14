"""Tests for the M9 watchlist scheduler.

Covers the shared per-item refresh helper and the cron-job iterator. We
stub `generate_plan` to avoid the live data/LLM stack — the scheduler's
job is the diff + persistence + iteration logic, not the pipeline it
delegates to.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import (
    Base,
    DataCache,
    User,
    UserRiskConfig,
    WatchlistItem,
)
from app.models import (
    Plan as PlanRow,
)
from app.models import (
    PlanRevision as PlanRevisionRow,
)
from app.pipeline.schema import Plan
from app.scheduler import (
    DAILY_REFRESH_HOUR_UTC,
    DAILY_REFRESH_MINUTE_UTC,
    JOB_ID,
    NoPriorPlanError,
    build_scheduler,
    refresh_all_watchlist_items,
    refresh_watchlist_item,
)
from tests.conftest import FakeLLM, build_plan


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_id = uuid.uuid4().hex
    url = (
        f"sqlite+aiosqlite:///file:scheduler-{db_id}"
        "?mode=memory&cache=shared&uri=true"
    )
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        await engine.dispose()


async def _seed_user_with_watchlist(
    factory: async_sessionmaker[AsyncSession],
    *,
    ticker: str = "AAPL",
    with_prior_plan: bool = True,
    prior_thesis: str = "original thesis",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]:
    """Returns (user_id, watchlist_item_id, prior_plan_id_or_None)."""
    async with factory() as session:
        user = User(email=f"sched-{uuid.uuid4().hex}@stockit.local")
        session.add(user)
        await session.flush()
        risk = UserRiskConfig(user_id=user.id)
        session.add(risk)

        plan_id: uuid.UUID | None = None
        if with_prior_plan:
            seeded = build_plan(ticker=ticker).model_copy(
                update={"thesis": prior_thesis}
            )
            plan_row = PlanRow(
                user_id=user.id,
                ticker=ticker,
                horizon=seeded.horizon,
                capital=seeded.capital,
                generated_at=seeded.generated_at,
                payload=seeded.model_dump(mode="json"),
            )
            session.add(plan_row)
            await session.flush()
            plan_id = plan_row.id

        item = WatchlistItem(
            user_id=user.id, ticker=ticker, last_plan_id=plan_id
        )
        session.add(item)
        await session.commit()
        return user.id, item.id, plan_id


def _make_fake_generate_plan(new_thesis: str = "refreshed thesis"):
    async def _fake(**kwargs) -> Plan:
        plan = build_plan(ticker=kwargs["ticker"], horizon=kwargs["horizon"])
        plan = plan.model_copy(
            update={
                "capital": kwargs["capital"],
                "thesis": new_thesis,
                # Bump generated_at so the "most recent plan" lookup picks the
                # newly-inserted row deterministically over the seeded one.
                "generated_at": datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
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

    return _fake


@pytest.mark.asyncio
async def test_refresh_watchlist_item_writes_revision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, item_id, _ = await _seed_user_with_watchlist(session_factory)
    fake = _make_fake_generate_plan(new_thesis="new thesis")

    async with session_factory() as session:
        item = await session.get(WatchlistItem, item_id)
        assert item is not None
        risk = await session.get(UserRiskConfig, user_id)
        assert risk is not None
        revision = await refresh_watchlist_item(
            session=session,
            llm=FakeLLM(),
            item=item,
            risk_config=risk,
            generate_plan_fn=fake,
        )
        assert revision.id is not None
        assert revision.diff_json["ticker"] == "AAPL"
        assert revision.diff_json["thesis"] == {
            "before": "original thesis",
            "after": "new thesis",
        }
        assert "thesis" in revision.diff_json["changed_fields"]
        assert revision.payload["thesis"] == "new thesis"

    async with session_factory() as session:
        revisions = (await session.execute(select(PlanRevisionRow))).scalars().all()
        assert len(revisions) == 1
        item = await session.get(WatchlistItem, item_id)
        assert item is not None
        assert item.last_plan_id is not None
        # last_plan_id should now point at the newly-inserted plan row.
        plan = await session.get(PlanRow, item.last_plan_id)
        assert plan is not None
        assert plan.payload["thesis"] == "new thesis"


@pytest.mark.asyncio
async def test_refresh_without_prior_plan_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, item_id, _ = await _seed_user_with_watchlist(
        session_factory, with_prior_plan=False
    )
    fake = _make_fake_generate_plan()
    async with session_factory() as session:
        item = await session.get(WatchlistItem, item_id)
        assert item is not None
        risk = await session.get(UserRiskConfig, user_id)
        assert risk is not None
        with pytest.raises(NoPriorPlanError):
            await refresh_watchlist_item(
                session=session,
                llm=FakeLLM(),
                item=item,
                risk_config=risk,
                generate_plan_fn=fake,
            )


@pytest.mark.asyncio
async def test_refresh_purges_data_cache_rows_for_ticker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, item_id, _ = await _seed_user_with_watchlist(session_factory)
    # Pre-populate cache with rows for AAPL and an unrelated ticker.
    async with session_factory() as session:
        now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
        session.add_all(
            [
                DataCache(
                    key="AAPL:1d:180",
                    source="yfinance",
                    payload={"x": 1},
                    fetched_at=now,
                    ttl_seconds=86400,
                ),
                DataCache(
                    key="AAPL:news:30",
                    source="newsapi",
                    payload={"x": 1},
                    fetched_at=now,
                    ttl_seconds=3600,
                ),
                DataCache(
                    key="MSFT:1d:180",
                    source="yfinance",
                    payload={"x": 1},
                    fetched_at=now,
                    ttl_seconds=86400,
                ),
            ]
        )
        await session.commit()

    fake = _make_fake_generate_plan()
    async with session_factory() as session:
        item = await session.get(WatchlistItem, item_id)
        risk = await session.get(UserRiskConfig, user_id)
        assert item is not None and risk is not None
        await refresh_watchlist_item(
            session=session,
            llm=FakeLLM(),
            item=item,
            risk_config=risk,
            generate_plan_fn=fake,
        )

    async with session_factory() as session:
        remaining = (await session.execute(select(DataCache))).scalars().all()
        keys = sorted(r.key for r in remaining)
        assert keys == ["MSFT:1d:180"]


@pytest.mark.asyncio
async def test_refresh_all_iterates_and_skips_missing_prior(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_user_with_watchlist(
        session_factory, ticker="AAPL", with_prior_plan=True
    )
    await _seed_user_with_watchlist(
        session_factory, ticker="MSFT", with_prior_plan=False
    )

    fake = _make_fake_generate_plan(new_thesis="batch refresh")
    summary = await refresh_all_watchlist_items(
        session_factory=session_factory,
        llm=FakeLLM(),
        generate_plan_fn=fake,
    )
    assert summary == {"refreshed": 1, "skipped": 1, "errors": 0}

    async with session_factory() as session:
        revisions = (await session.execute(select(PlanRevisionRow))).scalars().all()
        assert len(revisions) == 1
        assert revisions[0].payload["thesis"] == "batch refresh"


@pytest.mark.asyncio
async def test_refresh_all_logs_and_continues_on_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_user_with_watchlist(
        session_factory, ticker="AAPL", with_prior_plan=True
    )
    await _seed_user_with_watchlist(
        session_factory, ticker="GOOG", with_prior_plan=True
    )

    calls: list[str] = []

    async def _flaky(**kwargs) -> Plan:
        ticker = kwargs["ticker"]
        calls.append(ticker)
        if ticker == "GOOG":
            raise RuntimeError("boom")
        return await _make_fake_generate_plan(new_thesis="ok")(**kwargs)

    summary = await refresh_all_watchlist_items(
        session_factory=session_factory,
        llm=FakeLLM(),
        generate_plan_fn=_flaky,
    )
    assert summary["refreshed"] == 1
    assert summary["errors"] == 1
    assert summary["skipped"] == 0
    assert sorted(calls) == ["AAPL", "GOOG"]


def test_build_scheduler_registers_daily_22_utc_job() -> None:
    scheduler = build_scheduler()
    job = scheduler.get_job(JOB_ID)
    assert job is not None
    trigger = job.trigger
    # CronTrigger exposes fields including hour / minute as iterable expressions.
    fields = {f.name: str(f) for f in trigger.fields}
    assert fields["hour"] == str(DAILY_REFRESH_HOUR_UTC)
    assert fields["minute"] == str(DAILY_REFRESH_MINUTE_UTC)
    assert str(trigger.timezone) == "UTC"

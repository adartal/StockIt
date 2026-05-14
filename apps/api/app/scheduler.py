"""Watchlist scheduler (M9).

Runs a daily APScheduler cron at 22:00 UTC that refreshes every
`WatchlistItem` in the database: invalidates that ticker's `data_cache`
rows, re-runs the full pipeline through `generate_plan`, diffs the new
plan against the previously-stored plan, and persists a `PlanRevision`
row carrying both the new plan payload and a structured diff.

The same per-item refresh is exposed as `refresh_watchlist_item`, called
from the on-demand `POST /watchlist/{id}/refresh` route. The route and
the cron path go through identical logic so a manual refresh is
indistinguishable on disk from a scheduled one.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import async_session_factory
from app.llm.provider import LLMProvider
from app.models import DataCache, UserRiskConfig, WatchlistItem
from app.models import Plan as PlanRow
from app.models import PlanRevision as PlanRevisionRow
from app.pipeline.diff import diff_plans
from app.pipeline.orchestrator import generate_plan as _default_generate_plan
from app.pipeline.schema import Horizon, Plan
from app.routes.deps import get_llm_provider, get_user_risk_config

logger = logging.getLogger(__name__)

# Cron schedule for the daily refresh job. UTC is intentional — the
# upstream data sources (yfinance, EDGAR, FRED) and our reviewers all
# tick on US-market-close-ish wall clock; 22:00 UTC is post-close
# regardless of DST.
DAILY_REFRESH_HOUR_UTC = 22
DAILY_REFRESH_MINUTE_UTC = 0
JOB_ID = "watchlist_daily_refresh"

# Type alias for the orchestrator entrypoint so tests can inject a fake
# without monkeypatching the module-level import.
GeneratePlanFn = Callable[..., Awaitable[Plan]]


class NoPriorPlanError(Exception):
    """Raised when a watchlist item has no Plan to diff against.

    Surfaced as HTTP 409 by the route; logged-and-skipped by the cron.
    """


async def _purge_ticker_cache(session: AsyncSession, ticker: str) -> int:
    """Drop `data_cache` rows whose key starts with ``{ticker}:``.

    Every fetcher in `pipeline/data/*` prefixes its cache key with the
    upper-cased ticker (e.g. ``AAPL:1d:180``), with the lone exception
    of `macro.py` which keys by sector. We deliberately do not purge the
    macro entries: the daily refresh would otherwise hammer FRED on
    every item for no real signal, since macro context shifts on a much
    slower clock than ticker-specific data.

    Returns the number of rows deleted (for logging).
    """
    upper = ticker.upper().strip()
    if not upper:
        return 0
    result = await session.execute(
        delete(DataCache).where(DataCache.key.like(f"{upper}:%"))
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def _load_prev_plan_row(
    session: AsyncSession, item: WatchlistItem
) -> PlanRow | None:
    """Find the most recent Plan to diff against.

    Prefers `item.last_plan_id` (the explicit pointer set by the prior
    refresh / initial plan generation). Falls back to the most recent
    Plan for the same (user, ticker) — handy when M6 created a plan via
    `POST /plans` before any refresh ran.
    """
    if item.last_plan_id is not None:
        row = await session.get(PlanRow, item.last_plan_id)
        if row is not None:
            return row
    result = await session.execute(
        select(PlanRow)
        .where(PlanRow.user_id == item.user_id, PlanRow.ticker == item.ticker)
        .order_by(PlanRow.generated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _load_new_plan_row(
    session: AsyncSession, user_id: Any, ticker: str
) -> PlanRow:
    result = await session.execute(
        select(PlanRow)
        .where(PlanRow.user_id == user_id, PlanRow.ticker == ticker)
        .order_by(PlanRow.generated_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        # generate_plan should always have persisted at least one row.
        raise RuntimeError(
            f"expected a Plan row for user={user_id} ticker={ticker} "
            "after generate_plan but found none"
        )
    return row


async def refresh_watchlist_item(
    *,
    session: AsyncSession,
    llm: LLMProvider,
    item: WatchlistItem,
    risk_config: UserRiskConfig,
    generate_plan_fn: GeneratePlanFn | None = None,
    force_cache_refresh: bool = True,
) -> PlanRevisionRow:
    """Refresh a single watchlist item and persist a PlanRevision.

    Shared entrypoint for both the daily cron job and the on-demand
    `POST /watchlist/{id}/refresh` route. Caller owns the session;
    this function commits before returning so the route can call
    `session.refresh(revision)` to surface server-defaulted columns.

    Raises:
        NoPriorPlanError: if the item has never been planned yet — the
            scheduler/route cannot compute a diff without a baseline.

    Other exceptions (`RiskRuleViolation`, `NoProviderAvailableError`,
    transport errors) propagate; the caller decides whether to log-and-skip
    or translate to an HTTP error.
    """
    gen_plan = generate_plan_fn or _default_generate_plan

    prev_plan_row = await _load_prev_plan_row(session, item)
    if prev_plan_row is None:
        raise NoPriorPlanError(
            f"watchlist item {item.id} (ticker={item.ticker}) has no prior Plan"
        )

    # Snapshot the prev payload before generate_plan mutates session state.
    prev_payload = dict(prev_plan_row.payload)
    horizon: Horizon = prev_plan_row.horizon  # type: ignore[assignment]
    capital = Decimal(str(prev_plan_row.capital))

    if force_cache_refresh:
        purged = await _purge_ticker_cache(session, item.ticker)
        logger.info(
            "scheduler: purged %d data_cache rows for ticker=%s", purged, item.ticker
        )

    new_plan = await gen_plan(
        user_id=item.user_id,
        ticker=item.ticker,
        horizon=horizon,
        capital=capital,
        risk_config=risk_config,
        session=session,
        llm=llm,
    )
    new_plan_row = await _load_new_plan_row(session, item.user_id, item.ticker)

    old_plan = Plan.model_validate(prev_payload)
    diff = diff_plans(old_plan, new_plan)
    payload = new_plan.model_dump(mode="json")

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


async def refresh_all_watchlist_items(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    llm: LLMProvider,
    generate_plan_fn: GeneratePlanFn | None = None,
) -> dict[str, int]:
    """Iterate every WatchlistItem and refresh it.

    A single failure (missing prior plan, risk violation, fetcher error)
    is logged and skipped — one bad ticker should not stop the rest of
    the watchlist from getting its nightly refresh.

    Returns a small summary dict suitable for log lines and tests:
    ``{"refreshed": int, "skipped": int, "errors": int}``.
    """
    refreshed = 0
    skipped = 0
    errors = 0

    async with session_factory() as session:
        result = await session.execute(select(WatchlistItem))
        items = list(result.scalars().all())

    for item in items:
        async with session_factory() as session:
            # Re-attach item by id in this fresh session so writes commit cleanly.
            fresh_item = await session.get(WatchlistItem, item.id)
            if fresh_item is None:
                continue
            try:
                risk_config = await get_user_risk_config(session, fresh_item.user_id)
                await refresh_watchlist_item(
                    session=session,
                    llm=llm,
                    item=fresh_item,
                    risk_config=risk_config,
                    generate_plan_fn=generate_plan_fn,
                )
                refreshed += 1
            except NoPriorPlanError as exc:
                logger.info("scheduler: skipping %s — %s", fresh_item.ticker, exc)
                skipped += 1
            except Exception:
                logger.exception(
                    "scheduler: refresh failed for ticker=%s item=%s",
                    fresh_item.ticker,
                    fresh_item.id,
                )
                errors += 1

    summary = {"refreshed": refreshed, "skipped": skipped, "errors": errors}
    logger.info("scheduler: daily refresh complete %s", summary)
    return summary


def _scheduler_enabled() -> bool:
    # Routes' integration test suite sets PYTEST_CURRENT_TEST; tests should
    # never bring up a live cron alongside the FastAPI app. Explicit override
    # via STOCKIT_SCHEDULER_ENABLED=1 wins (used by the scheduler tests).
    override = os.getenv("STOCKIT_SCHEDULER_ENABLED")
    if override is not None:
        return override == "1"
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return True


def build_scheduler(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    llm_factory: Callable[[], LLMProvider] | None = None,
) -> AsyncIOScheduler:
    """Construct (but do not start) the AsyncIOScheduler.

    The cron callable closes over the session factory and LLM factory so
    it can build its own short-lived sessions per item rather than
    sharing a single long-lived session across the entire watchlist.
    """
    factory = session_factory or async_session_factory
    make_llm = llm_factory or get_llm_provider
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _job() -> None:
        try:
            llm = make_llm()
        except Exception:
            logger.exception("scheduler: failed to construct LLM provider; skipping run")
            return
        await refresh_all_watchlist_items(session_factory=factory, llm=llm)

    scheduler.add_job(
        _job,
        CronTrigger(
            hour=DAILY_REFRESH_HOUR_UTC,
            minute=DAILY_REFRESH_MINUTE_UTC,
            timezone="UTC",
        ),
        id=JOB_ID,
        replace_existing=True,
    )
    return scheduler


__all__ = [
    "DAILY_REFRESH_HOUR_UTC",
    "DAILY_REFRESH_MINUTE_UTC",
    "JOB_ID",
    "NoPriorPlanError",
    "_scheduler_enabled",
    "build_scheduler",
    "refresh_all_watchlist_items",
    "refresh_watchlist_item",
]

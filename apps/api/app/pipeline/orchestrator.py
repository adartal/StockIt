"""End-to-end plan pipeline orchestrator.

Wires the four data fetchers, four analyst stages, the synthesizer, and
the deterministic risk post-processor into a single call. Persists the
resulting `Plan` and returns it.

Pipeline shape::

    data       parallel  prices, fundamentals, news
                         then macro (needs fundamentals.sector)
    analysts   parallel  fundamentals, technicals, news, macro
    synth      single LLM call
    risk       deterministic; on RiskRuleViolation(stop_required)
               we re-prompt synth ONCE with a clarifying note
    persist    write Plan row + update watchlist.last_plan_id
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.provider import LLMProvider, Message
from app.models import Plan as PlanRow
from app.models import UserRiskConfig, WatchlistItem
from app.pipeline.analysts import fundamentals as fundamentals_analyst
from app.pipeline.analysts import macro as macro_analyst
from app.pipeline.analysts import news as news_analyst
from app.pipeline.analysts import technicals as technicals_analyst
from app.pipeline.data.fundamentals import FundamentalsBundle, fetch_fundamentals
from app.pipeline.data.macro import MacroBundle, fetch_macro_context
from app.pipeline.data.news import NewsItem, fetch_news
from app.pipeline.data.prices import Interval, fetch_ohlcv
from app.pipeline.risk import RiskRuleViolation, apply_risk_rules
from app.pipeline.schema import AnalystOutput, Horizon, Plan
from app.pipeline.synth import (
    build_cache_blocks,
    build_user_block,
    synthesize,
)

logger = logging.getLogger(__name__)


# Horizon → (interval, lookback_days) for the technicals data slice.
_HORIZON_PRICE_PROFILE: dict[Horizon, tuple[Interval, int]] = {
    "intraday": ("5m", 5),
    "swing": ("1d", 180),
    "long_term": ("1wk", 730),
}

# Horizon → news lookback window.
_HORIZON_NEWS_LOOKBACK: dict[Horizon, int] = {
    "intraday": 7,
    "swing": 30,
    "long_term": 90,
}

_DEFAULT_SECTOR = "Information Technology"

_CLARIFY_NOTE_PREFIX = (
    "Your previous response was rejected by the risk post-processor. "
    "Re-emit ONE strict-JSON Plan with a protective stop that is strictly "
    "below entry.levels[0]. Risk-rule violation follows:\n\n"
)


async def _safe_fetch_news(ticker: str, lookback_days: int) -> list[NewsItem]:
    try:
        return await fetch_news(ticker, lookback_days=lookback_days)
    except Exception as exc:
        logger.warning("news fetch failed for %s: %s", ticker, exc)
        return []


async def _safe_fetch_fundamentals(ticker: str) -> FundamentalsBundle:
    try:
        return await fetch_fundamentals(ticker)
    except Exception as exc:
        logger.warning("fundamentals fetch failed for %s: %s", ticker, exc)
        return FundamentalsBundle()


async def _safe_fetch_macro(sector: str | None) -> MacroBundle | None:
    if not sector:
        return None
    try:
        return await fetch_macro_context(sector)
    except ValueError:
        try:
            return await fetch_macro_context(_DEFAULT_SECTOR)
        except Exception as exc:
            logger.warning("macro fallback fetch failed: %s", exc)
            return None
    except Exception as exc:
        logger.warning("macro fetch failed for %s: %s", sector, exc)
        return None


def _empty_macro_output() -> AnalystOutput:
    return AnalystOutput(
        findings=["Macro context unavailable."],
        confidence=0.0,
        key_metrics={},
        citations=[],
    )


async def _run_macro_analyst(
    ticker: str,
    macro: MacroBundle | None,
    horizon: Horizon,
    llm: LLMProvider,
) -> AnalystOutput:
    if macro is None:
        return _empty_macro_output()
    try:
        return await macro_analyst.run(ticker, macro, horizon, llm)
    except Exception as exc:
        logger.warning("macro analyst failed: %s", exc)
        return _empty_macro_output()


async def _resynth_with_clarification(
    ticker: str,
    horizon: Horizon,
    capital: Decimal,
    risk_config: UserRiskConfig,
    analyst_outputs: dict[str, AnalystOutput],
    llm: LLMProvider,
    note: str,
) -> Plan:
    """One-shot synth re-prompt that appends a clarifying note.

    Re-uses the synth module's exported cache + user-block helpers so the
    prompt structure stays in lockstep with `synthesize` itself.
    """
    as_of = datetime.now(UTC)
    cache_blocks = build_cache_blocks(horizon)
    user_block = build_user_block(
        ticker, horizon, capital, risk_config, analyst_outputs, as_of
    )
    messages: list[Message] = [
        {"role": "user", "content": user_block},
        {"role": "user", "content": _CLARIFY_NOTE_PREFIX + note},
    ]
    result = await llm.complete_structured(
        messages=messages,
        response_model=Plan,
        cache_blocks=cache_blocks,
        max_retries=1,
    )
    if not isinstance(result, Plan):
        result = Plan.model_validate(result.model_dump())
    return result


async def _load_user_watchlist(
    session: AsyncSession, user_id: uuid.UUID
) -> list[WatchlistItem]:
    result = await session.execute(
        select(WatchlistItem).where(WatchlistItem.user_id == user_id)
    )
    return list(result.scalars().all())


async def _load_user_plans(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Plan]:
    result = await session.execute(
        select(PlanRow).where(PlanRow.user_id == user_id)
    )
    plans: list[Plan] = []
    for row in result.scalars().all():
        try:
            plans.append(Plan.model_validate(row.payload))
        except Exception:
            continue
    return plans


def _serialize_plan(plan: Plan) -> dict[str, Any]:
    return plan.model_dump(mode="json")


async def generate_plan(
    user_id: uuid.UUID,
    ticker: str,
    horizon: Horizon,
    capital: Decimal,
    risk_config: UserRiskConfig,
    *,
    session: AsyncSession,
    llm: LLMProvider,
) -> Plan:
    """Run the full pipeline for `ticker` and persist the resulting Plan."""
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")

    interval, lookback_days = _HORIZON_PRICE_PROFILE[horizon]
    news_lookback = _HORIZON_NEWS_LOOKBACK[horizon]

    prices_task = fetch_ohlcv(ticker, interval, lookback_days)
    fundamentals_task = _safe_fetch_fundamentals(ticker)
    news_task = _safe_fetch_news(ticker, news_lookback)

    prices_df, fundamentals_bundle, news_items = await asyncio.gather(
        prices_task, fundamentals_task, news_task
    )
    macro_bundle = await _safe_fetch_macro(fundamentals_bundle.sector)

    analyst_results = await asyncio.gather(
        fundamentals_analyst.run(ticker, fundamentals_bundle, horizon, llm),
        technicals_analyst.run(ticker, prices_df, horizon, llm),
        news_analyst.run(ticker, news_items, horizon, llm),
        _run_macro_analyst(ticker, macro_bundle, horizon, llm),
    )
    analyst_outputs: dict[str, AnalystOutput] = {
        "fundamentals": analyst_results[0],
        "technicals": analyst_results[1],
        "news": analyst_results[2],
        "macro": analyst_results[3],
    }

    plan = await synthesize(
        ticker, horizon, capital, risk_config, analyst_outputs, llm
    )

    existing_watchlist = await _load_user_watchlist(session, user_id)
    existing_plans = await _load_user_plans(session, user_id)

    sector_lookup = _sector_lookup_from(fundamentals_bundle)

    try:
        plan, _ = apply_risk_rules(
            plan,
            capital=capital,
            risk_config=risk_config,
            existing_watchlist=existing_watchlist,
            existing_plans=existing_plans,
            sector_lookup=sector_lookup,
        )
    except RiskRuleViolation as violation:
        if violation.code != "stop_required":
            raise
        logger.info(
            "risk-rule violation %s — re-prompting synth once", violation.code
        )
        plan = await _resynth_with_clarification(
            ticker, horizon, capital, risk_config, analyst_outputs, llm,
            note=str(violation),
        )
        plan, _ = apply_risk_rules(
            plan,
            capital=capital,
            risk_config=risk_config,
            existing_watchlist=existing_watchlist,
            existing_plans=existing_plans,
            sector_lookup=sector_lookup,
        )

    await _persist_plan(session, user_id, plan)
    return plan


def _sector_lookup_from(fundamentals_bundle: FundamentalsBundle):
    sector = fundamentals_bundle.sector

    def lookup(_ticker: str) -> str | None:
        return sector

    return lookup


async def _persist_plan(
    session: AsyncSession, user_id: uuid.UUID, plan: Plan
) -> PlanRow:
    row = PlanRow(
        user_id=user_id,
        ticker=plan.ticker,
        horizon=plan.horizon,
        capital=plan.capital,
        generated_at=plan.generated_at,
        payload=_serialize_plan(plan),
    )
    session.add(row)
    await session.flush()
    await session.commit()
    await session.refresh(row)
    return row


__all__ = ["generate_plan"]

"""M5b — synthesizer.

One LLM call that turns four `AnalystOutput`s into a candidate `Plan`.
The synthesizer never sees raw market/filing data; it only consumes
analyst summaries (findings, key_metrics, citations) plus the user's
ticker/horizon/capital/risk-config.

The risk post-processor (M5a) is the final guard on the plan: it
overrides `sizing` from capital + per-trade risk and raises if the
stop is missing or non-protective. The synth prompt still asks for a
stop because the risk module will catch a bad plan rather than fix
one — emitting one is cheaper than re-prompting.

Validation strategy: instructor handles low-level JSON/schema retries
inside one provider call (max_retries=1). If a `ValidationError` still
surfaces, synth does *one* outer retry with a clarifying user note
quoting the validation failure. Two LLM calls is the worst case.

Model selection: the orchestrator passes the configured `LLMProvider`,
so the model is set provider-side. Default per ROADMAP is Opus 4.7 for
synthesis quality (see `app/llm/claude.py:DEFAULT_SYNTH_MODEL`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError

from app.llm.provider import LLMProvider, Message
from app.models import UserRiskConfig
from app.pipeline.schema import AnalystOutput, Horizon, Plan

PERSONA_BLOCK = (
    "You are a discretionary portfolio manager building one actionable "
    "trading plan for a single ticker and a single user. Four sector "
    "analysts (fundamentals, technicals, news, macro) have already done "
    "the data work and handed you their summaries. You do not see raw "
    "prices, filings, or articles — only what the analysts wrote. Your "
    "job is to weigh those summaries against the user's horizon and "
    "capital and produce one strict-JSON Plan."
)

SCHEMA_BLOCK = """Output strictly one JSON object matching the Plan schema:

{
  "ticker": string,                    // echo the user-supplied ticker
  "horizon": "intraday" | "swing" | "long_term",
  "capital": string,                   // decimal string, echo user input
  "generated_at": string,              // ISO-8601 UTC timestamp from user block
  "thesis": string,                    // 1–3 sentence directional read
  "conviction": "low" | "medium" | "high",
  "entry": {
    "kind": "limit" | "market" | "stop_limit",
    "levels": [string, ...],           // decimal strings, ascending or single
    "conditions": string               // trigger/setup in plain English
  },
  "sizing": {
    "risk_pct": number,                // 0–100; risk module will override
    "shares": integer,                 // 0 acceptable; risk module overrides
    "dollar_exposure": string,         // decimal; risk module overrides
    "R_value": string                  // decimal; risk module overrides
  },
  "stop": {
    "price": string,                   // decimal, strictly below entry[0] for longs
    "kind": "technical" | "atr" | "fixed_pct",
    "rationale": string
  },
  "exits": [
    {
      "kind": "scale_out" | "time_stop" | "invalidation",
      "price": string | null,
      "trigger": string,
      "portion": number | null         // 0.0–1.0 fraction of position
    }, ...
  ],
  "catalysts": [
    {"date": "YYYY-MM-DD", "description": string,
     "kind": "earnings" | "macro" | "corporate" | "other"}, ...
  ],
  "risk_flags": [],                    // leave empty; risk module populates
  "review_cadence": string,            // e.g. "daily until earnings", "weekly"
  "sources": [
    {"url": string, "title": string, "source": string, "fetched_at": string},
    ...
  ]
}

Rules:
- Output JSON only. No prose before or after. No code fences.
- Every URL in `sources` must come from one of the analyst citations
  in the user block. Do not invent URLs.
- Echo `ticker`, `horizon`, `capital`, `generated_at` from the user block
  verbatim. The user block is the source of truth for those fields."""

RULES_BLOCK = """Plan-construction rules:

1. STOP-LOSS IS MANDATORY. Every plan MUST include `stop` with a price
   strictly below `entry.levels[0]` (long-only assumption). Plans without
   a protective stop are rejected by the downstream risk module and force
   a re-prompt — emit one.
2. `sizing` will be overwritten by the deterministic risk module from
   capital × risk-per-trade ÷ (entry − stop). Emit plausible values but
   do not agonize over them; the override is authoritative.
3. `risk_flags` MUST be an empty list. The risk module populates flags.
4. Synthesize across analysts; do not parrot a single analyst. When
   analysts disagree, name the disagreement in the thesis and let it
   move `conviction` toward "low" or "medium".
5. Weight analysts by horizon — see weighting rules in the user block.
6. `conviction` reflects evidence strength, not enthusiasm. Conflicting
   analyst reads or low analyst confidence → "low". Aligned high-confidence
   reads → "medium" or "high".
7. `thesis` is 1–3 sentences. Name the dominant analyst signal and the
   key counter-signal (if any). No hedging boilerplate.
8. `sources` must enumerate the analyst citations you actually relied on.
   At minimum, cite one URL from every analyst whose finding shaped the
   thesis. Copy `url`, `title`, `source`, `fetched_at` verbatim from the
   analyst citation."""

GUARDS_BLOCK = """You receive ONLY analyst summaries. You do not have access to raw
prices, filings, articles, or macro feeds. If the analyst outputs are
thin or conflicting, lower `conviction` and shorten the thesis rather
than invent supporting evidence. Do not cite a URL that does not appear
in the analyst citations below. Do not output prose outside the JSON."""

HORIZON_WEIGHTING: dict[Horizon, str] = {
    "intraday": (
        "Horizon: intraday (hours to ~2 trading days). Weight technicals "
        "and very recent news heavily. Fundamentals are background unless "
        "an earnings/guidance event lands inside the window. Macro is "
        "regime context only. `review_cadence` should reference sessions "
        "or intraday checkpoints."
    ),
    "swing": (
        "Horizon: swing (~1–8 weeks). Weight technicals (daily bars) and "
        "news inside the last 30 days as primary signal. Fundamentals "
        "matter when a fresh print or guidance change lands in the window. "
        "Macro sets the backdrop. `review_cadence` is typically daily "
        "around catalysts, weekly otherwise."
    ),
    "long_term": (
        "Horizon: long_term (6+ months). Fundamentals dominate. News is "
        "thematic, not event-driven. Technicals are weekly/monthly trend "
        "context. Macro regime is a first-class input. `review_cadence` "
        "is typically monthly or quarterly with catalyst-driven exceptions."
    ),
}

CLARIFY_PREFIX = (
    "Your previous response failed Plan-schema validation. Validation "
    "error follows. Re-emit ONE strict-JSON Plan object that matches the "
    "schema exactly. Remember: `stop` is mandatory and must be strictly "
    "below `entry.levels[0]`; `risk_flags` must be `[]`; echo the "
    "user-supplied ticker / horizon / capital / generated_at verbatim. "
    "Output JSON only.\n\nValidation error:\n"
)


def build_cache_blocks(horizon: Horizon) -> list[str]:
    """Cacheable system prompt blocks. Horizon-dependent block sits in
    the middle so per-horizon prefixes share cache up to that point."""
    return [
        PERSONA_BLOCK,
        SCHEMA_BLOCK,
        HORIZON_WEIGHTING[horizon],
        RULES_BLOCK,
        GUARDS_BLOCK,
    ]


def _serialize_analysts(
    analyst_outputs: dict[str, AnalystOutput],
) -> dict[str, dict[str, object]]:
    """Stable analyst ordering for prompt reproducibility / cache hits."""
    preferred_order = ("fundamentals", "technicals", "news", "macro")
    ordered: dict[str, dict[str, object]] = {}
    for name in preferred_order:
        if name in analyst_outputs:
            ordered[name] = analyst_outputs[name].model_dump(mode="json")
    for name in sorted(analyst_outputs):
        if name not in ordered:
            ordered[name] = analyst_outputs[name].model_dump(mode="json")
    return ordered


def build_user_block(
    ticker: str,
    horizon: Horizon,
    capital: Decimal,
    risk_config: UserRiskConfig,
    analyst_outputs: dict[str, AnalystOutput],
    as_of: datetime,
) -> str:
    payload = _serialize_analysts(analyst_outputs)
    return (
        f"Ticker: {ticker}\n"
        f"Horizon: {horizon}\n"
        f"Capital (USD): {capital}\n"
        f"Generated at (UTC): {as_of.isoformat()}\n"
        f"User risk profile: risk_per_trade_pct={risk_config.risk_per_trade_pct}, "
        f"max_position_pct={risk_config.max_position_pct}\n\n"
        "Analyst summaries (your only data source):\n"
        f"{json.dumps(payload, indent=2, default=str)}\n\n"
        "Produce one JSON object matching the Plan schema. JSON only. "
        "Emit a stop-loss strictly below entry."
    )


async def synthesize(
    ticker: str,
    horizon: Horizon,
    capital: Decimal,
    risk_config: UserRiskConfig,
    analyst_outputs: dict[str, AnalystOutput],
    llm: LLMProvider,
) -> Plan:
    """Run the synthesizer for `ticker` over `horizon`.

    One LLM call by default. On Plan-schema `ValidationError`, retries
    once with a clarifying note that quotes the validation failure.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")

    as_of = datetime.now(UTC)
    cache_blocks = build_cache_blocks(horizon)
    user_block = build_user_block(
        ticker, horizon, capital, risk_config, analyst_outputs, as_of
    )
    messages: list[Message] = [{"role": "user", "content": user_block}]

    try:
        result = await llm.complete_structured(
            messages=messages,
            response_model=Plan,
            cache_blocks=cache_blocks,
            max_retries=1,
        )
    except ValidationError as first_err:
        clarifying = CLARIFY_PREFIX + str(first_err)
        retry_messages: list[Message] = [
            *messages,
            {"role": "user", "content": clarifying},
        ]
        result = await llm.complete_structured(
            messages=retry_messages,
            response_model=Plan,
            cache_blocks=cache_blocks,
            max_retries=1,
        )

    if not isinstance(result, Plan):
        # complete_structured returns BaseModel; coerce defensively.
        result = Plan.model_validate(result.model_dump())
    return result


__all__ = [
    "CLARIFY_PREFIX",
    "GUARDS_BLOCK",
    "HORIZON_WEIGHTING",
    "PERSONA_BLOCK",
    "RULES_BLOCK",
    "SCHEMA_BLOCK",
    "build_cache_blocks",
    "build_user_block",
    "synthesize",
]

"""M4a — fundamentals analyst.

One LLM call producing an :class:`AnalystOutput` from a
:class:`FundamentalsBundle`. The prompt follows
docs/analyst-prompt-design.md: five cached system blocks (persona,
schema reminder, horizon rules, citation+confidence rubric, bias guards)
plus a fresh user block carrying ticker, horizon, weighting hint,
provenance index, and JSON-serialized data payload.

The analyst module — not the LLM — owns the provenance index. URLs
come from the data bundle (10-K, 10-Q) plus a constructable Yahoo
quote URL; `fetched_at` is stamped here so the prompt's "copy verbatim"
rule has a stable source.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.llm.provider import LLMProvider, Message
from app.pipeline.data.fundamentals import FundamentalsBundle
from app.pipeline.schema import AnalystOutput, Horizon

ANALYST_ROLE = "equity fundamentals analyst"

PERSONA_BLOCK = (
    f"You are a {ANALYST_ROLE} for U.S.-listed equities. Your job is to "
    "analyze the data provided below for the ticker and horizon given, and "
    "emit one JSON object describing what the data shows. You do not advise "
    "on positions; you describe what is true in the data."
)

SCHEMA_BLOCK = """Output strictly one JSON object with this exact shape and no other keys:

{
  "findings": [string, ...],            // 3–7 declarative observations
  "confidence": number,                 // 0.0–1.0, calibrated per the rubric
  "key_metrics": { ... },               // numeric/categorical facts you extracted
  "citations": [
    {"url": string, "title": string, "source": string, "fetched_at": string},
    ...
  ]
}

Rules:
- Output JSON only. No prose before or after. No code fences.
- Every URL in `citations` must appear in the provided provenance index.
- Every claim in `findings` that names a number, event, filing, or quote
  must be backed by at least one citation.
- `fetched_at` must be copied verbatim from the provenance index entry."""

HORIZON_BLOCKS: dict[Horizon, str] = {
    "intraday": """Horizon: intraday (hours to ~2 trading days).

- Weight recency aggressively: data older than 5 trading days is context, not signal.
- News must be ≤ 48h old to count as a primary signal. Older items are background.
- Price action and short-window technicals dominate. Fundamentals are near-static
  background; only fundamentals events (earnings, guidance, filings) within the
  last 5 trading days carry weight.
- Macro is regime context only — note the regime, do not over-weight it.
- Findings should reference specific bars, sessions, or news within the last
  1–5 trading days.""",
    "swing": """Horizon: swing (~1–8 weeks).

- Weight the last 1–3 months of data.
- News within the last 30 days is primary signal; older news is context.
- Technicals at the daily-bar timeframe dominate (20- and 50-day SMAs, RSI(14)
  daily, MACD daily). Intraday noise is not the focus.
- Fundamentals matter when there is a fresh earnings/guidance/filing catalyst
  inside the swing window or expected within it.
- Macro regime sets the backdrop and is more material than at intraday.""",
    "long_term": """Horizon: long_term (6+ months).

- Weight the trailing 12–24 months of data.
- Fundamentals dominate: profitability trends, revenue growth durability,
  balance-sheet quality, capital structure.
- News is thematic, not event-driven — look for persistent narratives, not single headlines.
- Technicals are weekly/monthly trend context, not setup-grade signal.
- Macro regime (rate path, recession signals, sector flows) is a first-class input.""",
}

RUBRIC_BLOCK = """Citation rules:

1. Every claim in `findings` that references a specific number, filing,
   news item, regulatory event, or quote must be backed by at least one
   citation in the `citations` list.
2. Every URL you cite MUST appear verbatim in the provenance index given
   in the user block. If you cannot find a provenance entry that supports
   a claim, either remove the claim or lower your confidence.
3. Use the `title`, `source`, and `fetched_at` fields exactly as they
   appear in the provenance index. Do not modify them.
4. A finding may cite multiple URLs. Repeat the URLs in `citations` — no
   deduplication is required.
5. General market-data observations cite the single data-source URL for
   that data slice.
6. If the data slice is empty, emit zero or one explanatory finding,
   confidence ≤ 0.3, and an empty citations list. This is the only case
   where citations may be empty.

Confidence calibration:

- 0.9  Strong, consistent signal across the data. Reserved — use sparingly.
- 0.7  Clear directional signal supported by multiple data points; one or
       two minor caveats remain. Typical "good read" case.
- 0.5  Mixed signal. Real supporting evidence exists, but real
       counter-evidence is also present.
- 0.3  Data is thin, ambiguous, or contradictory. Findings should be hedged
       and few in number.
- ≤0.2 Data is effectively empty or unusable for this ticker × horizon.

Anchors:
- 0.5 is the default starting point. Move up only with cumulative supporting
  evidence; move down for every material gap or contradiction.
- Confidence reflects the strength of the analysis, not the attractiveness
  of the ticker. A confidently negative read is 0.9, not 0.1."""

GUARDS_BLOCK = """You analyze, you do not recommend. Do not use the verbs buy, sell, hold,
enter, exit, avoid, go long, go short, or any synonym thereof. Do not
suggest position size, stop levels, or entry prices. Do not predict future
price levels. Do not invent URLs, filings, or quotes. If the data is too
thin to support a finding, lower your confidence and emit fewer findings
rather than speculating. Saying "the data is insufficient" with
confidence 0.2 is correct behavior, not failure."""

WEIGHTING_HINTS: dict[Horizon, str] = {
    "intraday": (
        "Fundamentals are background. Only an earnings/guidance/filing event "
        "within the last 5 trading days is signal. Emit at most one or two bullets."
    ),
    "swing": (
        "Weight a fresh quarterly print and any guidance changes inside the 1–8 "
        "week window. Otherwise fundamentals are slow-moving context."
    ),
    "long_term": (
        "Fundamentals are the dominant lens. Multi-year revenue growth, margin "
        "trajectory, FCF stability, and leverage carry the read."
    ),
}

# §8.1 expected key_metrics keys — populated from the data bundle and merged
# with whatever the LLM emits (LLM values take precedence where overlapping).
EXPECTED_METRIC_KEYS: tuple[str, ...] = (
    "pe_ttm",
    "pb",
    "ps",
    "profit_margin",
    "revenue_growth_yoy",
    "debt_to_equity",
    "free_cash_flow_ttm",
    "sector",
    "industry",
    "market_cap",
    "latest_filing_date",
)


def _metrics_from_data(data: FundamentalsBundle) -> dict[str, Any]:
    return {
        "pe_ttm": data.pe_ttm,
        "pb": data.pb,
        "ps": data.ps,
        "profit_margin": data.profit_margin,
        "revenue_growth_yoy": data.revenue_growth_yoy,
        "debt_to_equity": data.debt_to_equity,
        "free_cash_flow_ttm": data.free_cash_flow_ttm,
        "sector": data.sector,
        "industry": data.industry,
        "market_cap": data.market_cap,
        "latest_filing_date": (
            data.latest_10q_filed_at.isoformat()
            if data.latest_10q_filed_at is not None
            else None
        ),
    }


def build_provenance(
    ticker: str, data: FundamentalsBundle, fetched_at: datetime
) -> list[dict[str, str]]:
    """Provenance index — the only URLs the LLM may cite."""
    iso = fetched_at.isoformat()
    items: list[dict[str, str]] = []
    if data.latest_10k_url:
        items.append(
            {
                "url": data.latest_10k_url,
                "title": f"{ticker} latest 10-K",
                "source": "SEC EDGAR",
                "fetched_at": iso,
            }
        )
    if data.latest_10q_url:
        filed = (
            data.latest_10q_filed_at.isoformat()
            if data.latest_10q_filed_at is not None
            else iso
        )
        items.append(
            {
                "url": data.latest_10q_url,
                "title": f"{ticker} latest 10-Q",
                "source": "SEC EDGAR",
                "fetched_at": filed,
            }
        )
    items.append(
        {
            "url": f"https://finance.yahoo.com/quote/{ticker}",
            "title": f"{ticker} quote summary",
            "source": "Yahoo Finance",
            "fetched_at": iso,
        }
    )
    return items


def build_cache_blocks(horizon: Horizon) -> list[str]:
    return [
        PERSONA_BLOCK,
        SCHEMA_BLOCK,
        HORIZON_BLOCKS[horizon],
        RUBRIC_BLOCK,
        GUARDS_BLOCK,
    ]


def build_user_block(
    ticker: str,
    data: FundamentalsBundle,
    horizon: Horizon,
    as_of: datetime,
    provenance: list[dict[str, str]],
) -> str:
    payload = data.model_dump(mode="json")
    return (
        f"Ticker: {ticker}\n"
        f"Horizon: {horizon}\n"
        f"As-of (UTC): {as_of.isoformat()}\n\n"
        "Analyst weighting hint:\n"
        f"{WEIGHTING_HINTS[horizon]}\n\n"
        "Provenance index (the only URLs you may cite):\n"
        f"{json.dumps(provenance, indent=2)}\n\n"
        "Data payload:\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Produce one JSON object matching the AnalystOutput schema. JSON only."
    )


def _is_empty(data: FundamentalsBundle) -> bool:
    """True when neither valuation/quality metrics nor filings are present."""
    metric_fields = (
        data.pe_ttm,
        data.pb,
        data.ps,
        data.profit_margin,
        data.revenue_growth_yoy,
        data.debt_to_equity,
        data.free_cash_flow_ttm,
        data.market_cap,
    )
    if any(v is not None for v in metric_fields):
        return False
    if data.latest_10k_url or data.latest_10q_url:
        return False
    return True


async def run(
    ticker: str,
    data: FundamentalsBundle,
    horizon: Horizon,
    llm: LLMProvider,
) -> AnalystOutput:
    """Run the fundamentals analyst for `ticker` over `horizon`."""
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")

    if _is_empty(data):
        # Open Q §10.6 default: emit a present-but-empty AnalystOutput so the
        # synthesizer always sees four keys. No LLM call.
        return AnalystOutput(
            findings=[],
            confidence=0.0,
            key_metrics=_metrics_from_data(data),
            citations=[],
        )

    as_of = datetime.now(UTC)
    provenance = build_provenance(ticker, data, as_of)
    user_block = build_user_block(ticker, data, horizon, as_of, provenance)
    cache_blocks = build_cache_blocks(horizon)

    messages: list[Message] = [{"role": "user", "content": user_block}]
    result = await llm.complete_structured(
        messages=messages,
        response_model=AnalystOutput,
        cache_blocks=cache_blocks,
        max_retries=1,
    )
    if not isinstance(result, AnalystOutput):
        # complete_structured returns BaseModel; the router guarantees the
        # validated response_model type, but coerce defensively.
        result = AnalystOutput.model_validate(result.model_dump())

    # §10.1 default: each analyst module asserts the §8 expected keys are
    # present after parsing. The data-derived values seed those keys; LLM
    # values win where they overlap so the analyst can refine (e.g., emit a
    # computed latest_filing_date or a categorical regime label).
    merged_metrics = _metrics_from_data(data)
    merged_metrics.update(result.key_metrics)
    return result.model_copy(update={"key_metrics": merged_metrics})


__all__ = [
    "ANALYST_ROLE",
    "EXPECTED_METRIC_KEYS",
    "GUARDS_BLOCK",
    "HORIZON_BLOCKS",
    "PERSONA_BLOCK",
    "RUBRIC_BLOCK",
    "SCHEMA_BLOCK",
    "WEIGHTING_HINTS",
    "build_cache_blocks",
    "build_provenance",
    "build_user_block",
    "run",
]

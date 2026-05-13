"""News analyst (M4c).

Turns a list of :class:`NewsItem` headlines into a single
:class:`AnalystOutput`. The analyst is one LLM call that follows the
prompt contract locked in ``docs/analyst-prompt-design.md`` — cached
system blocks (persona, schema reminder, horizon rules, citation +
confidence rubric, bias guards) plus a fresh user block containing the
ticker, horizon, provenance index, and serialized payload.

Per the design doc:

* Items are filtered to the horizon's news window: 7d / 30d / 90d for
  intraday / swing / long_term.
* The list is capped at :data:`_MAX_ITEMS` newest-first to keep the
  token budget bounded.
* The provenance index is built from each ``NewsItem.url``; only those
  URLs are allowed in the LLM's ``citations`` (hallucinated URLs are
  dropped post-validation).
* When the filtered list is empty, the LLM is skipped and a
  data-empty :class:`AnalystOutput` is returned (confidence 0.0,
  empty findings/citations).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.llm.provider import LLMProvider, Message
from app.pipeline.data.news import NewsItem
from app.pipeline.schema import AnalystOutput, Citation, Horizon

logger = logging.getLogger(__name__)

_HORIZON_WINDOW_DAYS: dict[Horizon, int] = {
    "intraday": 7,
    "swing": 30,
    "long_term": 90,
}

_MAX_ITEMS = 30

_PERSONA_BLOCK = (
    "You are a equity news and sentiment analyst for U.S.-listed equities. "
    "Your job is to analyze the data provided below for the ticker and horizon "
    "given, and emit one JSON object describing what the data shows. You do "
    "not advise on positions; you describe what is true in the data."
)

_SCHEMA_BLOCK = """\
Output strictly one JSON object with this exact shape and no other keys:

{
  "findings": [string, ...],            // 3-7 declarative observations
  "confidence": number,                 // 0.0-1.0, calibrated per the rubric
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
- `fetched_at` must be copied verbatim from the provenance index entry.
"""

_HORIZON_BLOCKS: dict[Horizon, str] = {
    "intraday": """\
Horizon: intraday (hours to ~2 trading days).

- Weight recency aggressively: data older than 5 trading days is context,
  not signal.
- News must be <= 48h old to count as a primary signal. Older items are
  background.
- Price action and short-window technicals dominate. Fundamentals are
  near-static background; only fundamentals events (earnings, guidance,
  filings) within the last 5 trading days carry weight.
- Macro is regime context only - note the regime, do not over-weight it.
- Findings should reference specific bars, sessions, or news within the
  last 1-5 trading days.
""",
    "swing": """\
Horizon: swing (~1-8 weeks).

- Weight the last 1-3 months of data.
- News within the last 30 days is primary signal; older news is context.
- Technicals at the daily-bar timeframe dominate (20- and 50-day SMAs,
  RSI(14) daily, MACD daily). Intraday noise is not the focus.
- Fundamentals matter when there is a fresh earnings/guidance/filing
  catalyst inside the swing window or expected within it.
- Macro regime sets the backdrop and is more material than at intraday.
""",
    "long_term": """\
Horizon: long_term (6+ months).

- Weight the trailing 12-24 months of data.
- Fundamentals dominate: profitability trends, revenue growth durability,
  balance-sheet quality, capital structure.
- News is thematic, not event-driven - look for persistent narratives,
  not single headlines.
- Technicals are weekly/monthly trend context, not setup-grade signal.
- Macro regime (rate path, recession signals, sector flows) is a
  first-class input.
""",
}

_RUBRIC_BLOCK = """\
Citation rules:

1. Every claim in `findings` that references a specific number, filing,
   news item, regulatory event, or quote must be backed by at least one
   citation in the `citations` list.
2. Every URL you cite MUST appear verbatim in the provenance index given
   in the user block. If you cannot find a provenance entry that supports
   a claim, either remove the claim or lower your confidence.
3. Use the `title`, `source`, and `fetched_at` fields exactly as they
   appear in the provenance index. Do not modify them.
4. A finding may cite multiple URLs (e.g., "Both filings show ..."). Repeat
   the URLs in `citations` - no deduplication is required.
5. General market-data observations cite the single data-source URL for
   that data slice (the chart URL for technicals, the FRED series URL for
   macro rates, etc.).
6. If the data slice is empty (no news items, no fundamentals available),
   emit zero or one explanatory finding, confidence <= 0.3, and an empty
   citations list. This is the only case where citations may be empty.

Confidence calibration:

- 0.9  Strong, consistent signal across the data. Multiple independent
       data points point the same direction. High-quality citations
       (primary filings, multiple reputable news sources, clear technical
       setup). No material counter-evidence in the data. Reserved - use
       sparingly.
- 0.7  Clear directional signal supported by multiple data points; one
       or two minor caveats or unknowns remain. Typical "good read" case.
- 0.5  Mixed signal. Real supporting evidence exists, but real
       counter-evidence is also present. The data does not resolve cleanly.
- 0.3  Data is thin, ambiguous, or contradictory. Only weak inferences
       are possible. Findings should be hedged and few in number.
- <=0.2 Data is effectively empty or unusable for this ticker x horizon.
       Findings should explicitly note this.

Calibration anchors:
- 0.5 is the default starting point. Move up only with cumulative
  supporting evidence; move down for every material gap or contradiction.
- Confidence reflects the strength of the *analysis*, not the
  attractiveness of the ticker. A confidently negative read is 0.9, not 0.1.

Sentiment scoring rubric (key_metrics.sentiment_score, -1.0 .. +1.0):

- +1.0  Overwhelmingly positive across the window. Multiple
        independent items report unambiguously bullish events (beats,
        guidance raises, large contract wins) and no material
        counter-narrative.
- +0.5  Net positive: positive items outnumber/outweigh negative ones,
        but real bearish items exist in the window.
- 0.0   Balanced or neutral. Mixed coverage with no directional bias, or
        the window is dominated by factual/non-evaluative news.
- -0.5  Net negative: negative items outnumber/outweigh positive ones,
        but real bullish items exist.
- -1.0  Overwhelmingly negative. Multiple independent items report
        unambiguously bearish events (misses, downgrades, regulatory
        actions, departures) and no material counter-narrative.

Weight items by recency within the window (more recent => more weight)
and by impact (regulatory/M&A/earnings outweigh analyst color). Round
to one decimal place.
"""

_GUARDS_BLOCK = (
    "You analyze, you do not recommend. Do not use the verbs buy, sell, hold, "
    "enter, exit, avoid, go long, go short, or any synonym thereof. Do not "
    "suggest position size, stop levels, or entry prices. Do not predict "
    "future price levels. Do not invent URLs, filings, or quotes. If the "
    "data is too thin to support a finding, lower your confidence and emit "
    "fewer findings rather than speculating. Saying \"the data is "
    "insufficient\" with confidence 0.2 is correct behavior, not failure."
)


class _NewsKeyMetrics(BaseModel):
    """Strict shape for ``key_metrics`` of the news analyst."""

    sentiment_score: float = Field(ge=-1.0, le=1.0)
    num_items: int = Field(ge=0)
    dominant_themes: list[str]


class _NewsAnalystResponse(BaseModel):
    """LLM-facing response model.

    Distinct from :class:`AnalystOutput` so we can pin ``key_metrics`` to
    the news-specific shape and let instructor validate it for free.
    """

    findings: list[str] = Field(min_length=1, max_length=7)
    confidence: float = Field(ge=0.0, le=1.0)
    key_metrics: _NewsKeyMetrics
    citations: list[Citation]


async def run(
    ticker: str,
    data: list[NewsItem],
    horizon: Horizon,
    llm: LLMProvider,
) -> AnalystOutput:
    """Run the news analyst for one ticker x horizon and return its output.

    The LLM is bypassed when the horizon-filtered list is empty so we
    don't burn a call to produce a data-empty result.
    """

    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")

    window_days = _HORIZON_WINDOW_DAYS[horizon]
    items = _filter_and_cap(data, window_days)

    if not items:
        return AnalystOutput(
            findings=[
                f"No news items for {ticker} within the last {window_days} days."
            ],
            confidence=0.0,
            key_metrics={
                "sentiment_score": 0.0,
                "num_items": 0,
                "dominant_themes": [],
            },
            citations=[],
        )

    as_of = datetime.now(UTC)
    provenance = _build_provenance(items, fetched_at=as_of)
    user_block = _render_user_block(
        ticker=ticker,
        horizon=horizon,
        as_of=as_of,
        items=items,
        provenance=provenance,
    )

    messages: list[Message] = [{"role": "user", "content": user_block}]
    cache_blocks = [
        _PERSONA_BLOCK,
        _SCHEMA_BLOCK,
        _HORIZON_BLOCKS[horizon],
        _RUBRIC_BLOCK,
        _GUARDS_BLOCK,
    ]

    raw = await llm.complete_structured(
        messages,
        _NewsAnalystResponse,
        cache_blocks=cache_blocks,
        max_retries=1,
    )
    assert isinstance(raw, _NewsAnalystResponse)

    allowed_urls = {p["url"] for p in provenance}
    citations = [c for c in raw.citations if c.url in allowed_urls]
    dropped = len(raw.citations) - len(citations)
    if dropped:
        logger.warning(
            "news analyst for %s dropped %d hallucinated citation(s)", ticker, dropped
        )

    return AnalystOutput(
        findings=raw.findings,
        confidence=raw.confidence,
        key_metrics={
            "sentiment_score": raw.key_metrics.sentiment_score,
            "num_items": raw.key_metrics.num_items,
            "dominant_themes": raw.key_metrics.dominant_themes,
        },
        citations=citations,
    )


def _filter_and_cap(items: list[NewsItem], window_days: int) -> list[NewsItem]:
    """Keep items within the horizon window, newest-first, capped at the limit."""
    cutoff = datetime.now(UTC).timestamp() - window_days * 86400
    in_window = [it for it in items if it.published_at.timestamp() >= cutoff]
    in_window.sort(key=lambda it: it.published_at, reverse=True)
    return in_window[:_MAX_ITEMS]


def _build_provenance(
    items: list[NewsItem], *, fetched_at: datetime
) -> list[dict[str, str]]:
    """Provenance index — the only URLs the LLM is allowed to cite.

    Dedups by URL so that aggregators republishing the same article
    don't blow up the index. ``fetched_at`` is stamped once for the
    analyst call (the news fetcher's cache record isn't surfaced to us;
    a single now-stamp is the contract we can keep).
    """
    seen: set[str] = set()
    provenance: list[dict[str, str]] = []
    fetched_iso = fetched_at.isoformat()
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        provenance.append(
            {
                "url": item.url,
                "title": item.title,
                "source": item.source,
                "fetched_at": fetched_iso,
            }
        )
    return provenance


def _render_user_block(
    *,
    ticker: str,
    horizon: Horizon,
    as_of: datetime,
    items: list[NewsItem],
    provenance: list[dict[str, str]],
) -> str:
    weighting_hint = _WEIGHTING_HINTS[horizon]
    data_payload: list[dict[str, Any]] = []
    for item in items:
        entry: dict[str, Any] = {
            "url": item.url,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at.isoformat(),
        }
        if item.summary:
            entry["summary"] = item.summary
        if item.sentiment_hint is not None:
            entry["sentiment_hint"] = item.sentiment_hint
        data_payload.append(entry)

    return (
        f"Ticker: {ticker}\n"
        f"Horizon: {horizon}\n"
        f"As-of (UTC): {as_of.isoformat()}\n\n"
        f"Analyst weighting hint:\n{weighting_hint}\n\n"
        "Cluster the news items below into themes in one pass, then describe "
        "dominant narratives, sentiment direction, recency-weighted importance, "
        "and any upcoming catalysts mentioned. Compute the sentiment score and "
        "dominant themes for key_metrics.\n\n"
        "Provenance index (the only URLs you may cite):\n"
        f"{json.dumps(provenance, indent=2)}\n\n"
        "Data payload:\n"
        f"{json.dumps(data_payload, indent=2)}\n\n"
        "Produce one JSON object matching the AnalystOutput schema. JSON only."
    )


_WEIGHTING_HINTS: dict[Horizon, str] = {
    "intraday": (
        "Only items <= 48h old are primary signal. Older items are background. "
        "Note any single high-impact item (regulatory, M&A, earnings)."
    ),
    "swing": (
        "Items within the last 30 days are primary. Look for dominant themes "
        "and recurring stories, not just single headlines."
    ),
    "long_term": (
        "Look for persistent multi-month narratives. Treat single events as "
        "noise unless they materially alter the long-term thesis (e.g., "
        "management change, segment divestiture)."
    ),
}


__all__ = ["run"]

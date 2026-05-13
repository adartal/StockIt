"""Macro analyst: one LLM call mapping a `MacroBundle` to an `AnalystOutput`.

Follows the M4 analyst prompt design ([docs/analyst-prompt-design.md]). The
prompt is assembled from five cached system blocks (persona, schema, horizon
rules, citation+confidence rubric, bias guards) plus an uncached user block
that carries the ticker, horizon, weighting hints, provenance index, and
serialized `MacroBundle`.

The deterministic regime classifications (`rates_regime`, `vix_regime`,
`sector_relative_perf_30d`) are computed here and *injected* into the parsed
output's `key_metrics`, overwriting any value the model emitted for those
keys. The synthesizer relies on these being stable categorical strings, not
LLM prose.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.llm.provider import LLMProvider, Message
from app.pipeline.data.macro import MacroBundle
from app.pipeline.schema import AnalystOutput, Citation, Horizon

ANALYST_ROLE = "macro and regime analyst"

PERSONA_BLOCK = f"""You are a {ANALYST_ROLE} for U.S.-listed equities. Your job is to analyze
the data provided below for the ticker and horizon given, and emit one
JSON object describing what the data shows. You do not advise on positions;
you describe what is true in the data."""

SCHEMA_BLOCK = """Output strictly one JSON object with this exact shape and no other keys:

{
  "findings": [string, ...],            // declarative observations
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

- Weight recency aggressively: data older than 5 trading days is context,
  not signal.
- Macro is regime context only — note the regime and stop.
- Emit exactly ONE finding summarizing the macro regime (rate level, VIX
  bucket, sector vs SPY). Do not expand. Keep confidence modest.""",
    "swing": """Horizon: swing (~1–8 weeks).

- Weight the last 1–3 months of data.
- Macro regime is meaningful backdrop. Sector ETF performance vs SPY over
  the last 30 days is the key cross-section.
- Emit 3–5 findings covering rate environment, sector momentum vs market,
  VIX regime, and relative strength.""",
    "long_term": """Horizon: long_term (6+ months).

- Weight the trailing 12–24 months of data (only the most recent month is
  in the payload — note that limitation).
- Macro is a first-class input. Rate-path direction, curve shape, and
  multi-month sector flows carry weight equal to or exceeding
  ticker-specific factors.
- Emit 4–7 findings covering rate environment impact on the sector,
  sector momentum vs market, VIX regime, and relative strength.""",
}

RUBRIC_BLOCK = """Citation rules:

1. Every claim in `findings` that references a specific number must be
   backed by at least one citation in the `citations` list.
2. Every URL you cite MUST appear verbatim in the provenance index given
   in the user block. If you cannot find a provenance entry that supports
   a claim, either remove the claim or lower your confidence.
3. Use the `title`, `source`, and `fetched_at` fields exactly as they
   appear in the provenance index. Do not modify them.
4. A finding may cite multiple URLs. Repeat the URLs in `citations` — no
   deduplication is required.
5. General market-data observations cite the single data-source URL for
   that data slice (FRED series URL for treasury rates, VIX quote URL,
   SPY quote URL, sector ETF quote URL).

Confidence calibration:

- 0.9  Strong, consistent signal across the data. Reserved.
- 0.7  Clear directional signal supported by multiple data points; minor
       caveats remain. Typical "good read" case.
- 0.5  Mixed signal. Real supporting and counter-evidence both present.
- 0.3  Data is thin, ambiguous, or contradictory.
- ≤0.2 Data is effectively empty or unusable.

Calibration anchors:
- 0.5 is the default starting point. Move up only with cumulative
  supporting evidence; move down for every material gap or contradiction.
- Confidence reflects the strength of the *analysis*, not the
  attractiveness of the ticker. A confidently negative read is 0.9, not 0.1."""

BIAS_GUARDS_BLOCK = """You analyze, you do not recommend. Do not use the verbs buy, sell, hold,
enter, exit, avoid, go long, go short, or any synonym thereof. Do not
suggest position size, stop levels, or entry prices. Do not predict future
price levels. Do not invent URLs, filings, or quotes. If the data is too
thin to support a finding, lower your confidence and emit fewer findings
rather than speculating."""


_WEIGHTING_HINTS: dict[Horizon, str] = {
    "intraday": (
        "Regime context only. Note the regime (rate level, VIX bucket, sector "
        "vs SPY) in ONE bullet and stop."
    ),
    "swing": (
        "Regime is meaningful backdrop. Sector ETF performance vs SPY over the "
        "last 30 days is the key cross-section."
    ),
    "long_term": (
        "First-class input. Rate-path direction, curve shape, and multi-month "
        "sector flows carry weight equal to or exceeding ticker-specific "
        "factors."
    ),
}


def _classify_rates_regime(dgs2_delta_30d: float) -> str:
    """Easing / tightening / flat based on the 30-day move in DGS2."""
    if dgs2_delta_30d <= -0.10:
        return "easing"
    if dgs2_delta_30d >= 0.10:
        return "tightening"
    return "flat"


def _classify_vix_regime(vix: float) -> str:
    """Low (<15), normal (15–25), high (>25)."""
    if vix < 15.0:
        return "low"
    if vix < 25.0:
        return "normal"
    return "high"


def _build_provenance(data: MacroBundle, fetched_at: datetime) -> list[dict[str, str]]:
    stamp = fetched_at.isoformat()
    return [
        {
            "url": "https://fred.stlouisfed.org/series/DGS2",
            "title": "2-Year Treasury Constant Maturity Rate",
            "source": "FRED",
            "fetched_at": stamp,
        },
        {
            "url": "https://fred.stlouisfed.org/series/DGS10",
            "title": "10-Year Treasury Constant Maturity Rate",
            "source": "FRED",
            "fetched_at": stamp,
        },
        {
            "url": "https://finance.yahoo.com/quote/%5EVIX",
            "title": "CBOE Volatility Index (^VIX)",
            "source": "Yahoo Finance",
            "fetched_at": stamp,
        },
        {
            "url": "https://finance.yahoo.com/quote/SPY",
            "title": "SPDR S&P 500 ETF (SPY)",
            "source": "Yahoo Finance",
            "fetched_at": stamp,
        },
        {
            "url": f"https://finance.yahoo.com/quote/{data.sector_etf_ticker}",
            "title": f"Sector ETF ({data.sector_etf_ticker})",
            "source": "Yahoo Finance",
            "fetched_at": stamp,
        },
    ]


def _user_block(
    ticker: str,
    horizon: Horizon,
    data: MacroBundle,
    provenance: list[dict[str, str]],
    as_of: datetime,
) -> str:
    payload = data.model_dump(mode="json")
    return (
        f"Ticker: {ticker}\n"
        f"Horizon: {horizon}\n"
        f"As-of (UTC): {as_of.isoformat()}\n\n"
        f"Analyst weighting hint:\n{_WEIGHTING_HINTS[horizon]}\n\n"
        f"Provenance index (the only URLs you may cite):\n"
        f"{json.dumps(provenance, indent=2)}\n\n"
        f"Data payload:\n{json.dumps(payload, indent=2)}\n\n"
        "Produce one JSON object matching the AnalystOutput schema. JSON only."
    )


async def run(
    ticker: str,
    data: MacroBundle,
    horizon: Horizon,
    llm: LLMProvider,
) -> AnalystOutput:
    """Run the macro analyst once and return its `AnalystOutput`.

    Deterministic regime classifications (`rates_regime`, `vix_regime`,
    `sector_relative_perf_30d`) are computed here and overwrite whatever the
    model produced for those keys, so downstream synthesis can rely on
    stable categorical values.
    """
    as_of = datetime.now(UTC)
    provenance = _build_provenance(data, as_of)

    cache_blocks = [
        PERSONA_BLOCK,
        SCHEMA_BLOCK,
        HORIZON_BLOCKS[horizon],
        RUBRIC_BLOCK,
        BIAS_GUARDS_BLOCK,
    ]
    user_block = _user_block(ticker, horizon, data, provenance, as_of)
    messages: list[Message] = [{"role": "user", "content": user_block}]

    raw = await llm.complete_structured(
        messages=messages,
        response_model=AnalystOutput,
        cache_blocks=cache_blocks,
        max_retries=1,
    )
    assert isinstance(raw, AnalystOutput)

    sector_rel = data.sector_etf_perf_30d - data.spy_perf_30d
    rates_regime = _classify_rates_regime(data.rates["DGS2"].delta_30d)
    vix_regime = _classify_vix_regime(data.vix)

    merged_metrics: dict[str, object] = dict(raw.key_metrics)
    merged_metrics["sector_relative_perf_30d"] = sector_rel
    merged_metrics["rates_regime"] = rates_regime
    merged_metrics["vix_regime"] = vix_regime

    return AnalystOutput(
        findings=raw.findings,
        confidence=raw.confidence,
        key_metrics=merged_metrics,
        citations=[Citation.model_validate(c.model_dump()) for c in raw.citations],
    )


__all__ = ["run"]

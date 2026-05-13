"""Technicals analyst (M4b).

Computes a fixed indicator set from OHLCV bars in Python — RSI(14),
MACD(12/26/9), ATR(14), SMA(20/50/200), swing-based support/resistance,
volume z-score, distance from 52-week high — and passes the resulting
summary (NOT the raw OHLCV) to the LLM under the shared analyst prompt
template described in docs/analyst-prompt-design.md.

Why indicators are computed in Python rather than left to the LLM:
math accuracy + token budget. The model receives the last 60 bars in
compact form plus the indicator series ends, which keeps the user-block
payload small and bounded regardless of how many bars the caller fetched.

Note on `pandas-ta`: the M4b briefing called for pandas-ta, but the
project pins pandas>=3.0.3 which is incompatible with pandas-ta's
transitive pin to numpy<2.3 (via numba). The indicator math here is the
standard textbook formulation (Wilder's smoothing for RSI/ATR, EMA for
MACD) implemented directly in pandas — no extra dependency.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.llm.provider import LLMProvider, Message
from app.pipeline.schema import AnalystOutput, Citation, Horizon

_TRADING_DAYS_PER_YEAR = 252
_BARS_FOR_LLM = 60


async def run(
    ticker: str,
    data: pd.DataFrame,
    horizon: Horizon,
    llm: LLMProvider,
) -> AnalystOutput:
    """Run the technicals analyst for `ticker` over `data` (OHLCV bars).

    `data` is the DataFrame returned by `app.pipeline.data.prices.fetch_ohlcv`:
    UTC-indexed, columns ``open, high, low, close, volume``.

    Returns an `AnalystOutput` with the §8.2 key_metrics fields populated
    deterministically from the indicators (so the synthesizer in M5b can
    rely on their presence even if the LLM call retries on the JSON
    schema). Empty data → an empty, low-confidence `AnalystOutput` per
    docs/analyst-prompt-design.md §10 open Q 6.
    """
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("ticker must be non-empty")

    fetched_at = datetime.now(UTC)

    if data.empty or len(data) < 2:
        return AnalystOutput(
            findings=["Price data is empty or insufficient for technical analysis."],
            confidence=0.1,
            key_metrics=_empty_metrics(_infer_interval(data)),
            citations=[],
        )

    indicators = _compute_indicators(data)
    interval = _infer_interval(data)
    key_metrics = _build_key_metrics(indicators, interval, len(data))

    chart_url = f"https://finance.yahoo.com/chart/{ticker}"
    provenance = [
        {
            "url": chart_url,
            "title": f"{ticker} price chart",
            "source": "Yahoo Finance",
            "fetched_at": fetched_at.isoformat(),
        }
    ]

    user_block = _build_user_block(
        ticker=ticker,
        horizon=horizon,
        as_of=fetched_at,
        interval=interval,
        provenance=provenance,
        data=data,
        indicators=indicators,
    )

    cache_blocks = [
        _BLOCK_PERSONA,
        _BLOCK_SCHEMA,
        _HORIZON_BLOCKS[horizon],
        _BLOCK_RUBRIC,
        _BLOCK_GUARDS,
    ]

    messages: list[Message] = [{"role": "user", "content": user_block}]
    raw = await llm.complete_structured(
        messages=messages,
        response_model=AnalystOutput,
        cache_blocks=cache_blocks,
        max_retries=1,
    )
    if not isinstance(raw, AnalystOutput):  # pragma: no cover — providers return the model
        raise TypeError(f"expected AnalystOutput, got {type(raw).__name__}")

    merged_metrics = {**raw.key_metrics, **key_metrics}
    citations = raw.citations or [
        Citation(
            url=chart_url,
            title=f"{ticker} price chart",
            source="Yahoo Finance",
            fetched_at=fetched_at,
        )
    ]
    return AnalystOutput(
        findings=raw.findings,
        confidence=raw.confidence,
        key_metrics=merged_metrics,
        citations=citations,
    )


def _compute_indicators(data: pd.DataFrame) -> dict[str, Any]:
    """Standard textbook indicators on a UTC-indexed OHLCV frame."""
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = data["volume"].astype(float)

    sma_20 = close.rolling(window=20, min_periods=1).mean()
    sma_50 = close.rolling(window=50, min_periods=1).mean()
    sma_200 = close.rolling(window=200, min_periods=1).mean()

    rsi_14 = _rsi(close, period=14)
    macd_line, macd_signal, macd_hist = _macd(close)
    atr_14 = _atr(high, low, close, period=14)

    volume_mean = volume.rolling(window=30, min_periods=1).mean()
    volume_std = volume.rolling(window=30, min_periods=2).std()
    volume_z = (volume - volume_mean) / volume_std.replace(0.0, pd.NA)

    high_52w = high.tail(_TRADING_DAYS_PER_YEAR).max()
    low_52w = low.tail(_TRADING_DAYS_PER_YEAR).min()
    last_close = float(close.iloc[-1])
    distance_from_52w_high_pct = (
        float((last_close - high_52w) / high_52w * 100.0) if high_52w else float("nan")
    )
    distance_from_52w_low_pct = (
        float((last_close - low_52w) / low_52w * 100.0) if low_52w else float("nan")
    )

    support, resistance = _swing_levels(high, low, window=5)

    return {
        "close": close,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "rsi_14": rsi_14,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "atr_14": atr_14,
        "volume": volume,
        "volume_z": volume_z,
        "high_52w": float(high_52w) if high_52w else None,
        "low_52w": float(low_52w) if low_52w else None,
        "distance_from_52w_high_pct": distance_from_52w_high_pct,
        "distance_from_52w_low_pct": distance_from_52w_low_pct,
        "support": support,
        "resistance": resistance,
    }


def _rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI. Zero-loss windows pin to 100, zero-gain windows to 0."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(~((avg_loss == 0.0) & (avg_gain > 0.0)), 100.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss > 0.0)), 0.0)
    rsi = rsi.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    return rsi


def _macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def _swing_levels(
    high: pd.Series,
    low: pd.Series,
    window: int = 5,
) -> tuple[list[float], list[float]]:
    """Pick swing-low (support) and swing-high (resistance) levels.

    A bar at position i is a swing high if its high is the strict max of
    the [i-window, i+window] window; symmetric for swing lows. We return
    the last three of each (most recent first) to keep the payload small.
    """
    supports: list[float] = []
    resistances: list[float] = []
    n = len(high)
    if n < 2 * window + 1:
        return supports, resistances
    hi_arr = high.to_numpy()
    lo_arr = low.to_numpy()
    for i in range(window, n - window):
        seg_hi = hi_arr[i - window : i + window + 1]
        seg_lo = lo_arr[i - window : i + window + 1]
        if hi_arr[i] == seg_hi.max() and (seg_hi == hi_arr[i]).sum() == 1:
            resistances.append(float(hi_arr[i]))
        if lo_arr[i] == seg_lo.min() and (seg_lo == lo_arr[i]).sum() == 1:
            supports.append(float(lo_arr[i]))
    return supports[-3:][::-1], resistances[-3:][::-1]


def _infer_interval(data: pd.DataFrame) -> str:
    """Best-effort interval string from the bar spacing. Defaults to '1d'."""
    if len(data) < 2:
        return "1d"
    diffs = data.index.to_series().diff().dropna()
    if diffs.empty:
        return "1d"
    median_delta = diffs.median()
    if not isinstance(median_delta, pd.Timedelta):
        return "1d"
    median_seconds = float(median_delta.total_seconds())
    if median_seconds <= 90:
        return "1m"
    if median_seconds <= 360:
        return "5m"
    if median_seconds <= 4000:
        return "1h"
    if median_seconds <= 90000:
        return "1d"
    return "1wk"


def _build_key_metrics(
    indicators: dict[str, Any], interval: str, lookback_bars: int
) -> dict[str, Any]:
    close = indicators["close"]
    last = -1
    return {
        "close": _f(close.iloc[last]),
        "sma_20": _f(indicators["sma_20"].iloc[last]),
        "sma_50": _f(indicators["sma_50"].iloc[last]),
        "sma_200": _f(indicators["sma_200"].iloc[last]),
        "rsi_14": _f(indicators["rsi_14"].iloc[last]),
        "macd": _f(indicators["macd"].iloc[last]),
        "macd_signal": _f(indicators["macd_signal"].iloc[last]),
        "macd_hist": _f(indicators["macd_hist"].iloc[last]),
        "atr_14": _f(indicators["atr_14"].iloc[last]),
        "volume_z": _f(indicators["volume_z"].iloc[last]),
        "high_52w": indicators["high_52w"],
        "low_52w": indicators["low_52w"],
        "distance_from_52w_high_pct": _f(indicators["distance_from_52w_high_pct"]),
        "distance_from_52w_low_pct": _f(indicators["distance_from_52w_low_pct"]),
        "support": indicators["support"],
        "resistance": indicators["resistance"],
        "interval": interval,
        "lookback_bars": lookback_bars,
    }


def _empty_metrics(interval: str) -> dict[str, Any]:
    return {
        "close": None,
        "sma_20": None,
        "sma_50": None,
        "sma_200": None,
        "rsi_14": None,
        "macd": None,
        "macd_signal": None,
        "macd_hist": None,
        "atr_14": None,
        "volume_z": None,
        "high_52w": None,
        "low_52w": None,
        "distance_from_52w_high_pct": None,
        "distance_from_52w_low_pct": None,
        "support": [],
        "resistance": [],
        "interval": interval,
        "lookback_bars": 0,
    }


def _f(value: Any) -> float | None:
    """Convert a pandas/NumPy scalar to a plain float, or None if NaN/missing."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _build_user_block(
    *,
    ticker: str,
    horizon: Horizon,
    as_of: datetime,
    interval: str,
    provenance: list[dict[str, str]],
    data: pd.DataFrame,
    indicators: dict[str, Any],
) -> str:
    bars_tail = data.tail(_BARS_FOR_LLM)
    bars_summary = [
        {
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "o": _f(row.open),
            "h": _f(row.high),
            "l": _f(row.low),
            "c": _f(row.close),
            "v": _f(row.volume),
        }
        for ts, row in zip(bars_tail.index, bars_tail.itertuples(index=False), strict=False)
    ]
    # Last few indicator values, not the full series, keep token budget tight.
    indicator_tail = {
        name: [_f(v) for v in indicators[name].tail(10).tolist()]
        for name in ("sma_20", "sma_50", "sma_200", "rsi_14", "macd", "macd_signal", "atr_14")
    }

    payload = {
        "interval": interval,
        "bars": bars_summary,
        "indicators_tail": indicator_tail,
        "snapshot": {
            "close": _f(indicators["close"].iloc[-1]),
            "sma_20": _f(indicators["sma_20"].iloc[-1]),
            "sma_50": _f(indicators["sma_50"].iloc[-1]),
            "sma_200": _f(indicators["sma_200"].iloc[-1]),
            "rsi_14": _f(indicators["rsi_14"].iloc[-1]),
            "macd": _f(indicators["macd"].iloc[-1]),
            "macd_signal": _f(indicators["macd_signal"].iloc[-1]),
            "atr_14": _f(indicators["atr_14"].iloc[-1]),
            "volume_z": _f(indicators["volume_z"].iloc[-1]),
            "high_52w": indicators["high_52w"],
            "low_52w": indicators["low_52w"],
            "distance_from_52w_high_pct": _f(indicators["distance_from_52w_high_pct"]),
            "distance_from_52w_low_pct": _f(indicators["distance_from_52w_low_pct"]),
            "support": indicators["support"],
            "resistance": indicators["resistance"],
        },
    }

    return (
        f"Ticker: {ticker}\n"
        f"Horizon: {horizon}\n"
        f"As-of (UTC): {as_of.isoformat()}\n\n"
        "Analyst weighting hint:\n"
        f"{_WEIGHTING_HINTS[horizon]}\n\n"
        "Provenance index (the only URLs you may cite):\n"
        f"{json.dumps(provenance, indent=2)}\n\n"
        "Data payload:\n"
        f"{json.dumps(payload, default=str)}\n\n"
        "Produce one JSON object matching the AnalystOutput schema. JSON only."
    )


# ---------------------------------------------------------------------------
# Prompt blocks — verbatim from docs/analyst-prompt-design.md §4.1, §5, §6, §7.
# These are cached as the system prefix; only the persona varies vs the other
# three analysts so the shared blocks reuse Anthropic's prompt cache hits.
# ---------------------------------------------------------------------------

_BLOCK_PERSONA = (
    "You are an equity price-action and chart analyst for U.S.-listed equities. "
    "Your job is to analyze the data provided below for the ticker and horizon "
    "given, and emit one JSON object describing what the data shows. You do not "
    "advise on positions; you describe what is true in the data."
)

_BLOCK_SCHEMA = """Output strictly one JSON object with this exact shape and no other keys:

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

_HORIZON_BLOCKS: dict[Horizon, str] = {
    "intraday": """Horizon: intraday (hours to ~2 trading days).

- Weight recency aggressively: data older than 5 trading days is context, not signal.
- News must be ≤ 48h old to count as a primary signal. Older items are background.
- Price action and short-window technicals dominate. Fundamentals are
  near-static background; only fundamentals events (earnings, guidance,
  filings) within the last 5 trading days carry weight.
- Macro is regime context only — note the regime, do not over-weight it.
- Findings should reference specific bars, sessions, or news within the
  last 1–5 trading days.""",
    "swing": """Horizon: swing (~1–8 weeks).

- Weight the last 1–3 months of data.
- News within the last 30 days is primary signal; older news is context.
- Technicals at the daily-bar timeframe dominate (20- and 50-day SMAs,
  RSI(14) daily, MACD daily). Intraday noise is not the focus.
- Fundamentals matter when there is a fresh earnings/guidance/filing
  catalyst inside the swing window or expected within it.
- Macro regime sets the backdrop and is more material than at intraday.""",
    "long_term": """Horizon: long_term (6+ months).

- Weight the trailing 12–24 months of data.
- Fundamentals dominate: profitability trends, revenue growth durability,
  balance-sheet quality, capital structure.
- News is thematic, not event-driven — look for persistent narratives,
  not single headlines.
- Technicals are weekly/monthly trend context, not setup-grade signal.
- Macro regime (rate path, recession signals, sector flows) is a
  first-class input.""",
}

_BLOCK_RUBRIC = """Citation rules:

1. Every claim in `findings` that references a specific number, filing,
   news item, regulatory event, or quote must be backed by at least one
   citation in the `citations` list.
2. Every URL you cite MUST appear verbatim in the provenance index given
   in the user block. If you cannot find a provenance entry that supports
   a claim, either remove the claim or lower your confidence.
3. Use the `title`, `source`, and `fetched_at` fields exactly as they
   appear in the provenance index. Do not modify them.
4. A finding may cite multiple URLs (e.g., "Both the Q3 10-Q and the
   sector ETF return show ..."). Repeat the URLs in `citations` — no
   deduplication is required.
5. General market-data observations (e.g., "RSI(14) is 72") cite the
   single data-source URL for that data slice (the chart URL for
   technicals, the FRED series URL for macro rates, etc.).
6. If the data slice is empty (no news items, no fundamentals available),
   emit zero or one explanatory finding, confidence ≤ 0.3, and an empty
   citations list. This is the only case where citations may be empty.

Confidence calibration:

- 0.9  Strong, consistent signal across the data. Multiple independent
       data points point the same direction. High-quality citations
       (primary filings, multiple reputable news sources, clear technical
       setup). No material counter-evidence in the data. Reserved — use
       sparingly.
- 0.7  Clear directional signal supported by multiple data points; one
       or two minor caveats or unknowns remain. Typical "good read" case.
- 0.5  Mixed signal. Real supporting evidence exists, but real
       counter-evidence is also present. The data does not resolve cleanly.
- 0.3  Data is thin, ambiguous, or contradictory. Only weak inferences
       are possible. Findings should be hedged and few in number.
- ≤0.2 Data is effectively empty or unusable for this ticker × horizon.
       Findings should explicitly note this.

Calibration anchors:
- 0.5 is the default starting point. Move up only with cumulative
  supporting evidence; move down for every material gap or contradiction.
- Confidence reflects the strength of the *analysis*, not the
  attractiveness of the ticker. A confidently negative read is 0.9, not 0.1."""

_BLOCK_GUARDS = (
    "You analyze, you do not recommend. Do not use the verbs buy, sell, hold, "
    "enter, exit, avoid, go long, go short, or any synonym thereof. Do not "
    "suggest position size, stop levels, or entry prices. Do not predict future "
    "price levels. Do not invent URLs, filings, or quotes. If the data is too "
    "thin to support a finding, lower your confidence and emit fewer findings "
    "rather than speculating. Saying \"the data is insufficient\" with "
    "confidence 0.2 is correct behavior, not failure."
)

_WEIGHTING_HINTS: dict[Horizon, str] = {
    "intraday": (
        "1m–1h bars dominate. Focus on the last 1–5 sessions: VWAP relationship, "
        "intraday RSI, volume spikes, session highs/lows."
    ),
    "swing": (
        "Daily bars dominate. Focus on the 20/50-day SMA relationship, RSI(14) "
        "daily, MACD crossovers within the last 1–3 months."
    ),
    "long_term": (
        "Weekly/monthly trend only. Note the long-term moving-average regime, "
        "multi-year support/resistance — not setup-grade signals."
    ),
}


__all__ = ["run"]

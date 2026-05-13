"""Tests for the M4b technicals analyst.

The LLM call is replaced with a `FakeLLMProvider` that captures the
arguments it receives and returns a canned `AnalystOutput`. Indicator
math is exercised through the analyst's run() with a synthetic OHLCV
frame whose closing series has known properties (strict uptrend → RSI
> 70, MACD > 0, price above all SMAs).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from pydantic import BaseModel

from app.llm.provider import LLMProvider, Message
from app.pipeline.analysts.technicals import run
from app.pipeline.schema import AnalystOutput, Citation, Horizon


class FakeLLMProvider:
    """LLMProvider double. Returns the canned `response` and records the
    last call's messages/cache_blocks so tests can assert on prompt shape."""

    name = "fake"

    def __init__(self, response: AnalystOutput) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def complete_structured(
        self,
        messages: list[Message],
        response_model: type[BaseModel],
        *,
        cache_blocks: list[str] | None = None,
        max_retries: int = 1,
    ) -> BaseModel:
        self.calls.append(
            {
                "messages": messages,
                "response_model": response_model,
                "cache_blocks": list(cache_blocks or []),
                "max_retries": max_retries,
            }
        )
        return self.response


def _uptrend_frame(bars: int = 260) -> pd.DataFrame:
    """OHLCV frame with strictly increasing closes — gives RSI≈100, MACD>0."""
    end = datetime(2026, 5, 13, tzinfo=UTC)
    idx = pd.DatetimeIndex(
        [end - timedelta(days=bars - 1 - i) for i in range(bars)], name="timestamp", tz="UTC"
    )
    closes = [100.0 + i * 0.5 for i in range(bars)]
    highs = [c + 0.4 for c in closes]
    lows = [c - 0.4 for c in closes]
    opens = [c - 0.1 for c in closes]
    volumes = [1_000_000.0 + (i % 7) * 5_000.0 for i in range(bars)]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=idx,
    )


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float)
    df.index = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return df


def _canned_output() -> AnalystOutput:
    return AnalystOutput(
        findings=[
            "Close above the 20-, 50-, and 200-day SMAs with positive MACD.",
            "RSI(14) is in the overbought zone.",
        ],
        confidence=0.7,
        key_metrics={"trend": "up"},
        citations=[
            Citation(
                url="https://finance.yahoo.com/chart/AAPL",
                title="AAPL price chart",
                source="Yahoo Finance",
                fetched_at=datetime(2026, 5, 13, tzinfo=UTC),
            )
        ],
    )


@pytest.mark.parametrize("horizon", ["intraday", "swing", "long_term"])
async def test_run_returns_analyst_output_with_required_key_metrics(horizon: Horizon) -> None:
    df = _uptrend_frame()
    llm = FakeLLMProvider(_canned_output())

    out = await run("aapl", df, horizon, llm)

    assert isinstance(out, AnalystOutput)
    # Required §8.2 / briefing keys must be present and populated.
    for key in (
        "rsi_14",
        "atr_14",
        "sma_50",
        "sma_200",
        "distance_from_52w_high_pct",
        "close",
        "sma_20",
        "macd",
        "macd_signal",
        "volume_z",
        "interval",
        "lookback_bars",
    ):
        assert key in out.key_metrics, f"missing {key}"
    assert out.key_metrics["sma_50"] is not None
    assert out.key_metrics["sma_200"] is not None
    assert out.key_metrics["rsi_14"] is not None
    assert out.key_metrics["atr_14"] is not None
    assert out.key_metrics["lookback_bars"] == len(df)


async def test_run_protocol_compliance() -> None:
    llm = FakeLLMProvider(_canned_output())
    assert isinstance(llm, LLMProvider)


async def test_uptrend_produces_high_rsi_and_positive_macd() -> None:
    df = _uptrend_frame()
    llm = FakeLLMProvider(_canned_output())

    out = await run("AAPL", df, "swing", llm)

    rsi = out.key_metrics["rsi_14"]
    macd = out.key_metrics["macd"]
    sma_50 = out.key_metrics["sma_50"]
    close = out.key_metrics["close"]
    assert rsi is not None and rsi > 70.0, f"expected RSI>70 in strict uptrend, got {rsi}"
    assert macd is not None and macd > 0.0, f"expected MACD>0 in uptrend, got {macd}"
    assert close > sma_50, "close should sit above the 50-day SMA in a strict uptrend"


async def test_empty_data_returns_low_confidence_no_citations() -> None:
    llm = FakeLLMProvider(_canned_output())

    out = await run("AAPL", _empty_frame(), "swing", llm)

    assert out.confidence <= 0.3
    assert out.citations == []
    assert out.key_metrics["close"] is None
    # The LLM must not be called when data is empty.
    assert llm.calls == []


async def test_prompt_structure_persona_schema_horizon_rubric_guards() -> None:
    df = _uptrend_frame()
    llm = FakeLLMProvider(_canned_output())

    await run("AAPL", df, "swing", llm)

    assert len(llm.calls) == 1
    call = llm.calls[0]
    blocks = call["cache_blocks"]
    # Exactly the five blocks specified in the design doc, in order.
    assert len(blocks) == 5
    assert "price-action and chart analyst" in blocks[0]
    assert "Output strictly one JSON object" in blocks[1]
    assert "Horizon: swing" in blocks[2]
    assert "Citation rules" in blocks[3] and "Confidence calibration" in blocks[3]
    assert "do not recommend" in blocks[4]

    messages = call["messages"]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    user_content = messages[0]["content"]
    assert "Ticker: AAPL" in user_content
    assert "Horizon: swing" in user_content
    assert "Provenance index" in user_content
    # The only allowed citation URL is the chart URL for this ticker.
    assert "https://finance.yahoo.com/chart/AAPL" in user_content
    # Data payload is the indicator-augmented form, NOT raw OHLCV columns.
    assert "indicators_tail" in user_content
    assert "snapshot" in user_content


async def test_horizon_swaps_block_3_and_weighting_hint() -> None:
    df = _uptrend_frame()
    llm = FakeLLMProvider(_canned_output())

    await run("AAPL", df, "long_term", llm)
    call = llm.calls[-1]
    blocks = call["cache_blocks"]
    assert "Horizon: long_term" in blocks[2]
    assert "Weekly/monthly trend only" in call["messages"][0]["content"]


async def test_user_block_payload_caps_bars_at_60() -> None:
    df = _uptrend_frame(bars=300)
    llm = FakeLLMProvider(_canned_output())

    await run("AAPL", df, "swing", llm)
    call = llm.calls[0]
    # Find the JSON payload block after "Data payload:"
    content: str = call["messages"][0]["content"]
    payload_str = content.split("Data payload:\n", 1)[1].split("\n\nProduce", 1)[0]
    payload = json.loads(payload_str)
    assert len(payload["bars"]) == 60
    # 60 bars sent, but the analyst still reports the full lookback in metrics.


async def test_llm_citations_preserved_if_present() -> None:
    df = _uptrend_frame()
    canned = _canned_output()
    llm = FakeLLMProvider(canned)

    out = await run("AAPL", df, "swing", llm)
    assert len(out.citations) == 1
    assert out.citations[0].url == "https://finance.yahoo.com/chart/AAPL"


async def test_llm_empty_citations_get_chart_url_fallback() -> None:
    """If the LLM omits citations (against the rules), the analyst stamps
    in the chart URL so the synthesizer's per-finding attribution still works."""
    df = _uptrend_frame()
    canned = AnalystOutput(
        findings=["Trend is up."],
        confidence=0.6,
        key_metrics={},
        citations=[],
    )
    llm = FakeLLMProvider(canned)

    out = await run("AAPL", df, "swing", llm)
    assert len(out.citations) == 1
    assert out.citations[0].url == "https://finance.yahoo.com/chart/AAPL"


async def test_swing_resistance_levels_detected() -> None:
    """A frame with a clear local high should surface that high as resistance."""
    end = datetime(2026, 5, 13, tzinfo=UTC)
    n = 60
    idx = pd.DatetimeIndex(
        [end - timedelta(days=n - 1 - i) for i in range(n)], name="timestamp", tz="UTC"
    )
    # Triangle: rises to a single peak around bar 30, then falls. Use a
    # small asymmetric kink so the peak bar is the unique local max.
    peak = 30
    closes = [100.0 + (peak - abs(peak - i)) * 0.7 for i in range(n)]
    closes[peak] += 1.5  # guarantee a strict local max at `peak`
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    df = pd.DataFrame(
        {
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1_000_000.0] * n,
        },
        index=idx,
    )
    llm = FakeLLMProvider(_canned_output())
    out = await run("AAPL", df, "swing", llm)

    resistances = out.key_metrics["resistance"]
    assert isinstance(resistances, list)
    assert len(resistances) >= 1
    assert max(resistances) == pytest.approx(max(highs), rel=1e-6)

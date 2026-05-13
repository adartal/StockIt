"""Tests for the macro analyst.

A fake `LLMProvider` records the messages and `cache_blocks` it received
and returns a canned `AnalystOutput`. We assert on:

- the prompt structure (5 cache blocks in order; user block carries
  ticker/horizon/provenance/payload),
- horizon → cache-block selection,
- deterministic regime classifications injected into `key_metrics`,
- that the provenance URLs cover the FRED + Yahoo data sources the prompt
  design specifies.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.provider import Message
from app.pipeline.analysts import macro as macro_analyst
from app.pipeline.data.macro import MacroBundle, RateReading
from app.pipeline.schema import AnalystOutput, Citation, Horizon


class FakeLLMProvider:
    """Test double for LLMProvider that returns a fixed `AnalystOutput`."""

    name = "fake"

    def __init__(self, output: AnalystOutput) -> None:
        self.output = output
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
                "messages": list(messages),
                "response_model": response_model,
                "cache_blocks": list(cache_blocks) if cache_blocks else None,
                "max_retries": max_retries,
            }
        )
        return self.output


def _bundle(
    *,
    vix: float = 18.0,
    sector_perf: float = 0.08,
    spy_perf: float = 0.04,
    dgs2_latest: float = 4.5,
    dgs2_delta: float = -0.20,
    dgs10_latest: float = 4.1,
    dgs10_delta: float = 0.05,
    etf: str = "XLK",
) -> MacroBundle:
    return MacroBundle(
        rates={
            "DGS2": RateReading(latest=dgs2_latest, delta_30d=dgs2_delta),
            "DGS10": RateReading(latest=dgs10_latest, delta_30d=dgs10_delta),
        },
        vix=vix,
        sector_etf_ticker=etf,
        sector_etf_perf_30d=sector_perf,
        spy_perf_30d=spy_perf,
    )


def _canned_output(citation_url: str = "https://fred.stlouisfed.org/series/DGS2") -> AnalystOutput:
    return AnalystOutput(
        findings=[
            "Short rates ticking lower over the last 30 days while the curve "
            "remains compressed.",
            "Sector ETF outperformed SPY over the trailing 30 days.",
        ],
        confidence=0.6,
        key_metrics={"dgs2": 4.5, "vix": 18.0},
        citations=[
            Citation(
                url=citation_url,
                title="2-Year Treasury Constant Maturity Rate",
                source="FRED",
                fetched_at="2026-05-13T14:00:00+00:00",
            )
        ],
    )


@pytest.mark.asyncio
async def test_run_returns_analyst_output_with_injected_metrics() -> None:
    data = _bundle()
    fake = FakeLLMProvider(_canned_output())

    result = await macro_analyst.run("AAPL", data, "swing", fake)

    assert isinstance(result, AnalystOutput)
    assert result.findings == fake.output.findings
    assert result.confidence == pytest.approx(0.6)
    # deterministic regime metrics are injected on top of the model's metrics
    assert result.key_metrics["dgs2"] == 4.5
    assert result.key_metrics["rates_regime"] == "easing"
    assert result.key_metrics["vix_regime"] == "normal"
    assert result.key_metrics["sector_relative_perf_30d"] == pytest.approx(0.04)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dgs2_delta", "expected"),
    [(-0.20, "easing"), (-0.05, "flat"), (0.0, "flat"), (0.05, "flat"), (0.25, "tightening")],
)
async def test_rates_regime_classification(dgs2_delta: float, expected: str) -> None:
    data = _bundle(dgs2_delta=dgs2_delta)
    fake = FakeLLMProvider(_canned_output())

    result = await macro_analyst.run("AAPL", data, "swing", fake)
    assert result.key_metrics["rates_regime"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vix", "expected"),
    [
        (10.0, "low"),
        (14.99, "low"),
        (15.0, "normal"),
        (20.0, "normal"),
        (25.0, "high"),
        (40.0, "high"),
    ],
)
async def test_vix_regime_classification(vix: float, expected: str) -> None:
    data = _bundle(vix=vix)
    fake = FakeLLMProvider(_canned_output())

    result = await macro_analyst.run("AAPL", data, "swing", fake)
    assert result.key_metrics["vix_regime"] == expected


@pytest.mark.asyncio
async def test_prompt_has_five_cache_blocks_in_order() -> None:
    data = _bundle()
    fake = FakeLLMProvider(_canned_output())

    await macro_analyst.run("AAPL", data, "swing", fake)

    call = fake.calls[0]
    blocks = call["cache_blocks"]
    assert blocks is not None
    assert len(blocks) == 5
    assert blocks[0] == macro_analyst.PERSONA_BLOCK
    assert blocks[1] == macro_analyst.SCHEMA_BLOCK
    assert blocks[2] == macro_analyst.HORIZON_BLOCKS["swing"]
    assert blocks[3] == macro_analyst.RUBRIC_BLOCK
    assert blocks[4] == macro_analyst.BIAS_GUARDS_BLOCK


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon", ["intraday", "swing", "long_term"])
async def test_horizon_block_swaps(horizon: Horizon) -> None:
    data = _bundle()
    fake = FakeLLMProvider(_canned_output())

    await macro_analyst.run("AAPL", data, horizon, fake)

    blocks = fake.calls[0]["cache_blocks"]
    assert blocks[2] == macro_analyst.HORIZON_BLOCKS[horizon]


@pytest.mark.asyncio
async def test_intraday_horizon_block_requests_single_bullet() -> None:
    """Intraday horizon block must instruct the model to emit one finding."""
    block = macro_analyst.HORIZON_BLOCKS["intraday"]
    assert "ONE" in block or "one" in block
    # also asserts macro is regime-only for intraday
    assert "regime" in block.lower()


@pytest.mark.asyncio
async def test_user_block_contains_ticker_horizon_payload_provenance() -> None:
    data = _bundle()
    fake = FakeLLMProvider(_canned_output())

    await macro_analyst.run("AAPL", data, "long_term", fake)

    user_msg = fake.calls[0]["messages"][0]
    assert user_msg["role"] == "user"
    content = user_msg["content"]
    assert "Ticker: AAPL" in content
    assert "Horizon: long_term" in content
    # provenance URLs all present
    assert "https://fred.stlouisfed.org/series/DGS2" in content
    assert "https://fred.stlouisfed.org/series/DGS10" in content
    assert "https://finance.yahoo.com/quote/%5EVIX" in content
    assert "https://finance.yahoo.com/quote/SPY" in content
    assert "https://finance.yahoo.com/quote/XLK" in content
    # payload reflects the bundle
    assert '"sector_etf_ticker": "XLK"' in content
    assert '"vix": 18.0' in content


@pytest.mark.asyncio
async def test_provider_called_with_response_model_and_one_retry() -> None:
    data = _bundle()
    fake = FakeLLMProvider(_canned_output())

    await macro_analyst.run("AAPL", data, "swing", fake)

    call = fake.calls[0]
    assert call["response_model"] is AnalystOutput
    assert call["max_retries"] == 1


@pytest.mark.asyncio
async def test_long_term_horizon_uses_long_term_weighting_hint() -> None:
    data = _bundle()
    fake = FakeLLMProvider(_canned_output())

    await macro_analyst.run("AAPL", data, "long_term", fake)

    content = fake.calls[0]["messages"][0]["content"]
    assert "First-class input" in content


@pytest.mark.asyncio
async def test_intraday_horizon_uses_intraday_weighting_hint() -> None:
    data = _bundle()
    fake = FakeLLMProvider(_canned_output())

    await macro_analyst.run("AAPL", data, "intraday", fake)

    content = fake.calls[0]["messages"][0]["content"]
    assert "ONE bullet" in content


@pytest.mark.asyncio
async def test_provenance_index_is_valid_json_in_user_block() -> None:
    """The provenance index block must be parseable JSON."""
    data = _bundle(etf="XLE")
    fake = FakeLLMProvider(_canned_output())

    await macro_analyst.run("AAPL", data, "swing", fake)

    content = fake.calls[0]["messages"][0]["content"]
    # extract the provenance JSON array — it's between
    # "Provenance index ...:\n" and "\n\nData payload:"
    start_marker = "may cite):\n"
    end_marker = "\n\nData payload:"
    start = content.index(start_marker) + len(start_marker)
    end = content.index(end_marker, start)
    provenance = json.loads(content[start:end])

    assert isinstance(provenance, list)
    assert len(provenance) == 5
    for entry in provenance:
        assert set(entry.keys()) == {"url", "title", "source", "fetched_at"}
    urls = {e["url"] for e in provenance}
    assert "https://finance.yahoo.com/quote/XLE" in urls

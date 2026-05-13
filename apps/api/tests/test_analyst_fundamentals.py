"""Tests for the M4a fundamentals analyst.

A fake `LLMProvider` captures the call's `cache_blocks` and `messages`
so we can assert the prompt structure laid out in
docs/analyst-prompt-design.md. The LLM itself just returns a canned
`AnalystOutput`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import BaseModel

from app.llm.provider import LLMProvider, Message
from app.pipeline.analysts.fundamentals import (
    EXPECTED_METRIC_KEYS,
    GUARDS_BLOCK,
    HORIZON_BLOCKS,
    PERSONA_BLOCK,
    RUBRIC_BLOCK,
    SCHEMA_BLOCK,
    WEIGHTING_HINTS,
    build_cache_blocks,
    build_provenance,
    build_user_block,
    run,
)
from app.pipeline.data.fundamentals import FundamentalsBundle
from app.pipeline.schema import AnalystOutput, Citation, Horizon


def _full_bundle() -> FundamentalsBundle:
    return FundamentalsBundle(
        sector="Technology",
        industry="Consumer Electronics",
        market_cap=3.1e12,
        pe_ttm=31.8,
        pb=48.2,
        ps=8.4,
        profit_margin=0.262,
        revenue_growth_yoy=0.043,
        debt_to_equity=1.95,
        free_cash_flow_ttm=1.08e11,
        latest_10k_url="https://www.sec.gov/Archives/edgar/data/320193/aapl-10k.htm",
        latest_10q_url="https://www.sec.gov/Archives/edgar/data/320193/aapl-10q.htm",
        latest_10q_filed_at=datetime(2026, 4, 30, 20, 0, tzinfo=UTC),
    )


def _canned_output(provenance: list[dict[str, str]]) -> AnalystOutput:
    cite = provenance[0]
    return AnalystOutput(
        findings=[
            "Profit margin 26.2% with revenue growth 4.3% YoY per the latest 10-Q.",
            "Net leverage elevated at D/E 1.95 against $108B TTM free cash flow.",
        ],
        confidence=0.7,
        key_metrics={"pe_ttm": 31.8, "free_cash_flow_ttm": 1.08e11},
        citations=[
            Citation(
                url=cite["url"],
                title=cite["title"],
                source=cite["source"],
                fetched_at=datetime.fromisoformat(cite["fetched_at"]),
            )
        ],
    )


class FakeLLM:
    """Captures the last call and returns a canned `AnalystOutput`.

    `response_factory` receives the call args dict so a test can build
    a canned output that references the provenance URLs actually passed.
    """

    name = "fake"

    def __init__(self, response_factory: Any) -> None:
        self.response_factory = response_factory
        self.calls: list[dict[str, Any]] = []

    async def complete_structured(
        self,
        messages: list[Message],
        response_model: type[BaseModel],
        *,
        cache_blocks: list[str] | None = None,
        max_retries: int = 1,
    ) -> BaseModel:
        call = {
            "messages": messages,
            "response_model": response_model,
            "cache_blocks": cache_blocks,
            "max_retries": max_retries,
        }
        self.calls.append(call)
        result = self.response_factory(call)
        return cast(BaseModel, result)


def test_fake_llm_satisfies_provider_protocol() -> None:
    prov = [
        {
            "url": "x",
            "title": "t",
            "source": "s",
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    ]
    fake = FakeLLM(lambda _call: _canned_output(prov))
    assert isinstance(fake, LLMProvider)


def test_build_provenance_includes_10k_10q_and_yahoo() -> None:
    data = _full_bundle()
    fetched_at = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)

    prov = build_provenance("AAPL", data, fetched_at)

    urls = [p["url"] for p in prov]
    assert data.latest_10k_url in urls
    assert data.latest_10q_url in urls
    assert "https://finance.yahoo.com/quote/AAPL" in urls
    # Sources are labelled correctly.
    sources = {p["url"]: p["source"] for p in prov}
    assert sources[data.latest_10k_url] == "SEC EDGAR"
    assert sources[data.latest_10q_url] == "SEC EDGAR"
    assert sources["https://finance.yahoo.com/quote/AAPL"] == "Yahoo Finance"


def test_build_provenance_skips_missing_filings() -> None:
    data = FundamentalsBundle(pe_ttm=20.0)  # no filings, no filed_at
    prov = build_provenance("AAPL", data, datetime(2026, 5, 13, tzinfo=UTC))
    assert len(prov) == 1
    assert prov[0]["url"] == "https://finance.yahoo.com/quote/AAPL"


@pytest.mark.parametrize("horizon", ["intraday", "swing", "long_term"])
def test_build_cache_blocks_order_and_horizon_swap(horizon: Horizon) -> None:
    blocks = build_cache_blocks(horizon)
    assert blocks[0] == PERSONA_BLOCK
    assert blocks[1] == SCHEMA_BLOCK
    assert blocks[2] == HORIZON_BLOCKS[horizon]
    assert blocks[3] == RUBRIC_BLOCK
    assert blocks[4] == GUARDS_BLOCK
    # Each horizon block is distinct so caching keys differ per horizon.
    all_horizons: tuple[Horizon, ...] = ("intraday", "swing", "long_term")
    for other in all_horizons:
        if other == horizon:
            continue
        assert blocks[2] != HORIZON_BLOCKS[other]


def test_persona_block_is_fundamentals_specific() -> None:
    assert "equity fundamentals analyst" in PERSONA_BLOCK
    # Bias guards apply to all analysts; persona is the only role swap.
    assert "fundamentals" not in GUARDS_BLOCK.lower()


def test_build_user_block_contains_required_sections() -> None:
    data = _full_bundle()
    as_of = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
    prov = build_provenance("AAPL", data, as_of)

    user = build_user_block("AAPL", data, "long_term", as_of, prov)

    assert "Ticker: AAPL" in user
    assert "Horizon: long_term" in user
    assert "As-of (UTC): 2026-05-13T14:00:00+00:00" in user
    assert WEIGHTING_HINTS["long_term"] in user
    assert "Provenance index" in user
    assert "Data payload:" in user
    # Provenance URLs appear; data payload is JSON-serialized.
    assert data.latest_10k_url is not None
    assert data.latest_10k_url in user
    assert "31.8" in user  # pe_ttm
    assert user.rstrip().endswith("JSON only.")


@pytest.mark.parametrize(
    "horizon",
    ["intraday", "swing", "long_term"],
)
async def test_run_invokes_llm_with_correct_prompt_shape(horizon: Horizon) -> None:
    data = _full_bundle()
    fake = FakeLLM(lambda call: _canned_output(_extract_provenance(call)))

    result = await run("aapl", data, horizon, fake)

    assert isinstance(result, AnalystOutput)
    assert len(fake.calls) == 1
    call = fake.calls[0]

    # cache_blocks order matches the design doc and selects the right horizon.
    assert call["cache_blocks"] == build_cache_blocks(horizon)
    # response_model is AnalystOutput so the M3 router validates the JSON.
    assert call["response_model"] is AnalystOutput
    # One user message carrying the uncached block.
    messages = call["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    user_block = messages[0]["content"]
    # Ticker is upper-cased before going into the prompt.
    assert "Ticker: AAPL" in user_block
    assert f"Horizon: {horizon}" in user_block
    assert WEIGHTING_HINTS[horizon] in user_block


async def test_run_preserves_llm_findings_and_merges_expected_metrics() -> None:
    data = _full_bundle()
    fake = FakeLLM(lambda call: _canned_output(_extract_provenance(call)))

    result = await run("AAPL", data, "long_term", fake)

    # Findings + confidence + citations come from the LLM untouched.
    assert result.confidence == 0.7
    assert len(result.findings) == 2
    assert len(result.citations) == 1

    # §10.1 default: §8 expected keys are present after parsing.
    for key in EXPECTED_METRIC_KEYS:
        assert key in result.key_metrics, f"missing expected key_metric: {key}"
    # Data-derived values fill the keys the LLM omitted.
    assert result.key_metrics["sector"] == "Technology"
    assert result.key_metrics["market_cap"] == 3.1e12
    assert result.key_metrics["latest_filing_date"] == "2026-04-30T20:00:00+00:00"
    # LLM-provided keys win where they overlap.
    assert result.key_metrics["pe_ttm"] == 31.8
    assert result.key_metrics["free_cash_flow_ttm"] == 1.08e11


async def test_run_empty_bundle_short_circuits_without_llm_call() -> None:
    fake = FakeLLM(lambda _call: _canned_output([]))
    data = FundamentalsBundle()  # all fields None

    result = await run("AAPL", data, "swing", fake)

    assert fake.calls == []  # no LLM call
    assert result.findings == []
    assert result.confidence == 0.0
    assert result.citations == []
    # §8 expected keys are still present so the synthesizer sees a stable shape.
    for key in EXPECTED_METRIC_KEYS:
        assert key in result.key_metrics


async def test_run_rejects_empty_ticker() -> None:
    fake = FakeLLM(lambda _call: _canned_output([]))
    with pytest.raises(ValueError):
        await run("   ", _full_bundle(), "swing", fake)


def _extract_provenance(call: dict[str, Any]) -> list[dict[str, str]]:
    """Pull the JSON provenance array back out of the user block."""
    user_block: str = call["messages"][0]["content"]
    start = user_block.index("Provenance index")
    bracket_start = user_block.index("[", start)
    depth = 0
    for i in range(bracket_start, len(user_block)):
        ch = user_block[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                parsed = json.loads(user_block[bracket_start : i + 1])
                return cast(list[dict[str, str]], parsed)
    raise AssertionError("provenance JSON not found in user block")

"""Tests for the M5b synthesizer.

A fake `LLMProvider` captures the call's `cache_blocks` and `messages`
so we can assert prompt structure, and lets a test scenario script
multi-call behavior for the validation-retry path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from app.llm.provider import LLMProvider, Message
from app.models import UserRiskConfig
from app.pipeline.schema import (
    AnalystOutput,
    Citation,
    Entry,
    ExitLevel,
    Horizon,
    Plan,
    Sizing,
    Stop,
)
from app.pipeline.synth import (
    CLARIFY_PREFIX,
    GUARDS_BLOCK,
    HORIZON_WEIGHTING,
    PERSONA_BLOCK,
    RULES_BLOCK,
    SCHEMA_BLOCK,
    build_cache_blocks,
    build_user_block,
    synthesize,
)

# ---------- fixtures ----------


def _cite(url: str) -> Citation:
    return Citation(
        url=url,
        title="t",
        source="src",
        fetched_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
    )


def _analyst_outputs() -> dict[str, AnalystOutput]:
    return {
        "fundamentals": AnalystOutput(
            findings=["FCF $108B, margins 26%."],
            confidence=0.7,
            key_metrics={"pe_ttm": 31.8},
            citations=[_cite("https://sec.gov/aapl-10q")],
        ),
        "technicals": AnalystOutput(
            findings=["Holding 50-day SMA; RSI 58."],
            confidence=0.6,
            key_metrics={"sma_50": 188.0, "rsi_14": 58.0},
            citations=[_cite("https://finance.yahoo.com/quote/AAPL")],
        ),
        "news": AnalystOutput(
            findings=["No fresh material headlines in last 7 days."],
            confidence=0.4,
            key_metrics={"headline_count_7d": 3},
            citations=[_cite("https://news.example/aapl-1")],
        ),
        "macro": AnalystOutput(
            findings=["Rate-cut path priced; tech beta elevated."],
            confidence=0.5,
            key_metrics={"regime": "late_cycle"},
            citations=[_cite("https://fred.example/fedfunds")],
        ),
    }


def _risk_config() -> UserRiskConfig:
    return UserRiskConfig(
        user_id=uuid.uuid4(),
        risk_per_trade_pct=1.0,
        max_position_pct=10.0,
        preferred_llm="claude",
    )


def _canned_plan(
    ticker: str = "AAPL",
    horizon: Horizon = "swing",
    capital: Decimal = Decimal("10000"),
    *,
    citations: list[Citation] | None = None,
) -> Plan:
    return Plan(
        ticker=ticker,
        horizon=horizon,
        capital=capital,
        generated_at=datetime(2026, 5, 13, 14, 0, tzinfo=UTC),
        thesis="Holding key MA with constructive fundamentals; thin news flow.",
        conviction="medium",
        entry=Entry(kind="limit", levels=[Decimal("190")], conditions="on pullback to 50dma"),
        sizing=Sizing(
            risk_pct=1.0,
            shares=20,
            dollar_exposure=Decimal("3800"),
            R_value=Decimal("5"),
        ),
        stop=Stop(price=Decimal("185"), kind="technical", rationale="below 50dma"),
        exits=[
            ExitLevel(
                kind="scale_out",
                price=Decimal("205"),
                trigger="first target",
                portion=0.5,
            )
        ],
        catalysts=[],
        risk_flags=[],
        review_cadence="weekly",
        sources=citations or [_cite("https://sec.gov/aapl-10q")],
    )


class FakeLLM:
    """Records every call and returns a scripted response per call index."""

    name = "fake"

    def __init__(self, responses: list[Any]) -> None:
        # Each entry is either a BaseModel to return or an Exception to raise.
        self._responses = list(responses)
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
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return cast(BaseModel, nxt)


# ---------- protocol / structural tests ----------


def test_fake_llm_satisfies_provider_protocol() -> None:
    fake = FakeLLM([_canned_plan()])
    assert isinstance(fake, LLMProvider)


@pytest.mark.parametrize("horizon", ["intraday", "swing", "long_term"])
def test_build_cache_blocks_order_and_horizon_swap(horizon: Horizon) -> None:
    blocks = build_cache_blocks(horizon)
    assert blocks[0] == PERSONA_BLOCK
    assert blocks[1] == SCHEMA_BLOCK
    assert blocks[2] == HORIZON_WEIGHTING[horizon]
    assert blocks[3] == RULES_BLOCK
    assert blocks[4] == GUARDS_BLOCK
    # Each horizon block is distinct so cache keys differ per horizon.
    others: tuple[Horizon, ...] = ("intraday", "swing", "long_term")
    for other in others:
        if other == horizon:
            continue
        assert blocks[2] != HORIZON_WEIGHTING[other]


def test_rules_block_mandates_stop_and_empty_risk_flags() -> None:
    assert "STOP-LOSS IS MANDATORY" in RULES_BLOCK
    assert "strictly below" in RULES_BLOCK
    assert "risk_flags" in RULES_BLOCK
    assert "empty list" in RULES_BLOCK


def test_guards_block_isolates_synth_from_raw_data() -> None:
    text = GUARDS_BLOCK.lower()
    assert "only analyst summaries" in text
    assert "do not have access to raw" in text


def test_schema_block_no_invent_urls() -> None:
    assert "Do not invent URLs" in SCHEMA_BLOCK
    assert "from one of the analyst citations" in SCHEMA_BLOCK


def test_persona_is_portfolio_manager() -> None:
    assert "portfolio manager" in PERSONA_BLOCK
    assert "analyst" in PERSONA_BLOCK


# ---------- user-block content ----------


def test_build_user_block_contains_required_sections() -> None:
    as_of = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
    user = build_user_block(
        "AAPL",
        "swing",
        Decimal("10000"),
        _risk_config(),
        _analyst_outputs(),
        as_of,
    )
    assert "Ticker: AAPL" in user
    assert "Horizon: swing" in user
    assert "Capital (USD): 10000" in user
    assert "Generated at (UTC): 2026-05-13T14:00:00+00:00" in user
    assert "risk_per_trade_pct=1.0" in user
    assert "max_position_pct=10.0" in user
    # All four analyst outputs serialized.
    assert "fundamentals" in user
    assert "technicals" in user
    assert "news" in user
    assert "macro" in user
    # Sample analyst content / citation appears.
    assert "FCF $108B" in user
    assert "https://sec.gov/aapl-10q" in user
    assert user.rstrip().endswith("Emit a stop-loss strictly below entry.")


def test_build_user_block_analyst_ordering_is_stable() -> None:
    """Stable analyst-key ordering matters for prompt caching."""
    as_of = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
    # Construct dict in non-preferred insertion order.
    out = _analyst_outputs()
    shuffled = {
        "news": out["news"],
        "macro": out["macro"],
        "fundamentals": out["fundamentals"],
        "technicals": out["technicals"],
    }
    user = build_user_block(
        "AAPL", "swing", Decimal("10000"), _risk_config(), shuffled, as_of
    )
    # The four keys appear in the preferred order: fund, tech, news, macro.
    fund_pos = user.index('"fundamentals"')
    tech_pos = user.index('"technicals"')
    news_pos = user.index('"news"')
    macro_pos = user.index('"macro"')
    assert fund_pos < tech_pos < news_pos < macro_pos


def test_build_user_block_handles_extra_analyst_key() -> None:
    """Unknown analyst keys are appended in sorted order after the preferred four."""
    as_of = datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
    out = _analyst_outputs()
    out["alt_data"] = AnalystOutput(
        findings=["beta signal"], confidence=0.3, key_metrics={}, citations=[]
    )
    user = build_user_block(
        "AAPL", "swing", Decimal("10000"), _risk_config(), out, as_of
    )
    assert '"alt_data"' in user
    # Appears after the four preferred keys.
    assert user.index('"alt_data"') > user.index('"macro"')


# ---------- happy-path synthesize ----------


@pytest.mark.parametrize("horizon", ["intraday", "swing", "long_term"])
async def test_synthesize_invokes_llm_with_correct_prompt_shape(
    horizon: Horizon,
) -> None:
    fake = FakeLLM([_canned_plan(horizon=horizon)])
    result = await synthesize(
        ticker="aapl",  # lower-cased; synth normalizes.
        horizon=horizon,
        capital=Decimal("10000"),
        risk_config=_risk_config(),
        analyst_outputs=_analyst_outputs(),
        llm=fake,
    )

    assert isinstance(result, Plan)
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["response_model"] is Plan
    # cache_blocks shape matches design.
    blocks = call["cache_blocks"]
    assert blocks[0] == PERSONA_BLOCK
    assert blocks[2] == HORIZON_WEIGHTING[horizon]
    # User block carries normalized ticker (upper-case).
    assert len(call["messages"]) == 1
    assert call["messages"][0]["role"] == "user"
    assert "Ticker: AAPL" in call["messages"][0]["content"]


async def test_synthesize_passes_all_analyst_outputs_in_user_block() -> None:
    fake = FakeLLM([_canned_plan()])
    outs = _analyst_outputs()
    await synthesize(
        ticker="AAPL",
        horizon="swing",
        capital=Decimal("10000"),
        risk_config=_risk_config(),
        analyst_outputs=outs,
        llm=fake,
    )
    content = fake.calls[0]["messages"][0]["content"]
    # Each analyst's first finding shows up verbatim.
    for slot, out in outs.items():
        assert slot in content
        assert out.findings[0] in content


async def test_synthesize_empty_ticker_raises() -> None:
    fake = FakeLLM([_canned_plan()])
    with pytest.raises(ValueError):
        await synthesize(
            ticker="   ",
            horizon="swing",
            capital=Decimal("10000"),
            risk_config=_risk_config(),
            analyst_outputs=_analyst_outputs(),
            llm=fake,
        )


# ---------- validation-retry path ----------


def _validation_error() -> ValidationError:
    """Construct a real pydantic ValidationError for the Plan schema."""
    with pytest.raises(ValidationError) as exc:
        Plan.model_validate({})  # missing every required field
    return exc.value


async def test_synthesize_retries_once_on_validation_error_with_clarify_note() -> None:
    err = _validation_error()
    good = _canned_plan()
    fake = FakeLLM([err, good])

    result = await synthesize(
        ticker="AAPL",
        horizon="swing",
        capital=Decimal("10000"),
        risk_config=_risk_config(),
        analyst_outputs=_analyst_outputs(),
        llm=fake,
    )

    assert result is good
    assert len(fake.calls) == 2

    first_msgs = fake.calls[0]["messages"]
    second_msgs = fake.calls[1]["messages"]
    # Retry preserves the original user block and appends a clarifying note.
    assert second_msgs[0] == first_msgs[0]
    assert len(second_msgs) == 2
    assert second_msgs[1]["role"] == "user"
    assert second_msgs[1]["content"].startswith(CLARIFY_PREFIX)
    # The clarifying note quotes the original validation error.
    assert "Validation error:" in second_msgs[1]["content"]
    # Cache blocks identical across both calls (cache reuse).
    assert fake.calls[0]["cache_blocks"] == fake.calls[1]["cache_blocks"]


async def test_synthesize_does_not_retry_more_than_once() -> None:
    err1 = _validation_error()
    err2 = _validation_error()
    fake = FakeLLM([err1, err2])

    with pytest.raises(ValidationError):
        await synthesize(
            ticker="AAPL",
            horizon="swing",
            capital=Decimal("10000"),
            risk_config=_risk_config(),
            analyst_outputs=_analyst_outputs(),
            llm=fake,
        )
    assert len(fake.calls) == 2


# ---------- output validation ----------


async def test_synthesize_result_is_real_plan_with_stop_below_entry() -> None:
    """Acceptance check: synth's contract is that the Plan it returns has
    a stop strictly below entry (so the risk module won't reject)."""
    fake = FakeLLM([_canned_plan()])
    plan = await synthesize(
        ticker="AAPL",
        horizon="swing",
        capital=Decimal("10000"),
        risk_config=_risk_config(),
        analyst_outputs=_analyst_outputs(),
        llm=fake,
    )
    assert plan.stop is not None
    assert Decimal(plan.stop.price) < Decimal(plan.entry.levels[0])
    # round-trip the plan through JSON to verify schema correctness.
    serialized = plan.model_dump_json()
    reparsed = Plan.model_validate_json(serialized)
    assert reparsed.ticker == "AAPL"

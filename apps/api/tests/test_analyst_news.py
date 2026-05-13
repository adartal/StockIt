"""Tests for the news analyst (M4c).

Uses a fake :class:`LLMProvider` that asserts the prompt structure
(cache blocks, user block contents) and returns a canned response, so
we can exercise the windowing / capping / provenance logic without
touching a real model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.llm.provider import LLMProvider, Message
from app.pipeline.analysts.news import run
from app.pipeline.data.news import NewsItem
from app.pipeline.schema import AnalystOutput, Citation, Horizon


class FakeNewsLLM:
    """LLMProvider double that captures the call and returns a canned model."""

    name = "fake-news"

    def __init__(self, response: BaseModel | Exception) -> None:
        self._response = response
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
                "cache_blocks": cache_blocks,
                "max_retries": max_retries,
            }
        )
        if isinstance(self._response, Exception):
            raise self._response
        # Re-validate through the requested model so the test mirrors the
        # real instructor-backed path.
        return response_model.model_validate(self._response.model_dump())


def _item(
    *,
    url: str,
    title: str,
    source: str,
    days_ago: float,
    summary: str | None = None,
) -> NewsItem:
    return NewsItem(
        url=url,
        title=title,
        source=source,
        published_at=datetime.now(UTC) - timedelta(days=days_ago),
        summary=summary,
    )


def _canned_response(
    response_model: type[BaseModel],
    *,
    citation_urls: list[str],
    sentiment_score: float = 0.4,
    dominant_themes: list[str] | None = None,
    num_items: int | None = None,
    findings: list[str] | None = None,
    confidence: float = 0.7,
) -> BaseModel:
    """Build a response that satisfies the analyst's internal model."""
    fetched = datetime.now(UTC)
    return response_model.model_validate(
        {
            "findings": findings
            or [
                "Coverage skews toward product-launch narrative this period.",
                "Multiple outlets report data-center capex acceleration.",
            ],
            "confidence": confidence,
            "key_metrics": {
                "sentiment_score": sentiment_score,
                "num_items": num_items if num_items is not None else len(citation_urls),
                "dominant_themes": dominant_themes or ["product launch", "capex"],
            },
            "citations": [
                {
                    "url": url,
                    "title": f"title for {url}",
                    "source": "FakeSource",
                    "fetched_at": fetched.isoformat(),
                }
                for url in citation_urls
            ],
        }
    )


def test_fake_satisfies_protocol() -> None:
    # Sanity: ensure FakeNewsLLM conforms to the LLMProvider Protocol so
    # the real router would accept it too.
    fake = FakeNewsLLM(
        AnalystOutput(findings=["x"], confidence=0.1, key_metrics={}, citations=[])
    )
    assert isinstance(fake, LLMProvider)


async def test_empty_data_skips_llm_and_returns_zero_confidence() -> None:
    fake = FakeNewsLLM(
        AnalystOutput(findings=["unused"], confidence=0.9, key_metrics={}, citations=[])
    )

    out = await run("AAPL", [], "swing", fake)

    assert fake.calls == []
    assert out.confidence == 0.0
    assert out.citations == []
    assert out.key_metrics["num_items"] == 0
    assert out.key_metrics["sentiment_score"] == 0.0
    assert out.key_metrics["dominant_themes"] == []
    assert len(out.findings) == 1


@pytest.mark.parametrize(
    ("horizon", "window_days"),
    [("intraday", 7), ("swing", 30), ("long_term", 90)],
)
async def test_horizon_window_filters_old_items(horizon: Horizon, window_days: int) -> None:
    items = [
        _item(url="https://a.test/recent", title="Recent", source="A", days_ago=0.5),
        _item(
            url="https://b.test/old",
            title="Old",
            source="B",
            days_ago=window_days + 5,
        ),
    ]

    captured: dict[str, Any] = {}

    class CapturingLLM:
        name = "cap"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            captured["messages"] = messages
            captured["cache_blocks"] = cache_blocks
            return _canned_response(
                response_model,
                citation_urls=["https://a.test/recent"],
            )

    fake = CapturingLLM()
    out = await run("MSFT", items, horizon, fake)

    user_content = captured["messages"][0]["content"]
    assert "https://a.test/recent" in user_content
    assert "https://b.test/old" not in user_content
    assert any("https://a.test/recent" == c.url for c in out.citations)
    assert all(c.url != "https://b.test/old" for c in out.citations)


async def test_items_are_capped_at_30_and_sorted_newest_first() -> None:
    items = [
        _item(
            url=f"https://x.test/item-{i:02d}",
            title=f"Item {i}",
            source="X",
            days_ago=i,
        )
        for i in range(40)
    ]

    captured: dict[str, Any] = {}

    class CapturingLLM:
        name = "cap"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            captured["user"] = messages[0]["content"]
            return _canned_response(response_model, citation_urls=[items[0].url])

    fake = CapturingLLM()
    await run("NVDA", items, "long_term", fake)

    user_content = captured["user"]
    # Within window (<=90 days), 40 items qualify but only 30 newest
    # should land in the payload. URLs appear in both the provenance
    # index and the data payload, hence 60 total occurrences.
    assert user_content.count('"url": "https://x.test/item-') == 60
    # The newest (item-00 = today) must appear; the 31st-newest
    # (item-30) must be dropped from both sections.
    assert "https://x.test/item-00" in user_content
    assert "https://x.test/item-30" not in user_content


async def test_hallucinated_citations_are_dropped() -> None:
    items = [
        _item(url="https://real.test/a", title="A", source="R", days_ago=1),
        _item(url="https://real.test/b", title="B", source="R", days_ago=2),
    ]

    class HallucinatingLLM:
        name = "hallu"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            return _canned_response(
                response_model,
                citation_urls=[
                    "https://real.test/a",
                    "https://made-up.test/x",
                ],
            )

    out = await run("AMD", items, "swing", HallucinatingLLM())

    urls = {c.url for c in out.citations}
    assert urls == {"https://real.test/a"}


async def test_prompt_structure_uses_cache_blocks_and_user_block() -> None:
    items = [_item(url="https://n.test/1", title="One", source="N", days_ago=1)]

    captured: dict[str, Any] = {}

    class CapturingLLM:
        name = "cap"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            captured["messages"] = messages
            captured["cache_blocks"] = cache_blocks
            captured["max_retries"] = max_retries
            return _canned_response(response_model, citation_urls=["https://n.test/1"])

    await run("GOOG", items, "swing", CapturingLLM())

    cache_blocks = captured["cache_blocks"]
    assert isinstance(cache_blocks, list)
    # Persona, schema, horizon, rubric, bias guards - 5 blocks in this order.
    assert len(cache_blocks) == 5
    assert "equity news and sentiment analyst" in cache_blocks[0]
    assert "Output strictly one JSON object" in cache_blocks[1]
    assert "Horizon: swing" in cache_blocks[2]
    assert "Citation rules" in cache_blocks[3]
    assert "Sentiment scoring rubric" in cache_blocks[3]
    assert "You analyze, you do not recommend" in cache_blocks[4]

    user = captured["messages"][0]["content"]
    assert "Ticker: GOOG" in user
    assert "Horizon: swing" in user
    assert "Provenance index" in user
    assert "Data payload" in user
    assert captured["max_retries"] == 1


async def test_horizon_block_swaps_with_horizon() -> None:
    items = [_item(url="https://n.test/1", title="One", source="N", days_ago=1)]
    captured: dict[Horizon, list[str]] = {}

    for horizon in ("intraday", "swing", "long_term"):
        slot: dict[str, list[str]] = {}

        class CapturingLLM:
            name = "cap"

            def __init__(self, sink: dict[str, list[str]]) -> None:
                self._sink = sink

            async def complete_structured(
                self,
                messages: list[Message],
                response_model: type[BaseModel],
                *,
                cache_blocks: list[str] | None = None,
                max_retries: int = 1,
            ) -> BaseModel:
                assert cache_blocks is not None
                self._sink["blocks"] = cache_blocks
                return _canned_response(
                    response_model, citation_urls=["https://n.test/1"]
                )

        await run("AAPL", items, horizon, CapturingLLM(slot))
        captured[horizon] = slot["blocks"]

    assert "Horizon: intraday" in captured["intraday"][2]
    assert "Horizon: swing" in captured["swing"][2]
    assert "Horizon: long_term" in captured["long_term"][2]
    # Non-horizon blocks are identical across calls (cache prefix shared).
    for idx in (0, 1, 3, 4):
        assert (
            captured["intraday"][idx]
            == captured["swing"][idx]
            == captured["long_term"][idx]
        )


async def test_returns_analyst_output_with_expected_key_metrics() -> None:
    items = [
        _item(url="https://k.test/a", title="A", source="K", days_ago=1),
        _item(url="https://k.test/b", title="B", source="K", days_ago=2),
    ]

    class LLM:
        name = "ok"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            return _canned_response(
                response_model,
                citation_urls=["https://k.test/a", "https://k.test/b"],
                sentiment_score=-0.3,
                dominant_themes=["regulatory", "guidance cut"],
                num_items=2,
            )

    out = await run("TSLA", items, "swing", LLM())

    assert isinstance(out, AnalystOutput)
    assert set(out.key_metrics.keys()) == {
        "sentiment_score",
        "num_items",
        "dominant_themes",
    }
    assert out.key_metrics["sentiment_score"] == -0.3
    assert out.key_metrics["num_items"] == 2
    assert out.key_metrics["dominant_themes"] == ["regulatory", "guidance cut"]
    assert {c.url for c in out.citations} == {"https://k.test/a", "https://k.test/b"}


async def test_provenance_dedups_duplicate_urls() -> None:
    # Two items with the same URL (an aggregator scenario the news
    # fetcher already dedups, but the analyst shouldn't depend on it).
    same_url = "https://dup.test/x"
    items = [
        _item(url=same_url, title="A", source="S1", days_ago=1),
        _item(url=same_url, title="B", source="S2", days_ago=2),
    ]

    captured: dict[str, str] = {}

    class CapturingLLM:
        name = "cap"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            captured["user"] = messages[0]["content"]
            return _canned_response(response_model, citation_urls=[same_url])

    await run("INTC", items, "swing", CapturingLLM())

    # Extract just the provenance section
    user = captured["user"]
    prov_start = user.index("Provenance index")
    prov_end = user.index("Data payload")
    provenance_block = user[prov_start:prov_end]
    assert provenance_block.count(same_url) == 1


async def test_empty_ticker_raises() -> None:
    fake = FakeNewsLLM(
        AnalystOutput(findings=["x"], confidence=0.1, key_metrics={}, citations=[])
    )
    with pytest.raises(ValueError):
        await run("", [], "swing", fake)


async def test_intraday_window_drops_items_older_than_seven_days() -> None:
    items = [
        _item(url="https://i.test/new", title="Today", source="I", days_ago=0.1),
        _item(url="https://i.test/edge", title="Edge", source="I", days_ago=7.5),
    ]

    captured: dict[str, Any] = {}

    class CapturingLLM:
        name = "cap"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            captured["user"] = messages[0]["content"]
            return _canned_response(
                response_model, citation_urls=["https://i.test/new"]
            )

    out = await run("AAPL", items, "intraday", CapturingLLM())

    assert "https://i.test/new" in captured["user"]
    assert "https://i.test/edge" not in captured["user"]
    assert {c.url for c in out.citations} == {"https://i.test/new"}


async def test_citation_validation_failure_propagates() -> None:
    # Confirm that bad shapes coming from the LLM (e.g., missing
    # confidence bounds) surface as ValidationError - they are not
    # transient, so the router would let them through too.
    items = [_item(url="https://v.test/a", title="A", source="V", days_ago=1)]

    class BadLLM:
        name = "bad"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            return response_model.model_validate(
                {
                    "findings": ["x"],
                    "confidence": 1.7,  # out of range
                    "key_metrics": {
                        "sentiment_score": 0.0,
                        "num_items": 1,
                        "dominant_themes": [],
                    },
                    "citations": [],
                }
            )

    with pytest.raises(ValidationError):
        await run("AAPL", items, "swing", BadLLM())


async def test_citations_round_trip_through_analyst_output() -> None:
    items = [_item(url="https://r.test/a", title="A", source="R", days_ago=1)]

    class LLM:
        name = "ok"

        async def complete_structured(
            self,
            messages: list[Message],
            response_model: type[BaseModel],
            *,
            cache_blocks: list[str] | None = None,
            max_retries: int = 1,
        ) -> BaseModel:
            return _canned_response(response_model, citation_urls=["https://r.test/a"])

    out = await run("AAPL", items, "swing", LLM())
    [c] = out.citations
    assert isinstance(c, Citation)
    # JSON roundtrip - schema_roundtrip equivalence as a sanity check.
    payload = json.loads(out.model_dump_json())
    assert payload["citations"][0]["url"] == "https://r.test/a"

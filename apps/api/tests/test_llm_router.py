"""Router fallback policy tests.

Uses fake providers that raise our framework-level errors so we can
verify the chain falls through on 429/5xx and propagates everything
else immediately.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.llm.provider import LLMProvider, Message, RateLimitError, ServerError
from app.llm.router import LLMRouter, NoProviderAvailableError


class Sample(BaseModel):
    name: str
    score: int
    note: str


class FakeProvider:
    """Test double for LLMProvider.

    ``behavior`` is either a ready :class:`Sample` to return or an
    exception instance to raise. ``calls`` tracks invocations so
    tests can assert the router stopped at the right provider.
    """

    def __init__(self, name: str, behavior: Sample | Exception) -> None:
        self.name = name
        self.behavior = behavior
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
                "cache_blocks": cache_blocks,
                "max_retries": max_retries,
            }
        )
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


def _msg() -> list[Message]:
    return [{"role": "user", "content": "hi"}]


def test_fake_provider_satisfies_protocol() -> None:
    p = FakeProvider("x", Sample(name="a", score=1, note="b"))
    assert isinstance(p, LLMProvider)


async def test_primary_answers_no_fallback() -> None:
    expected = Sample(name="primary", score=1, note="ok")
    primary = FakeProvider("primary", expected)
    fallback = FakeProvider("fallback", Sample(name="should_not_run", score=0, note="x"))
    router = LLMRouter(primary, [fallback])

    result = await router.complete_structured(_msg(), Sample)

    assert result == expected
    assert router.last_used == "primary"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 0


async def test_falls_through_on_rate_limit() -> None:
    expected = Sample(name="fallback", score=2, note="fb")
    primary = FakeProvider("primary", RateLimitError("429"))
    fallback = FakeProvider("fallback", expected)
    router = LLMRouter(primary, [fallback])

    result = await router.complete_structured(_msg(), Sample)

    assert result == expected
    assert router.last_used == "fallback"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


async def test_falls_through_on_server_error() -> None:
    expected = Sample(name="fb", score=3, note="x")
    primary = FakeProvider("primary", ServerError("503"))
    fallback = FakeProvider("fallback", expected)
    router = LLMRouter(primary, [fallback])

    result = await router.complete_structured(_msg(), Sample)

    assert result == expected
    assert router.last_used == "fallback"


async def test_chains_through_multiple_failures() -> None:
    expected = Sample(name="third", score=9, note="finally")
    p1 = FakeProvider("p1", RateLimitError("429"))
    p2 = FakeProvider("p2", ServerError("500"))
    p3 = FakeProvider("p3", expected)
    router = LLMRouter(p1, [p2, p3])

    result = await router.complete_structured(_msg(), Sample)

    assert result == expected
    assert router.last_used == "p3"
    assert len(p1.calls) == len(p2.calls) == len(p3.calls) == 1


async def test_raises_when_all_providers_fail() -> None:
    p1 = FakeProvider("p1", RateLimitError("429"))
    p2 = FakeProvider("p2", ServerError("500"))
    router = LLMRouter(p1, [p2])

    with pytest.raises(NoProviderAvailableError):
        await router.complete_structured(_msg(), Sample)

    assert router.last_used is None


async def test_non_transient_error_propagates_without_fallback() -> None:
    """Validation/auth failures shouldn't burn through fallback providers."""
    primary = FakeProvider("primary", ValueError("schema mismatch"))
    fallback = FakeProvider("fallback", Sample(name="x", score=1, note="y"))
    router = LLMRouter(primary, [fallback])

    with pytest.raises(ValueError, match="schema mismatch"):
        await router.complete_structured(_msg(), Sample)

    assert len(primary.calls) == 1
    assert len(fallback.calls) == 0


async def test_router_forwards_cache_blocks_and_retries() -> None:
    primary = FakeProvider("primary", Sample(name="ok", score=1, note="n"))
    router = LLMRouter(primary)

    await router.complete_structured(
        _msg(),
        Sample,
        cache_blocks=["block-a", "block-b"],
        max_retries=3,
    )

    assert primary.calls[0]["cache_blocks"] == ["block-a", "block-b"]
    assert primary.calls[0]["max_retries"] == 3

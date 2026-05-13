"""Anthropic Claude provider.

Wraps the async Anthropic SDK with ``instructor`` so callers can
request a pydantic ``response_model`` and get back a validated
instance. Each entry in ``cache_blocks`` becomes a separate system
block tagged with ``cache_control: ephemeral`` — Anthropic caches the
longest matching prefix, so re-using the same blocks across calls
hits the cache.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic
import instructor
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.llm.provider import Message, RateLimitError, ServerError

DEFAULT_ANALYST_MODEL = "claude-sonnet-4-6"
DEFAULT_SYNTH_MODEL = "claude-opus-4-7"


class ClaudeProvider:
    """LLMProvider implementation backed by Anthropic's API."""

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str = DEFAULT_ANALYST_MODEL,
        max_tokens: int = 4096,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self._client = instructor.from_anthropic(AsyncAnthropic(api_key=api_key))

    async def complete_structured(
        self,
        messages: list[Message],
        response_model: type[BaseModel],
        *,
        cache_blocks: list[str] | None = None,
        max_retries: int = 1,
    ) -> BaseModel:
        system: list[dict[str, Any]] | str = ""
        if cache_blocks:
            system = [
                {"type": "text", "text": block, "cache_control": {"type": "ephemeral"}}
                for block in cache_blocks
            ]

        try:
            result: BaseModel = await self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=cast(Any, list(messages)),
                response_model=response_model,
                max_retries=max_retries,
            )
        except anthropic.RateLimitError as e:
            raise RateLimitError(f"anthropic rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise ServerError(f"anthropic {e.status_code}: {e}") from e
            raise
        return result

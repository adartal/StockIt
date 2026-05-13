"""LLM provider Protocol + shared error types.

All concrete providers raise :class:`RateLimitError` on 429s and
:class:`ServerError` on 5xx so the router can apply a uniform
fallback policy without importing vendor SDK exception types.
"""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable

from pydantic import BaseModel


class Message(TypedDict):
    """A single chat-style turn. Role is "user" or "assistant"."""

    role: str
    content: str


class LLMError(Exception):
    """Base class for provider-level failures surfaced to the router."""


class RateLimitError(LLMError):
    """Raised on HTTP 429 from the upstream provider."""


class ServerError(LLMError):
    """Raised on HTTP 5xx from the upstream provider."""


@runtime_checkable
class LLMProvider(Protocol):
    """Abstract LLM provider returning a validated pydantic model.

    Implementations use the ``instructor`` library to coerce the model
    response into ``response_model`` and to retry on validation
    failure up to ``max_retries`` additional attempts.

    ``cache_blocks`` is a list of system-prompt fragments. Providers
    that support prompt caching (Anthropic) attach ``cache_control``
    metadata to each block; others concatenate them into a single
    system message.
    """

    name: str

    async def complete_structured(
        self,
        messages: list[Message],
        response_model: type[BaseModel],
        *,
        cache_blocks: list[str] | None = None,
        max_retries: int = 1,
    ) -> BaseModel: ...

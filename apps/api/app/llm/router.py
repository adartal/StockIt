"""Fallback router across a primary + ordered fallback providers.

Each call tries the primary first. On a :class:`RateLimitError` or
:class:`ServerError`, it falls through to the next provider. Any
other exception (validation failure after instructor retries, auth
error, bad request, etc.) propagates immediately — those are not
transient and shouldn't waste fallback budget.

The provider that produced the result is logged at INFO level and
exposed on ``LLMRouter.last_used`` for tests and observability.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel

from app.llm.provider import LLMProvider, Message, RateLimitError, ServerError

logger = logging.getLogger(__name__)


class NoProviderAvailableError(RuntimeError):
    """Raised when every provider in the chain returned a transient error."""


class LLMRouter:
    """Routes a structured-completion call through primary → fallbacks."""

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: Sequence[LLMProvider] = (),
    ) -> None:
        self._chain: tuple[LLMProvider, ...] = (primary, *fallbacks)
        self.last_used: str | None = None

    @property
    def providers(self) -> tuple[LLMProvider, ...]:
        return self._chain

    async def complete_structured(
        self,
        messages: list[Message],
        response_model: type[BaseModel],
        *,
        cache_blocks: list[str] | None = None,
        max_retries: int = 1,
    ) -> BaseModel:
        last_err: Exception | None = None
        for provider in self._chain:
            try:
                result = await provider.complete_structured(
                    messages,
                    response_model,
                    cache_blocks=cache_blocks,
                    max_retries=max_retries,
                )
            except (RateLimitError, ServerError) as e:
                logger.warning(
                    "llm provider %r failed transiently (%s); falling through",
                    provider.name,
                    e,
                )
                last_err = e
                continue
            self.last_used = provider.name
            logger.info("llm provider %r answered", provider.name)
            return result

        raise NoProviderAvailableError(
            f"all {len(self._chain)} providers exhausted; last error: {last_err}"
        ) from last_err

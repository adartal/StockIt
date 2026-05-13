"""OpenAI provider.

OpenAI applies prompt caching automatically on prompts >= 1024 tokens
when prefixes match across requests, so ``cache_blocks`` is simply
concatenated into a leading system message — no per-block metadata
required.
"""

from __future__ import annotations

from typing import Any, cast

import instructor
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.llm.provider import Message, RateLimitError, ServerError

DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider:
    """LLMProvider implementation backed by OpenAI's chat completions API."""

    name = "openai"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self._client = instructor.from_openai(AsyncOpenAI(api_key=api_key))

    async def complete_structured(
        self,
        messages: list[Message],
        response_model: type[BaseModel],
        *,
        cache_blocks: list[str] | None = None,
        max_retries: int = 1,
    ) -> BaseModel:
        chat_messages: list[Message] = []
        if cache_blocks:
            chat_messages.append({"role": "system", "content": "\n\n".join(cache_blocks)})
        chat_messages.extend(messages)

        try:
            result: BaseModel = await self._client.chat.completions.create(
                model=self.model,
                messages=cast(Any, chat_messages),
                response_model=response_model,
                max_retries=max_retries,
            )
        except openai.RateLimitError as e:
            raise RateLimitError(f"openai rate limited: {e}") from e
        except openai.APIStatusError as e:
            if e.status_code is not None and e.status_code >= 500:
                raise ServerError(f"openai {e.status_code}: {e}") from e
            raise
        return result

"""Google Gemini provider.

Uses ``google-genai`` via instructor's ``from_genai`` bridge.
``cache_blocks`` are concatenated into a system message; explicit
context caching on Gemini requires a separate cached-content lifecycle
which is out of scope for the v1 abstraction.
"""

from __future__ import annotations

import instructor
from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel

from app.llm.provider import Message, RateLimitError, ServerError

DEFAULT_MODEL = "gemini-2.5-pro"


class GeminiProvider:
    """LLMProvider implementation backed by Google's Gemini API."""

    name = "gemini"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self._client = instructor.from_genai(
            genai.Client(api_key=api_key),
            use_async=True,
        )

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
                messages=chat_messages,
                response_model=response_model,
                max_retries=max_retries,
            )
        except genai_errors.APIError as e:
            code = getattr(e, "code", None)
            if code == 429:
                raise RateLimitError(f"gemini rate limited: {e}") from e
            if isinstance(code, int) and code >= 500:
                raise ServerError(f"gemini {code}: {e}") from e
            raise
        return result

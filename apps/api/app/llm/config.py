"""LLM provider config: instantiate only providers whose key is present.

Reads ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``GEMINI_API_KEY``
from the environment. :func:`default_router` returns a router with
Claude as primary and OpenAI/Gemini as ordered fallbacks (whichever
are configured).
"""

from __future__ import annotations

import os

from app.llm.claude import ClaudeProvider
from app.llm.gemini import GeminiProvider
from app.llm.openai import OpenAIProvider
from app.llm.provider import LLMProvider
from app.llm.router import LLMRouter

ANTHROPIC_ENV = "ANTHROPIC_API_KEY"
OPENAI_ENV = "OPENAI_API_KEY"
GEMINI_ENV = "GEMINI_API_KEY"


def build_providers(
    *,
    anthropic_model: str | None = None,
    openai_model: str | None = None,
    gemini_model: str | None = None,
) -> dict[str, LLMProvider]:
    """Return a dict of provider-name → instance for every configured key."""
    providers: dict[str, LLMProvider] = {}
    if os.getenv(ANTHROPIC_ENV):
        providers["anthropic"] = (
            ClaudeProvider(model=anthropic_model) if anthropic_model else ClaudeProvider()
        )
    if os.getenv(OPENAI_ENV):
        providers["openai"] = (
            OpenAIProvider(model=openai_model) if openai_model else OpenAIProvider()
        )
    if os.getenv(GEMINI_ENV):
        providers["gemini"] = (
            GeminiProvider(model=gemini_model) if gemini_model else GeminiProvider()
        )
    return providers


def default_router(
    *,
    anthropic_model: str | None = None,
    openai_model: str | None = None,
    gemini_model: str | None = None,
) -> LLMRouter:
    """Build a router with Claude primary, OpenAI/Gemini as fallbacks.

    Raises ``RuntimeError`` if no provider keys are configured.
    """
    providers = build_providers(
        anthropic_model=anthropic_model,
        openai_model=openai_model,
        gemini_model=gemini_model,
    )
    if not providers:
        raise RuntimeError(
            "no LLM provider keys configured; "
            f"set one of {ANTHROPIC_ENV}, {OPENAI_ENV}, {GEMINI_ENV}"
        )

    ordered = [providers[name] for name in ("anthropic", "openai", "gemini") if name in providers]
    return LLMRouter(primary=ordered[0], fallbacks=ordered[1:])

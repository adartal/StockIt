"""LLM provider abstraction (M3).

Exports a provider Protocol, three concrete implementations
(Anthropic Claude, OpenAI, Google Gemini), a fallback router, and a
config helper that wires up only those providers whose API keys are
present in the environment.
"""

from app.llm.claude import ClaudeProvider
from app.llm.config import build_providers, default_router
from app.llm.gemini import GeminiProvider
from app.llm.openai import OpenAIProvider
from app.llm.provider import (
    LLMError,
    LLMProvider,
    Message,
    RateLimitError,
    ServerError,
)
from app.llm.router import LLMRouter, NoProviderAvailableError

__all__ = [
    "ClaudeProvider",
    "GeminiProvider",
    "LLMError",
    "LLMProvider",
    "LLMRouter",
    "Message",
    "NoProviderAvailableError",
    "OpenAIProvider",
    "RateLimitError",
    "ServerError",
    "build_providers",
    "default_router",
]

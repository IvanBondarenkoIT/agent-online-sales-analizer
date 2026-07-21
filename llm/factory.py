"""Factory for LLM client instances."""

from __future__ import annotations

from config import Settings
from llm.base import LLMClient
from llm.cursor_provider import CursorProvider
from llm.mock_provider import MockProvider
from llm.openrouter_provider import OpenRouterProvider


def create_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider
    if provider == "cursor":
        return CursorProvider(settings)
    if provider == "openrouter":
        return OpenRouterProvider(settings)
    if provider == "mock":
        return MockProvider()
    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider!r}. "
        "Use 'cursor', 'openrouter', or 'mock'."
    )

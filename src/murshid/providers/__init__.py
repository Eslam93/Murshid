"""LLM provider abstraction (§0.5).

5 provider classes (Mock + Claude + OpenAI + Gemini + Falcon-Arabic) with
model-ID flag-toggling per vendor. Default selection is whichever wins the
mini-bench; set via `LLM_PROVIDER` env var.
"""

from murshid.providers.base import LLMProvider, ProviderResponse
from murshid.providers.claude import ClaudeProvider
from murshid.providers.gemini import GeminiProvider
from murshid.providers.mock import MockProvider
from murshid.providers.openai import OpenAIProvider

__all__ = [
    "LLMProvider",
    "ProviderResponse",
    "MockProvider",
    "ClaudeProvider",
    "OpenAIProvider",
    "GeminiProvider",
]

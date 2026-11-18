"""LLM provider abstraction (§0.5).

Zero-key providers: Extractive (the default: quotes the retrieved passages), Replay (recorded
real-model answers to the bench questions), Mock (a test double). Paid providers: Claude, OpenAI,
Gemini, each on its vendor's SDK, imported only when a call is made.

`factory.py` is the one registry: provider kinds, default model ids, prices, and
`build_provider` / `available_kinds`. The settings choose the provider with `LLM_PROVIDER`.
"""

from murshid.providers.base import FinishReason, LLMProvider, ProviderResponse
from murshid.providers.claude import ClaudeProvider
from murshid.providers.extractive import ExtractiveProvider
from murshid.providers.factory import (
    PROVIDER_KINDS,
    ProviderKind,
    available_kinds,
    build_provider,
)
from murshid.providers.gemini import GeminiProvider
from murshid.providers.mock import MockProvider
from murshid.providers.openai import OpenAIProvider
from murshid.providers.replay import ReplayProvider

__all__ = [
    "PROVIDER_KINDS",
    "ClaudeProvider",
    "ExtractiveProvider",
    "FinishReason",
    "GeminiProvider",
    "LLMProvider",
    "MockProvider",
    "OpenAIProvider",
    "ProviderKind",
    "ProviderResponse",
    "ReplayProvider",
    "available_kinds",
    "build_provider",
]

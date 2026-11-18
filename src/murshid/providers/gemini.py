"""GeminiProvider: the Gemini Developer API through the `google-genai` SDK.

The model id and API key come from the provider registry (`murshid.providers.factory`), which
reads them from the settings (`GEMINI_MODEL_ID`, `GEMINI_API_KEY`). Gemini Flash is also the
bench's default judge, out of family for the Claude and OpenAI answers it scores.

The SDK client is built once per provider, on the first call, so importing this module never
imports the SDK. Its retries are off (`HttpRetryOptions(attempts=1)`): `retry_call` is the only
retry layer. Each call passes its own timeout, which the SDK takes in milliseconds.

Gemini 2.5 models count thinking tokens against the output budget, so a call with no cap can
spend all of `max_tokens` thinking and return no text. For the models the registry lists in
`GEMINI_THINKING_BUDGET_LIMITS`, thinking is capped at half the output budget. Truncation still
shows: the finish reason is the candidate's real one (`length` for MAX_TOKENS), not a constant.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from murshid.providers.base import FinishReason, ProviderResponse, retry_call
from murshid.providers.factory import (
    DEFAULT_MODEL_IDS,
    GEMINI_THINKING_BUDGET_LIMITS,
    price_for,
    sdk_installed,
)

if TYPE_CHECKING:
    # The SDK is an optional extra, so it is imported for real only when a call is made.
    import httpx
    from google import genai
    from google.genai import types

# Gemini `FinishReason` names -> the normalised finish reason. Anything not listed is `other`.
_FINISH_REASONS: dict[str, FinishReason] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "BLOCKLIST": "content_filter",
    "PROHIBITED_CONTENT": "content_filter",
    "SPII": "content_filter",
    "IMAGE_SAFETY": "content_filter",
    "IMAGE_PROHIBITED_CONTENT": "content_filter",
    "IMAGE_RECITATION": "content_filter",
    "MALFORMED_FUNCTION_CALL": "tool",
    "UNEXPECTED_TOOL_CALL": "tool",
    "TOO_MANY_TOOL_CALLS": "tool",
}


def normalise_finish_reason(finish_reason: str | None, *, blocked: bool = False) -> FinishReason:
    """A Gemini finish reason as one of the five shared ones; a blocked prompt is filtered."""
    if finish_reason is None and blocked:
        return "content_filter"
    return _FINISH_REASONS.get(finish_reason or "", "other")


def thinking_budget(model_id: str, max_tokens: int) -> int | None:
    """Half the output budget, within the model's limits; None for a model left at its default."""
    limits = GEMINI_THINKING_BUDGET_LIMITS.get(model_id)
    if limits is None:
        return None
    low, high = limits
    return max(low, min(high, max_tokens // 2))


def _name(value: object) -> str | None:
    """An SDK enum member's value, a plain string as it is, None for None."""
    if value is None:
        return None
    return str(getattr(value, "value", value))


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        model_id: str | None = None,
        *,
        api_key: str = "",
        http_client: httpx.Client | None = None,
    ) -> None:
        """`http_client` replaces the SDK's own HTTP client (tests pass a fake transport)."""
        self.model_id = (model_id or DEFAULT_MODEL_IDS["gemini"]).strip()
        self._api_key = api_key.strip()
        self._http_client = http_client
        self._client: genai.Client | None = None
        self._client_lock = threading.Lock()

    def is_available(self) -> bool:
        return bool(self._api_key) and sdk_installed("gemini")

    def _sdk_client(self) -> genai.Client:
        """The provider's one SDK client, built on first use."""
        with self._client_lock:
            if self._client is None:
                from google import genai
                from google.genai import types

                self._client = genai.Client(
                    api_key=self._api_key,
                    vertexai=False,
                    http_options=types.HttpOptions(
                        retry_options=types.HttpRetryOptions(attempts=1),
                        httpx_client=self._http_client,
                    ),
                )
            return self._client

    def _config(self, system: str, max_tokens: int, timeout: float) -> types.GenerateContentConfig:
        from google.genai import types

        budget = thinking_budget(self.model_id, max_tokens)
        return types.GenerateContentConfig(
            # Gemini system instructions are request config, not a message.
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=0.0,
            thinking_config=(
                types.ThinkingConfig(thinking_budget=budget) if budget is not None else None
            ),
            http_options=types.HttpOptions(timeout=round(timeout * 1000)),
        )

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> ProviderResponse:
        client = self._sdk_client()
        config = self._config(system, max_tokens, timeout)
        start = time.perf_counter()
        resp = retry_call(
            client.models.generate_content,
            model=self.model_id,
            contents=user,
            config=config,
        )
        elapsed = time.perf_counter() - start

        candidate = resp.candidates[0] if resp.candidates else None
        raw_reason = _name(candidate.finish_reason) if candidate is not None else None
        block_reason = _name(resp.prompt_feedback.block_reason) if resp.prompt_feedback else None
        usage = resp.usage_metadata
        prompt_tokens = (usage.prompt_token_count or 0) if usage else 0
        answer_tokens = (usage.candidates_token_count or 0) if usage else 0
        # Thinking tokens are billed as output, as OpenAI's reasoning tokens are.
        thought_tokens = (usage.thoughts_token_count or 0) if usage else 0
        return ProviderResponse(
            text=resp.text or "",
            input_tokens=prompt_tokens,
            output_tokens=answer_tokens + thought_tokens,
            latency_s=elapsed,
            finish_reason=normalise_finish_reason(raw_reason, blocked=block_reason is not None),
            raw={
                "id": resp.response_id,
                "model": resp.model_version or self.model_id,
                "finish_reason": raw_reason,
                "block_reason": block_reason,
                "thoughts_tokens": thought_tokens,
            },
        )

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return price_for("gemini", self.model_id).cost_usd(
            response.input_tokens, response.output_tokens
        )

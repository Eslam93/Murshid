"""OpenAIProvider: OpenAI's Chat Completions API.

The model id and API key come from the provider registry (`murshid.providers.factory`), which
reads them from the settings (`OPENAI_MODEL_ID`, `OPENAI_API_KEY`).

The SDK client is built once per provider, on the first call, so importing this module never
imports the SDK. It is built with `max_retries=0`: `retry_call` is the only retry layer, so the
SDK's own retries never multiply it. Each call passes its own timeout.

GPT-5.x note: the chat completions endpoint for the GPT-5 family REQUIRES
`max_completion_tokens` rather than the legacy `max_tokens` parameter
(verified 2026-05-22; sending `max_tokens` returns a 400
"Unsupported parameter" error).
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, cast

from murshid.providers.base import FinishReason, ProviderResponse, retry_call
from murshid.providers.factory import DEFAULT_MODEL_IDS, price_for, sdk_installed

if TYPE_CHECKING:
    # The SDK is an optional extra, so it is imported for real only when a call is made.
    import httpx2
    from openai import OpenAI
    from openai.types import CompletionUsage

# OpenAI `finish_reason` -> the normalised finish reason.
_FINISH_REASONS: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "content_filter": "content_filter",
    "tool_calls": "tool",
    "function_call": "tool",
}


def normalise_finish_reason(finish_reason: str | None) -> FinishReason:
    """OpenAI's `finish_reason` as one of the five shared finish reasons."""
    return _FINISH_REASONS.get(finish_reason or "", "other")


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        model_id: str | None = None,
        *,
        api_key: str = "",
        http_client: httpx2.Client | None = None,
    ) -> None:
        """`http_client` replaces the SDK's own HTTP client (tests pass a fake transport)."""
        self.model_id = (model_id or DEFAULT_MODEL_IDS["openai"]).strip()
        self._api_key = api_key.strip()
        self._http_client = http_client
        self._client: OpenAI | None = None
        self._client_lock = threading.Lock()

    def is_available(self) -> bool:
        return bool(self._api_key) and sdk_installed("openai")

    def _sdk_client(self) -> OpenAI:
        """The provider's one SDK client, built on first use."""
        with self._client_lock:
            if self._client is None:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key=self._api_key,
                    max_retries=0,
                    http_client=self._http_client,
                )
            return self._client

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> ProviderResponse:
        client = self._sdk_client()
        start = time.perf_counter()
        resp = retry_call(
            client.chat.completions.create,
            model=self.model_id,
            # GPT-5.x family uses max_completion_tokens; rejects legacy max_tokens.
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start

        choice = resp.choices[0]
        text = choice.message.content or ""
        # A completion that is not streamed always reports usage; the SDK types the field
        # optional for the sake of streamed chunks. The cast only tells mypy so: a reply without
        # usage still fails on the attribute access below.
        usage = cast("CompletionUsage", resp.usage)
        return ProviderResponse(
            text=text,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_s=elapsed,
            finish_reason=normalise_finish_reason(choice.finish_reason),
            raw={"id": resp.id, "model": resp.model, "finish_reason": choice.finish_reason},
        )

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return price_for("openai", self.model_id).cost_usd(
            response.input_tokens, response.output_tokens
        )

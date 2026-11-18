# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""ClaudeProvider: Anthropic's Messages API.

The model id and API key come from the provider registry (`murshid.providers.factory`), which
reads them from the settings (`ANTHROPIC_MODEL_ID`, `ANTHROPIC_API_KEY`).

The SDK client is built once per provider, on the first call, so importing this module never
imports the SDK. It is built with `max_retries=0`: `retry_call` is the only retry layer, so the
SDK's own retries never multiply it. Each call passes its own timeout.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from murshid.providers.base import FinishReason, ProviderResponse, retry_call
from murshid.providers.factory import DEFAULT_MODEL_IDS, price_for, sdk_installed

if TYPE_CHECKING:
    # The SDK is an optional extra, so it is imported for real only when a call is made.
    import anthropic
    import httpx2

# Anthropic `stop_reason` -> the normalised finish reason.
_FINISH_REASONS: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "refusal": "content_filter",
    "tool_use": "tool",
    "pause_turn": "other",
}


def normalise_finish_reason(stop_reason: str | None) -> FinishReason:
    """Anthropic's `stop_reason` as one of the five shared finish reasons."""
    return _FINISH_REASONS.get(stop_reason or "", "other")


class ClaudeProvider:
    name = "claude"

    def __init__(
        self,
        model_id: str | None = None,
        *,
        api_key: str = "",
        http_client: httpx2.Client | None = None,
    ) -> None:
        """`http_client` replaces the SDK's own HTTP client (tests pass a fake transport)."""
        self.model_id = (model_id or DEFAULT_MODEL_IDS["claude"]).strip()
        self._api_key = api_key.strip()
        self._http_client = http_client
        self._client: anthropic.Anthropic | None = None
        self._client_lock = threading.Lock()

    def is_available(self) -> bool:
        return bool(self._api_key) and sdk_installed("claude")

    def _sdk_client(self) -> anthropic.Anthropic:
        """The provider's one SDK client, built on first use."""
        with self._client_lock:
            if self._client is None:
                import anthropic

                self._client = anthropic.Anthropic(
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
            client.messages.create,
            model=self.model_id,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start

        text = "".join(block.text for block in resp.content if block.type == "text")
        return ProviderResponse(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_s=elapsed,
            finish_reason=normalise_finish_reason(resp.stop_reason),
            raw={"id": resp.id, "model": resp.model, "finish_reason": resp.stop_reason},
        )

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return price_for("claude", self.model_id).cost_usd(
            response.input_tokens, response.output_tokens
        )

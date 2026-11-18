"""ClaudeProvider: Anthropic's Messages API.

Default: `claude-sonnet-4-6`, overridable with `ANTHROPIC_MODEL_ID`; the API key is
`ANTHROPIC_API_KEY`. Both are read from the environment when they are not passed in.

The SDK client is built once per provider, on the first call, so importing this module never
imports the SDK. It is built with `max_retries=0`: `retry_call` is the only retry layer, so the
SDK's own retries never multiply it. Each call passes its own timeout.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from typing import TYPE_CHECKING

from murshid.providers.base import FinishReason, ProviderResponse, retry_call

if TYPE_CHECKING:
    # The SDK is an optional extra, so it is imported for real only when a call is made.
    import anthropic
    import httpx2

# Per Anthropic models docs (2026-05-22). USD per 1M tokens.
_CLAUDE_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
_CLAUDE_PRICING_FALLBACK = (3.00, 15.00)  # treat unknown IDs like Sonnet

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
        api_key: str | None = None,
        http_client: httpx2.Client | None = None,
    ) -> None:
        """`http_client` replaces the SDK's own HTTP client (tests pass a fake transport)."""
        self.model_id = (
            model_id or os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
        ).strip()
        self._api_key = (
            api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        ).strip()
        self._http_client = http_client
        self._client: anthropic.Anthropic | None = None
        self._client_lock = threading.Lock()

    def is_available(self) -> bool:
        return bool(self._api_key) and importlib.util.find_spec("anthropic") is not None

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
        in_per_mtok, out_per_mtok = _CLAUDE_PRICING.get(self.model_id, _CLAUDE_PRICING_FALLBACK)
        return (
            response.input_tokens * in_per_mtok + response.output_tokens * out_per_mtok
        ) / 1_000_000

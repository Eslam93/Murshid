"""ClaudeProvider (§0.5).

Default: `claude-sonnet-4-6`. Alternate (held for judge sanity swap, NOT in
default bench rotation): `claude-opus-4-7`. Model ID overridable via
`ANTHROPIC_MODEL_ID` env var.

API key: `ANTHROPIC_API_KEY`. The SDK reads it from env automatically; this
class also surfaces `is_available()` for graceful skipping in the bench when
the key isn't set.
"""

from __future__ import annotations

import os
import time

from murshid.providers.base import ProviderResponse, retry_call


# Per Anthropic models docs (2026-05-22). USD per 1M tokens.
_CLAUDE_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7":              (5.00, 25.00),
    "claude-opus-4-6":              (5.00, 25.00),
    "claude-sonnet-4-6":            (3.00, 15.00),
    "claude-sonnet-4-5-20250929":   (3.00, 15.00),
    "claude-haiku-4-5-20251001":    (1.00,  5.00),
    "claude-haiku-4-5":             (1.00,  5.00),
}
_CLAUDE_PRICING_FALLBACK = (3.00, 15.00)  # treat unknown IDs like Sonnet


class ClaudeProvider:
    name = "claude"

    def __init__(self, model_id: str | None = None, api_key: str | None = None):
        self.model_id = (model_id or os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")).strip()
        self._api_key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        self._client = None  # lazy

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            import anthropic  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False

    def _client_for(self, timeout: float):
        """Build a per-call client with the requested timeout."""
        import anthropic  # noqa: PLC0415
        return anthropic.Anthropic(api_key=self._api_key, timeout=timeout)

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> ProviderResponse:
        client = self._client_for(timeout)
        start = time.perf_counter()
        resp = retry_call(
            client.messages.create,
            model=self.model_id,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        elapsed = time.perf_counter() - start

        text = "".join(block.text for block in resp.content if hasattr(block, "text"))
        return ProviderResponse(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_s=elapsed,
            finish_reason=resp.stop_reason or "stop",
            raw={"id": resp.id, "model": resp.model},
        )

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        in_per_mtok, out_per_mtok = _CLAUDE_PRICING.get(self.model_id, _CLAUDE_PRICING_FALLBACK)
        return (response.input_tokens * in_per_mtok + response.output_tokens * out_per_mtok) / 1_000_000

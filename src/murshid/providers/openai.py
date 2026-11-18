"""OpenAIProvider (§0.5).

Default: `gpt-5.5-2026-04-23`. Alternate (cost/quality datapoint):
`gpt-5.4-mini-2026-03-17`. Model ID overridable via `OPENAI_MODEL_ID`.

API key: `OPENAI_API_KEY`. The SDK reads it from env automatically.

GPT-5.x note: the chat completions endpoint for the GPT-5 family REQUIRES
`max_completion_tokens` rather than the legacy `max_tokens` parameter
(verified 2026-05-22; sending `max_tokens` returns a 400
"Unsupported parameter" error).
"""

from __future__ import annotations

import os
import time

from murshid.providers.base import ProviderResponse, retry_call


# Approximate USD per 1M tokens. Pricing for GPT-5.x is not fully published
# in the same shape as Anthropic's table; these estimates are conservative
# (treat as upper bounds for cost-log purposes).
_OPENAI_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.5-2026-04-23":       (5.00, 15.00),
    "gpt-5.4-mini-2026-03-17":  (1.00,  3.00),
    "gpt-4.1":                  (2.00,  8.00),
    "gpt-4o":                   (2.50, 10.00),
}
_OPENAI_PRICING_FALLBACK = (5.00, 15.00)


class OpenAIProvider:
    name = "openai"

    def __init__(self, model_id: str | None = None, api_key: str | None = None):
        self.model_id = (model_id or os.environ.get("OPENAI_MODEL_ID", "gpt-5.5-2026-04-23")).strip()
        self._api_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            import openai  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False

    def _client_for(self, timeout: float):
        from openai import OpenAI  # noqa: PLC0415
        return OpenAI(api_key=self._api_key, timeout=timeout)

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
            client.chat.completions.create,
            model=self.model_id,
            # GPT-5.x family uses max_completion_tokens; rejects legacy max_tokens.
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        elapsed = time.perf_counter() - start

        choice = resp.choices[0]
        text = choice.message.content or ""
        usage = resp.usage
        return ProviderResponse(
            text=text,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_s=elapsed,
            finish_reason=(choice.finish_reason or "stop"),
            raw={"id": resp.id, "model": resp.model},
        )

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        in_per_mtok, out_per_mtok = _OPENAI_PRICING.get(self.model_id, _OPENAI_PRICING_FALLBACK)
        return (response.input_tokens * in_per_mtok + response.output_tokens * out_per_mtok) / 1_000_000

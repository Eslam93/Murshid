"""GeminiProvider (§0.5).

Default: `gemini-3.1-pro-preview`. Alternate: `gemini-3-flash-preview`. The
default serves a dual role: a bench provider AND the bench judge (out-of-family
for Claude / OpenAI, used to reduce self-preference bias per ADR 2).

API key: `GEMINI_API_KEY` (or `GOOGLE_API_KEY`). The SDK is the legacy
`google-generativeai` package — the new `google-genai` package will be a
Phase-5+ swap.

Note: `gemini-3-pro-preview` was deprecated and shut down 2026-03-09 — do not
target it. Use `gemini-3.1-pro-preview` for the Pro tier.
"""

from __future__ import annotations

import os
import time

from murshid.providers.base import ProviderResponse, retry_call


# Approximate USD per 1M tokens. Gemini Pro / Flash pricing per Google AI
# pricing docs (estimates as of 2026-05-22; verify on the AI Studio pricing
# page before relying on these for accounting).
_GEMINI_PRICING: dict[str, tuple[float, float]] = {
    "gemini-3.1-pro-preview":   (2.50, 10.00),
    "gemini-3-flash-preview":   (0.30,  2.50),
    "gemini-2.5-pro":           (1.25,  5.00),
    "gemini-2.5-flash":         (0.075, 0.30),
    "gemini-2.5-flash-lite":    (0.05,  0.20),
}
_GEMINI_PRICING_FALLBACK = (2.50, 10.00)


class GeminiProvider:
    name = "gemini"

    def __init__(self, model_id: str | None = None, api_key: str | None = None):
        self.model_id = (
            model_id
            or os.environ.get("GEMINI_MODEL_ID", "gemini-3.1-pro-preview")
        ).strip()
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY", "")
            or os.environ.get("GOOGLE_API_KEY", "")
        ).strip()

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            import google.generativeai  # noqa: F401, PLC0415
            return True
        except ImportError:
            return False

    def _configure(self) -> None:
        import google.generativeai as genai  # noqa: PLC0415
        genai.configure(api_key=self._api_key)

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> ProviderResponse:
        import google.generativeai as genai  # noqa: PLC0415

        self._configure()
        # Gemini system instructions are model-level config, not message-level.
        model = genai.GenerativeModel(self.model_id, system_instruction=system)
        start = time.perf_counter()
        resp = retry_call(
            model.generate_content,
            user,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": 0.0,
            },
            request_options={"timeout": timeout},
        )
        elapsed = time.perf_counter() - start

        # `.text` is the convenience accessor; for safety, fall back to
        # candidates if the response was blocked / empty.
        try:
            text = resp.text or ""
        except (ValueError, AttributeError):
            text = ""

        usage = getattr(resp, "usage_metadata", None)
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0

        return ProviderResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=elapsed,
            finish_reason="stop",  # google-generativeai doesn't surface a clean enum
            raw={"model": self.model_id},
        )

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        in_per_mtok, out_per_mtok = _GEMINI_PRICING.get(self.model_id, _GEMINI_PRICING_FALLBACK)
        return (response.input_tokens * in_per_mtok + response.output_tokens * out_per_mtok) / 1_000_000

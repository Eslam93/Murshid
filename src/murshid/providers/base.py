"""LLMProvider protocol + ProviderResponse (§0.5).

Common interface across the 5 providers (Mock, Claude, OpenAI, Gemini,
FalconArabic). Phase 1 only requires Mock; the others are stubs until
Phase 3+.

Phase 4 reviewer fix #6: `retry_call` adds 2-retry exponential backoff on
known-transient API/network errors (APIConnectionError, RateLimitError,
ResourceExhausted, etc.) so transient SDK errors don't bleed into
behavior-match failures in the bench. Non-transient errors propagate
immediately.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, TypeVar, runtime_checkable

_log = logging.getLogger("murshid.providers")


@dataclass
class ProviderResponse:
    """Common response envelope across providers."""

    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    finish_reason: str = "stop"
    raw: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """5-provider abstraction (§0.5).

    Each implementation:
      - exposes `name` and `model_id` constants (model_id overridable via env var)
      - implements `generate(system, user, max_tokens, timeout)` -> ProviderResponse
      - implements `is_available()` to fail fast on missing API key / model
      - implements `cost_estimate_usd(response)` for the bench cost-log

    The `timeout` keyword is enforced at the SDK call site in each concrete
    provider (Phase 3 work). MockProvider ignores it. Retry policy is the
    bench runner's responsibility; this interface only exposes single-call
    timeout per §7 of the kickoff.
    """

    name: str
    model_id: str

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ) -> ProviderResponse: ...

    def is_available(self) -> bool: ...

    def cost_estimate_usd(self, response: ProviderResponse) -> float: ...


# ---------------------------------------------------------------------------
# Retry helper (reviewer fix #6)
# ---------------------------------------------------------------------------

# Class names of API/network errors worth retrying across Anthropic / OpenAI /
# Google Gen AI plus stdlib network errors. We match on class NAME rather than
# importing each SDK's exception class so this module stays SDK-agnostic.
#
# Round 2 fix (2.1): `APIError` is NO LONGER in the transient set. Both
# anthropic and openai SDKs subclass `APIError` for `BadRequestError`,
# `AuthenticationError`, etc. — non-transient client errors that should
# propagate immediately. The MRO walk in `_is_transient` would otherwise treat
# them as transient because they inherit from `APIError`. Use the explicit
# non-transient blocklist below to short-circuit before the transient check.
_TRANSIENT_ERROR_NAMES = frozenset({
    # Anthropic + OpenAI share these names — and they're concrete, not bases.
    "APIConnectionError", "APITimeoutError", "RateLimitError",
    "InternalServerError",
    # Google google.api_core.exceptions
    "ResourceExhausted", "ServiceUnavailable", "DeadlineExceeded",
    "GatewayTimeout", "TooManyRequests",
    # stdlib
    "ConnectionError", "TimeoutError",
    "ConnectionResetError", "ConnectionRefusedError",
    "ConnectionAbortedError", "BrokenPipeError",
    # urllib3 + requests transient class names (defensive)
    "ReadTimeoutError", "ConnectionTimeoutError", "ProtocolError",
})

# Class names that MUST NOT be retried — checked before the transient set so
# `BadRequestError(APIError)` etc. don't slip through the MRO walk just because
# their base class is `APIError`.
_NON_TRANSIENT_ERROR_NAMES = frozenset({
    "AuthenticationError",
    "BadRequestError",
    "InvalidRequestError",   # legacy OpenAI name
    "NotFoundError",
    "PermissionDeniedError",
    "UnprocessableEntityError",
    "ConflictError",
})


def _is_transient(exc: BaseException) -> bool:
    """True if `exc` is a known-transient API/network error worth retrying.

    Walks the class MRO so subclasses (`anthropic.APIConnectionError` →
    `anthropic.APIError` → `Exception`) are matched even if only the
    concrete name is in the allowlist. The non-transient blocklist is
    checked FIRST so `BadRequestError(APIError)` doesn't get retried just
    because it inherits from `APIError`.
    """
    for klass in type(exc).__mro__:
        if klass.__name__ in _NON_TRANSIENT_ERROR_NAMES:
            return False
    for klass in type(exc).__mro__:
        if klass.__name__ in _TRANSIENT_ERROR_NAMES:
            return True
    return False


_T = TypeVar("_T")


def retry_call(
    fn: Callable[..., _T],
    *args,
    max_retries: int = 2,
    backoff_base: float = 1.0,
    **kwargs,
) -> _T:
    """Call `fn(*args, **kwargs)`; retry up to `max_retries` times on transient
    errors with exponential backoff (`backoff_base * 2 ** attempt` seconds).

    Non-transient errors propagate immediately on the first failure — we don't
    want to retry on `BadRequestError` / `AuthenticationError` / malformed-input
    cases.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if attempt < max_retries and _is_transient(e):
                wait = backoff_base * (2 ** attempt)
                _log.warning(
                    "provider transient error %s on attempt %d/%d; retrying in %.1fs",
                    type(e).__name__, attempt + 1, max_retries + 1, wait,
                )
                time.sleep(wait)
                last_exc = e
                continue
            raise
    assert last_exc is not None  # unreachable: loop either returns or raises
    raise last_exc

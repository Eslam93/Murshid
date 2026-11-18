"""LLMProvider protocol, ProviderResponse, and the one retry layer every paid provider uses.

`retry_call` retries known-transient API and network errors (connection drops, timeouts, rate
limits, 5xx) twice with exponential backoff, so a transient vendor error does not turn into a
behavior-match failure in the bench. Non-transient errors propagate immediately. It is the only
retry layer: the paid providers build their SDK clients with the SDK's own retries switched off,
so retries never nest.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

_log = logging.getLogger("murshid.providers")

# Why the model stopped, the same five words for every vendor. A provider keeps the vendor's own
# value in `ProviderResponse.raw["finish_reason"]`.
#   stop            the model finished (a natural end or a stop sequence)
#   length          the output budget ran out: the text is truncated
#   content_filter  the vendor's safety system stopped or blocked the output
#   tool            the model stopped to call a tool, or a tool call went wrong
#   other           anything else, including no reason at all
FinishReason = Literal["stop", "length", "content_filter", "tool", "other"]


@dataclass
class ProviderResponse:
    """Common response envelope across providers."""

    text: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    finish_reason: FinishReason = "stop"
    # Free-form provider metadata (response id, served model, the vendor's raw finish reason,
    # ...); its keys vary by provider.
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """What the pipeline, the critic and the bench need from a model provider.

    Each implementation:
      - exposes `name` (the provider kind) and `model_id`
      - implements `generate(system, user, max_tokens, timeout)` -> ProviderResponse, with
        `timeout` enforced per call at the SDK call site (the zero-key providers ignore it)
      - implements `is_available()`: False when a key or the SDK is missing
      - implements `cost_estimate_usd(response)` for the bench cost log
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
# Retry helper
# ---------------------------------------------------------------------------

# Class names of API/network errors worth retrying across Anthropic, OpenAI and Google Gen AI,
# httpx and the standard library. We match on class NAME rather than importing each SDK's
# exception class so this module stays SDK-agnostic.
#
# `APIError` is NOT in the transient set: both anthropic and openai subclass `APIError` for
# `BadRequestError`, `AuthenticationError`, etc. — non-transient client errors that should
# propagate immediately. The non-transient blocklist below is checked first.
_TRANSIENT_ERROR_NAMES = frozenset(
    {
        # Anthropic + OpenAI share these names — and they're concrete, not bases. Anthropic's
        # OverloadedError (529), ServiceUnavailableError (503), GatewayTimeoutError and
        # DeadlineExceededError (504) subclass InternalServerError, so the MRO walk finds them.
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        # Anthropic: 408 Request Timeout.
        "RequestTimeoutError",
        # Google Gen AI (google-genai): every 5xx. Its 4xx class is decided by status code below.
        "ServerError",
        # Google API core (the SDK before google-genai), kept for anything still raising them.
        "ResourceExhausted",
        "ServiceUnavailable",
        "DeadlineExceeded",
        "GatewayTimeout",
        "TooManyRequests",
        # httpx: google-genai lets the transport's own errors through unwrapped. TimeoutException
        # covers the connect, read, write and pool timeouts; NetworkError covers ConnectError,
        # ReadError, WriteError and CloseError.
        "TimeoutException",
        "NetworkError",
        "RemoteProtocolError",
        # stdlib
        "ConnectionError",
        "TimeoutError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "ConnectionAbortedError",
        "BrokenPipeError",
        # urllib3 + requests transient class names (defensive)
        "ReadTimeoutError",
        "ConnectionTimeoutError",
        "ProtocolError",
    }
)

# Class names that MUST NOT be retried — checked before the transient set so
# `BadRequestError(APIError)` etc. don't slip through the MRO walk just because
# their base class is `APIError`.
_NON_TRANSIENT_ERROR_NAMES = frozenset(
    {
        "AuthenticationError",
        "BadRequestError",
        "InvalidRequestError",  # legacy OpenAI name
        "NotFoundError",
        "PermissionDeniedError",
        "UnprocessableEntityError",
        "ConflictError",
        # Anthropic: a 429 for a spend limit, which waiting does not lift (it subclasses
        # RateLimitError), and a 501, which no retry turns into an implemented endpoint (it
        # subclasses InternalServerError).
        "EnforcedSpendLimitReachedError",
        "HTTPNotImplementedError",
    }
)

# google-genai raises one `ClientError` for every 4xx; only the status code on it (`code`) tells
# a rate limit (429) or a request timeout (408) from a bad request or a bad key.
_STATUS_DECIDED_ERROR_NAMES = frozenset({"ClientError"})
_TRANSIENT_STATUS_CODES = frozenset({408, 429})


def _is_transient(exc: BaseException) -> bool:
    """True if `exc` is a known-transient API/network error worth retrying.

    Walks the class MRO so subclasses (`anthropic.APIConnectionError` →
    `anthropic.APIError` → `Exception`) are matched even if only the
    concrete name is in the allowlist. The non-transient blocklist is
    checked FIRST so `BadRequestError(APIError)` doesn't get retried just
    because it inherits from `APIError`.
    """
    names = {klass.__name__ for klass in type(exc).__mro__}
    if names & _NON_TRANSIENT_ERROR_NAMES:
        return False
    if names & _TRANSIENT_ERROR_NAMES:
        return True
    return bool(names & _STATUS_DECIDED_ERROR_NAMES) and (
        getattr(exc, "code", None) in _TRANSIENT_STATUS_CODES
    )


def retry_call[T](
    fn: Callable[..., T],
    *args: Any,
    max_retries: int = 2,
    backoff_base: float = 1.0,
    **kwargs: Any,
) -> T:
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
        except Exception as e:
            if attempt < max_retries and _is_transient(e):
                wait = backoff_base * (2**attempt)
                _log.warning(
                    "provider transient error %s on attempt %d/%d; retrying in %.1fs",
                    type(e).__name__,
                    attempt + 1,
                    max_retries + 1,
                    wait,
                )
                time.sleep(wait)
                last_exc = e
                continue
            raise
    # Unreachable for max_retries >= 0: the loop either returns or raises. An explicit raise
    # rather than `assert`, so the check survives `python -O`.
    if last_exc is None:
        raise AssertionError
    raise last_exc

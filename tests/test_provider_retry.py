"""Phase 4 reviewer fix #6 — provider retry helper.

Pins the contract of `murshid.providers.base.retry_call`:
  - Returns immediately on success.
  - Retries up to `max_retries` times on transient class-name-matched errors.
  - Propagates non-transient errors immediately (no retry).
  - Exhausts retries and re-raises the final exception when transient
    errors persist.
"""

from __future__ import annotations

import time

import pytest

from murshid.providers.base import retry_call


# ---------------------------------------------------------------------------
# Synthetic exceptions whose class names match the transient allowlist
# ---------------------------------------------------------------------------


class APIError(Exception):
    """Stand-in for the BASE class anthropic.APIError / openai.APIError.

    Both SDKs subclass APIError for BOTH transient (APIConnectionError,
    RateLimitError) AND non-transient (BadRequestError, AuthenticationError)
    errors. Round-2 reviewer (2.1) flagged that the original retry_call
    over-retried any subclass of APIError because the transient allowlist
    included `APIError` itself. The fix is a non-transient blocklist that
    takes precedence over the MRO walk.
    """


class APIConnectionError(APIError):
    """Mirrors anthropic.APIConnectionError / openai.APIConnectionError name.

    Note the SDK-realistic inheritance: this subclasses APIError, not Exception.
    """


class RateLimitError(APIError):
    """Mirrors anthropic.RateLimitError / openai.RateLimitError name."""


class ResourceExhausted(Exception):
    """Mirrors google.api_core.exceptions.ResourceExhausted name."""


class BadRequestError(APIError):
    """Non-transient — must NOT be retried.

    SDK-realistic inheritance: subclasses APIError just like the real
    anthropic.BadRequestError and openai.BadRequestError. This is the case
    the Round-2 reviewer caught — older test had inherited from Exception
    directly, so the MRO walk never hit APIError and the over-retry bug
    was invisible to the test.
    """


class AuthenticationError(APIError):
    """Non-transient — must NOT be retried. Inherits from APIError just like
    the real SDK exception classes."""


# ---------------------------------------------------------------------------
# retry_call contract
# ---------------------------------------------------------------------------


def test_retry_call_returns_immediately_on_success(monkeypatch):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    assert retry_call(fn) == "ok"
    assert calls["n"] == 1


def test_retry_call_retries_on_transient_error_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise APIConnectionError("connection reset")
        return "ok"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    assert retry_call(fn) == "ok"
    assert calls["n"] == 2


def test_retry_call_exhausts_retries_then_raises(monkeypatch):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise RateLimitError("rate limited")

    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(RateLimitError):
        retry_call(fn, max_retries=2)
    # max_retries=2 means: 1 initial attempt + 2 retries = 3 calls total.
    assert calls["n"] == 3


def test_retry_call_propagates_non_transient_immediately(monkeypatch):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise BadRequestError("bad request")

    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(BadRequestError):
        retry_call(fn, max_retries=5)
    # No retries — non-transient errors propagate on the first failure.
    assert calls["n"] == 1


def test_retry_call_authentication_error_not_retried(monkeypatch):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise AuthenticationError("missing API key")

    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(AuthenticationError):
        retry_call(fn, max_retries=5)
    assert calls["n"] == 1


def test_retry_call_google_resource_exhausted_is_transient(monkeypatch):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ResourceExhausted("quota exceeded")
        return "ok"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    assert retry_call(fn) == "ok"
    assert calls["n"] == 2


def test_retry_call_passes_args_and_kwargs(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def fn(a, b, *, c):
        return (a, b, c)

    assert retry_call(fn, 1, 2, c=3) == (1, 2, 3)


def test_retry_call_uses_exponential_backoff(monkeypatch):
    """Sleep durations should follow backoff_base * 2 ** attempt for each retry."""
    sleeps: list[float] = []

    def fake_sleep(d):
        sleeps.append(d)

    def fn():
        raise APIConnectionError("transient")

    monkeypatch.setattr(time, "sleep", fake_sleep)
    with pytest.raises(APIConnectionError):
        retry_call(fn, max_retries=3, backoff_base=1.0)
    # 3 retries → 3 sleeps before the final raise: 1.0, 2.0, 4.0
    assert sleeps == [1.0, 2.0, 4.0]


def test_retry_call_stdlib_connection_error_is_transient(monkeypatch):
    """stdlib ConnectionError name is in the transient allowlist."""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("network unreachable")
        return "ok"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    assert retry_call(fn) == "ok"
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Round 2 regression — non-transient SDK errors must not retry even though
# they inherit from APIError (which the old transient allowlist included).
# ---------------------------------------------------------------------------


def test_retry_call_bad_request_error_subclassing_api_error_not_retried(monkeypatch):
    """SDK-shaped: BadRequestError(APIError) must NOT be retried.

    Pre-fix bug: `_TRANSIENT_ERROR_NAMES` included `"APIError"` and the MRO
    walk found APIError on BadRequestError's chain, so it got retried as if
    transient. Fix: a non-transient blocklist short-circuits the MRO walk
    before the transient check.
    """
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise BadRequestError("model not found")

    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(BadRequestError):
        retry_call(fn, max_retries=5)
    assert calls["n"] == 1  # NO retries — non-transient must propagate immediately


def test_retry_call_authentication_error_subclassing_api_error_not_retried(monkeypatch):
    """Same regression for AuthenticationError(APIError)."""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise AuthenticationError("invalid API key")

    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(AuthenticationError):
        retry_call(fn, max_retries=5)
    assert calls["n"] == 1


def test_retry_call_transient_subclassing_api_error_still_retried(monkeypatch):
    """Counterpart: APIConnectionError(APIError) MUST still retry. The
    non-transient blocklist should only block the NAMED non-transient
    classes, not the entire APIError subtree."""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise APIConnectionError("connection reset")
        return "ok"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    assert retry_call(fn) == "ok"
    assert calls["n"] == 2


def test_retry_call_invalid_request_error_legacy_openai_name_not_retried(monkeypatch):
    """Legacy OpenAI name `InvalidRequestError` is in the blocklist."""
    class InvalidRequestError(APIError):
        pass

    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise InvalidRequestError("invalid request")

    monkeypatch.setattr(time, "sleep", lambda _: None)
    with pytest.raises(InvalidRequestError):
        retry_call(fn, max_retries=3)
    assert calls["n"] == 1

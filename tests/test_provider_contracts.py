# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Contract tests for the paid providers: the real SDK classes over a fake HTTP transport.

Each provider builds the real SDK client (anthropic, openai, google-genai) and hands it a fake
transport through the SDK's own injection point (`http_client=` for anthropic and openai, which
take an httpx2 client; `HttpOptions(httpx_client=)` for google-genai, which takes an httpx one).
The transport answers from a script and records every request. So the tests see exactly what goes
on the wire and exactly what the SDK raises, and no request leaves the process: a module-wide
fence also fails any socket connection or name lookup.

Pinned for each vendor: the request shape (model, max tokens, system prompt, user text, timeout,
key header); response parsing (text, usage, the real finish reason, a truncated reply); the SDK
client built once, with the SDK's own retries off; and `retry_call` as the only retry layer, on
the SDK's real exception classes: transient errors are retried twice, client errors never.
"""

from __future__ import annotations

import json
import socket
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any

import pytest

from murshid.providers import base
from murshid.providers.claude import ClaudeProvider
from murshid.providers.claude import normalise_finish_reason as claude_finish
from murshid.providers.gemini import GeminiProvider, thinking_budget
from murshid.providers.gemini import normalise_finish_reason as gemini_finish
from murshid.providers.openai import OpenAIProvider
from murshid.providers.openai import normalise_finish_reason as openai_finish

FAKE_KEY = "test-key-not-real-0000"
SYSTEM = "أنت مساعد."
USER = "ما رسوم تجديد الإقامة؟"


class ScriptExhaustedError(BaseException):
    """More requests than the script has steps. Not an Exception, so no SDK can swallow it."""


class Script:
    """A transport handler: each request takes the next step, a response or a transport fault.

    A step is `(status, json_body)` or an exception class of the HTTP library itself
    (`httpx2.ConnectError`), raised with the real request as that library would raise it.
    """

    def __init__(self, response_cls: Any, steps: Iterable[Any]) -> None:
        self._response_cls = response_cls
        self._steps: deque[Any] = deque(steps)
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        if not self._steps:
            raise ScriptExhaustedError(f"no step left for request {len(self.requests)}")
        step = self._steps.popleft()
        if isinstance(step, type) and issubclass(step, Exception):
            raise step("scripted transport fault", request=request)
        status, body = step
        return self._response_cls(status, json=body)

    def body(self, index: int = 0) -> Any:
        return json.loads(self.requests[index].content)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any real connection or DNS lookup fails the test."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a provider contract test tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_the_network_fence_is_up() -> None:
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("api.anthropic.com", 443), timeout=1)
    with pytest.raises(AssertionError, match="network"):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """retry_call's backoff sleeps, recorded instead of slept."""
    recorded: list[float] = []
    monkeypatch.setattr(base.time, "sleep", recorded.append)
    return recorded


def _timeout_of(request: Any) -> float:
    return float(request.extensions["timeout"]["read"])


# ---------------------------------------------------------------------------
# Claude (anthropic SDK over httpx2)
# ---------------------------------------------------------------------------


def _claude_message(
    text: str = "الرسوم SAR 600.", stop_reason: str = "end_turn", **usage: int
) -> dict[str, Any]:
    return {
        "id": "msg_test_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [
            {"type": "thinking", "thinking": "not part of the answer", "signature": "sig"},
            {"type": "text", "text": text},
        ],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 21, "output_tokens": 7, **usage},
    }


def _claude_error(status: int, error_type: str, error_code: str | None = None) -> tuple[int, Any]:
    error: dict[str, Any] = {"type": error_type, "message": "scripted error"}
    if error_code is not None:
        error["details"] = {"error_code": error_code}
    return status, {"type": "error", "error": error}


@pytest.fixture
def claude() -> Callable[..., tuple[ClaudeProvider, Script]]:
    pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")

    def make(*steps: Any, model_id: str = "claude-sonnet-4-6") -> tuple[ClaudeProvider, Script]:
        script = Script(httpx2.Response, steps)
        client = httpx2.Client(transport=httpx2.MockTransport(script))
        return ClaudeProvider(model_id, api_key=FAKE_KEY, http_client=client), script

    return make


def test_claude_sends_model_max_tokens_system_user_and_timeout(claude: Any) -> None:
    provider, script = claude((200, _claude_message()), model_id="claude-haiku-4-5-20251001")
    provider.generate(SYSTEM, USER, max_tokens=321, timeout=12.5)
    (request,) = script.requests
    assert request.method == "POST"
    assert request.url.path == "/v1/messages"
    assert script.body() == {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 321,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": USER}],
    }
    assert _timeout_of(request) == 12.5
    assert any(FAKE_KEY in value for value in request.headers.values())


def test_claude_parses_text_usage_and_the_real_finish_reason(claude: Any) -> None:
    provider, _ = claude((200, _claude_message("نص الإجابة", "end_turn")))
    response = provider.generate(SYSTEM, USER)
    assert response.text == "نص الإجابة"  # the thinking block is not the answer
    assert (response.input_tokens, response.output_tokens) == (21, 7)
    assert response.finish_reason == "stop"
    assert response.raw == {
        "id": "msg_test_1",
        "model": "claude-sonnet-4-6",
        "finish_reason": "end_turn",
    }
    assert response.latency_s >= 0


def test_claude_reports_a_truncated_reply_as_length(claude: Any) -> None:
    provider, _ = claude((200, _claude_message("نص مقطوع", "max_tokens")))
    response = provider.generate(SYSTEM, USER, max_tokens=5)
    assert response.finish_reason == "length"
    assert response.raw["finish_reason"] == "max_tokens"


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "length"),
        ("model_context_window_exceeded", "length"),
        ("refusal", "content_filter"),
        ("tool_use", "tool"),
        ("pause_turn", "other"),
        (None, "other"),
        ("a_reason_added_later", "other"),
    ],
)
def test_claude_finish_reasons_normalise(stop_reason: str | None, expected: str) -> None:
    assert claude_finish(stop_reason) == expected


def test_claude_builds_one_client_with_sdk_retries_off(claude: Any) -> None:
    import anthropic

    provider, script = claude((200, _claude_message()), (200, _claude_message()))
    provider.generate(SYSTEM, USER)
    client = provider._client
    provider.generate(SYSTEM, USER)
    assert isinstance(client, anthropic.Anthropic)
    assert provider._client is client
    assert client.max_retries == 0
    assert len(script.requests) == 2


def test_claude_transient_errors_are_retried_by_retry_call_alone(
    claude: Any, sleeps: list[float]
) -> None:
    import anthropic

    overloaded = _claude_error(529, "overloaded_error")
    provider, script = claude(overloaded, overloaded, overloaded)
    with pytest.raises(anthropic.OverloadedError):
        provider.generate(SYSTEM, USER)
    # One call and two retries, one request each: the SDK's own retries would make it nine.
    assert len(script.requests) == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    "fault",
    [
        _claude_error(503, "api_error"),
        _claude_error(500, "api_error"),
        _claude_error(429, "rate_limit_error"),
        _claude_error(408, "timeout_error"),
        "ConnectError",
        "ReadTimeout",
    ],
)
def test_claude_recovers_from_one_transient_fault(
    claude: Any, sleeps: list[float], fault: Any
) -> None:
    import httpx2

    step = getattr(httpx2, fault) if isinstance(fault, str) else fault
    provider, script = claude(step, (200, _claude_message("بعد إعادة المحاولة")))
    assert provider.generate(SYSTEM, USER).text == "بعد إعادة المحاولة"
    assert len(script.requests) == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    ("step", "error_name"),
    [
        (_claude_error(400, "invalid_request_error"), "BadRequestError"),
        (_claude_error(401, "authentication_error"), "AuthenticationError"),
        (_claude_error(403, "permission_error"), "PermissionDeniedError"),
        (_claude_error(404, "not_found_error"), "NotFoundError"),
        (
            _claude_error(429, "rate_limit_error", "enforced_spend_limit_reached"),
            "EnforcedSpendLimitReachedError",
        ),
        (_claude_error(501, "api_error"), "HTTPNotImplementedError"),
    ],
)
def test_claude_client_errors_are_never_retried(
    claude: Any, sleeps: list[float], step: Any, error_name: str
) -> None:
    import anthropic

    provider, script = claude(step)
    with pytest.raises(getattr(anthropic, error_name)):
        provider.generate(SYSTEM, USER)
    assert len(script.requests) == 1
    assert sleeps == []


def test_claude_without_a_key_is_unavailable_and_imports_nothing_to_say_so() -> None:
    assert not ClaudeProvider("claude-sonnet-4-6").is_available()
    assert ClaudeProvider("claude-sonnet-4-6", api_key=FAKE_KEY).is_available()


# ---------------------------------------------------------------------------
# OpenAI (openai SDK over httpx2)
# ---------------------------------------------------------------------------


def _openai_completion(
    content: str | None = "الرسوم SAR 600.", finish_reason: str = "stop"
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test-1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "gpt-5.5-2026-04-23",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 33, "completion_tokens": 9, "total_tokens": 42},
    }


def _openai_error(status: int, error_type: str) -> tuple[int, Any]:
    return status, {"error": {"message": "scripted error", "type": error_type, "code": None}}


@pytest.fixture
def openai() -> Callable[..., tuple[OpenAIProvider, Script]]:
    pytest.importorskip("openai")
    httpx2 = pytest.importorskip("httpx2")

    def make(*steps: Any, model_id: str = "gpt-5.5-2026-04-23") -> tuple[OpenAIProvider, Script]:
        script = Script(httpx2.Response, steps)
        client = httpx2.Client(transport=httpx2.MockTransport(script))
        return OpenAIProvider(model_id, api_key=FAKE_KEY, http_client=client), script

    return make


def test_openai_sends_model_max_completion_tokens_system_user_and_timeout(openai: Any) -> None:
    provider, script = openai((200, _openai_completion()), model_id="gpt-5.4-mini-2026-03-17")
    provider.generate(SYSTEM, USER, max_tokens=222, timeout=9.0)
    (request,) = script.requests
    assert request.method == "POST"
    assert request.url.path == "/v1/chat/completions"
    assert script.body() == {
        "model": "gpt-5.4-mini-2026-03-17",
        # GPT-5.x rejects the legacy max_tokens.
        "max_completion_tokens": 222,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
    }
    assert _timeout_of(request) == 9.0
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"


def test_openai_parses_text_usage_and_the_real_finish_reason(openai: Any) -> None:
    provider, _ = openai((200, _openai_completion("نص الإجابة", "stop")))
    response = provider.generate(SYSTEM, USER)
    assert response.text == "نص الإجابة"
    assert (response.input_tokens, response.output_tokens) == (33, 9)
    assert response.finish_reason == "stop"
    assert response.raw == {
        "id": "chatcmpl-test-1",
        "model": "gpt-5.5-2026-04-23",
        "finish_reason": "stop",
    }


def test_openai_reports_a_truncated_reply_as_length(openai: Any) -> None:
    # A reasoning model can spend the whole budget before writing: no text, finish "length".
    provider, _ = openai((200, _openai_completion(None, "length")))
    response = provider.generate(SYSTEM, USER, max_tokens=20)
    assert response.text == ""
    assert response.finish_reason == "length"


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("stop", "stop"),
        ("length", "length"),
        ("content_filter", "content_filter"),
        ("tool_calls", "tool"),
        ("function_call", "tool"),
        (None, "other"),
        ("a_reason_added_later", "other"),
    ],
)
def test_openai_finish_reasons_normalise(finish_reason: str | None, expected: str) -> None:
    assert openai_finish(finish_reason) == expected


def test_openai_builds_one_client_with_sdk_retries_off(openai: Any) -> None:
    import openai as openai_sdk

    provider, script = openai((200, _openai_completion()), (200, _openai_completion()))
    provider.generate(SYSTEM, USER)
    client = provider._client
    provider.generate(SYSTEM, USER)
    assert isinstance(client, openai_sdk.OpenAI)
    assert provider._client is client
    assert client.max_retries == 0
    assert len(script.requests) == 2


def test_openai_transient_errors_are_retried_by_retry_call_alone(
    openai: Any, sleeps: list[float]
) -> None:
    import openai as openai_sdk

    unavailable = _openai_error(503, "server_error")
    provider, script = openai(unavailable, unavailable, unavailable)
    with pytest.raises(openai_sdk.InternalServerError):
        provider.generate(SYSTEM, USER)
    assert len(script.requests) == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    "fault",
    [
        _openai_error(500, "server_error"),
        _openai_error(429, "rate_limit_exceeded"),
        "ConnectError",
        "ReadTimeout",
    ],
)
def test_openai_recovers_from_one_transient_fault(
    openai: Any, sleeps: list[float], fault: Any
) -> None:
    import httpx2

    step = getattr(httpx2, fault) if isinstance(fault, str) else fault
    provider, script = openai(step, (200, _openai_completion("بعد إعادة المحاولة")))
    assert provider.generate(SYSTEM, USER).text == "بعد إعادة المحاولة"
    assert len(script.requests) == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    ("step", "error_name"),
    [
        (_openai_error(400, "invalid_request_error"), "BadRequestError"),
        (_openai_error(401, "invalid_api_key"), "AuthenticationError"),
        (_openai_error(404, "model_not_found"), "NotFoundError"),
        (_openai_error(422, "unprocessable"), "UnprocessableEntityError"),
    ],
)
def test_openai_client_errors_are_never_retried(
    openai: Any, sleeps: list[float], step: Any, error_name: str
) -> None:
    import openai as openai_sdk

    provider, script = openai(step)
    with pytest.raises(getattr(openai_sdk, error_name)):
        provider.generate(SYSTEM, USER)
    assert len(script.requests) == 1
    assert sleeps == []


def test_openai_without_a_key_is_unavailable() -> None:
    assert not OpenAIProvider("gpt-5.5-2026-04-23").is_available()
    assert OpenAIProvider("gpt-5.5-2026-04-23", api_key=FAKE_KEY).is_available()


# ---------------------------------------------------------------------------
# Gemini (google-genai SDK over httpx)
# ---------------------------------------------------------------------------


def _gemini_reply(
    text: str | None = "الرسوم SAR 600.",
    finish_reason: str | None = "STOP",
    *,
    thoughts: int = 30,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"text": "thinking, not answering", "thought": True}]
    if text is not None:
        parts.append({"text": text})
    candidate: dict[str, Any] = {"content": {"role": "model", "parts": parts}, "index": 0}
    if finish_reason is not None:
        candidate["finishReason"] = finish_reason
    return {
        "candidates": [candidate],
        "usageMetadata": {
            "promptTokenCount": 40,
            "candidatesTokenCount": 6,
            "thoughtsTokenCount": thoughts,
            "totalTokenCount": 46 + thoughts,
        },
        "modelVersion": model,
        "responseId": "resp-test-1",
    }


def _gemini_error(status: int, error_status: str) -> tuple[int, Any]:
    return status, {"error": {"code": status, "message": "scripted error", "status": error_status}}


@pytest.fixture
def gemini() -> Callable[..., tuple[GeminiProvider, Script]]:
    pytest.importorskip("google.genai")
    httpx = pytest.importorskip("httpx")

    def make(*steps: Any, model_id: str = "gemini-2.5-flash") -> tuple[GeminiProvider, Script]:
        script = Script(httpx.Response, steps)
        client = httpx.Client(transport=httpx.MockTransport(script))
        return GeminiProvider(model_id, api_key=FAKE_KEY, http_client=client), script

    return make


def test_gemini_sends_model_budget_system_user_and_timeout(gemini: Any) -> None:
    provider, script = gemini((200, _gemini_reply()))
    provider.generate(SYSTEM, USER, max_tokens=4000, timeout=12.5)
    (request,) = script.requests
    assert request.method == "POST"
    assert request.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    body = script.body()
    assert body["contents"] == [{"role": "user", "parts": [{"text": USER}]}]
    assert body["systemInstruction"]["parts"] == [{"text": SYSTEM}]
    config = body["generationConfig"]
    assert config["maxOutputTokens"] == 4000
    assert config["temperature"] == 0.0
    # Thinking is capped at half the output budget, so the answer always has room.
    assert config["thinkingConfig"] in ({"thinkingBudget": 2000}, {"thinking_budget": 2000})
    assert _timeout_of(request) == 12.5
    assert request.headers["x-server-timeout"] == "13"
    assert request.headers["x-goog-api-key"] == FAKE_KEY


def test_gemini_3_models_keep_their_default_thinking(gemini: Any) -> None:
    provider, script = gemini(
        (200, _gemini_reply(model="gemini-3.1-pro-preview")), model_id="gemini-3.1-pro-preview"
    )
    provider.generate(SYSTEM, USER, max_tokens=1024)
    assert "thinkingConfig" not in script.body()["generationConfig"]
    assert script.requests[0].url.path == "/v1beta/models/gemini-3.1-pro-preview:generateContent"


@pytest.mark.parametrize(
    ("model", "max_tokens", "budget"),
    [
        ("gemini-2.5-flash", 4000, 2000),
        ("gemini-2.5-flash", 256, 128),
        ("gemini-2.5-flash", 100_000, 24576),
        ("gemini-2.5-pro", 100, 128),
        ("gemini-3.1-pro-preview", 4000, None),
        ("gemini-2.5-flash-lite", 4000, None),
    ],
)
def test_gemini_thinking_budget_is_half_the_output_within_the_model_limits(
    model: str, max_tokens: int, budget: int | None
) -> None:
    assert thinking_budget(model, max_tokens) == budget


def test_gemini_parses_text_usage_and_the_real_finish_reason(gemini: Any) -> None:
    provider, _ = gemini((200, _gemini_reply("نص الإجابة", "STOP", thoughts=30)))
    response = provider.generate(SYSTEM, USER)
    assert response.text == "نص الإجابة"  # the thought part is not the answer
    # Thinking tokens are billed as output.
    assert (response.input_tokens, response.output_tokens) == (40, 36)
    assert response.finish_reason == "stop"
    assert response.raw == {
        "id": "resp-test-1",
        "model": "gemini-2.5-flash",
        "finish_reason": "STOP",
        "block_reason": None,
        "thoughts_tokens": 30,
    }


def test_gemini_reports_thinking_that_ate_the_budget_as_length(gemini: Any) -> None:
    provider, _ = gemini((200, _gemini_reply(None, "MAX_TOKENS", thoughts=4000)))
    response = provider.generate(SYSTEM, USER, max_tokens=4000)
    assert response.text == ""
    assert response.finish_reason == "length"
    assert response.raw["finish_reason"] == "MAX_TOKENS"


def test_gemini_reports_a_blocked_prompt_as_content_filter(gemini: Any) -> None:
    blocked = {
        "promptFeedback": {"blockReason": "SAFETY"},
        "usageMetadata": {"promptTokenCount": 9},
    }
    provider, _ = gemini((200, blocked))
    response = provider.generate(SYSTEM, USER)
    assert response.text == ""
    assert response.finish_reason == "content_filter"
    assert response.raw["block_reason"] == "SAFETY"
    assert (response.input_tokens, response.output_tokens) == (9, 0)


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("STOP", "stop"),
        ("MAX_TOKENS", "length"),
        ("SAFETY", "content_filter"),
        ("RECITATION", "content_filter"),
        ("PROHIBITED_CONTENT", "content_filter"),
        ("SPII", "content_filter"),
        ("BLOCKLIST", "content_filter"),
        ("MALFORMED_FUNCTION_CALL", "tool"),
        ("UNEXPECTED_TOOL_CALL", "tool"),
        ("LANGUAGE", "other"),
        ("OTHER", "other"),
        ("FINISH_REASON_UNSPECIFIED", "other"),
        (None, "other"),
    ],
)
def test_gemini_finish_reasons_normalise(finish_reason: str | None, expected: str) -> None:
    assert gemini_finish(finish_reason) == expected


def test_gemini_parses_every_sdk_finish_reason() -> None:
    types = pytest.importorskip("google.genai.types")
    for member in types.FinishReason:
        assert gemini_finish(member.value) in {"stop", "length", "content_filter", "tool", "other"}


def test_gemini_builds_one_client_with_sdk_retries_off(gemini: Any) -> None:
    from google import genai

    provider, script = gemini((200, _gemini_reply()), (200, _gemini_reply()))
    provider.generate(SYSTEM, USER)
    client = provider._client
    provider.generate(SYSTEM, USER)
    assert isinstance(client, genai.Client)
    assert provider._client is client
    assert len(script.requests) == 2


def test_gemini_transient_errors_are_retried_by_retry_call_alone(
    gemini: Any, sleeps: list[float]
) -> None:
    from google.genai import errors

    unavailable = _gemini_error(503, "UNAVAILABLE")
    provider, script = gemini(unavailable, unavailable, unavailable)
    with pytest.raises(errors.ServerError):
        provider.generate(SYSTEM, USER)
    # One call and two retries, one request each: the SDK's default retry policy would add more.
    assert len(script.requests) == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    "fault",
    [
        _gemini_error(500, "INTERNAL"),
        _gemini_error(429, "RESOURCE_EXHAUSTED"),
        _gemini_error(408, "DEADLINE_EXCEEDED"),
        "ConnectError",
        "ReadTimeout",
    ],
)
def test_gemini_recovers_from_one_transient_fault(
    gemini: Any, sleeps: list[float], fault: Any
) -> None:
    import httpx

    step = getattr(httpx, fault) if isinstance(fault, str) else fault
    provider, script = gemini(step, (200, _gemini_reply("بعد إعادة المحاولة")))
    assert provider.generate(SYSTEM, USER).text == "بعد إعادة المحاولة"
    assert len(script.requests) == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    ("status", "error_status"),
    [
        (400, "INVALID_ARGUMENT"),
        (401, "UNAUTHENTICATED"),
        (403, "PERMISSION_DENIED"),
        (404, "NOT_FOUND"),
    ],
)
def test_gemini_client_errors_are_never_retried(
    gemini: Any, sleeps: list[float], status: int, error_status: str
) -> None:
    from google.genai import errors

    provider, script = gemini(_gemini_error(status, error_status))
    with pytest.raises(errors.ClientError) as caught:
        provider.generate(SYSTEM, USER)
    assert caught.value.code == status
    assert len(script.requests) == 1
    assert sleeps == []


def test_gemini_without_a_key_is_unavailable() -> None:
    assert not GeminiProvider("gemini-2.5-flash").is_available()
    assert GeminiProvider("gemini-2.5-flash", api_key=FAKE_KEY).is_available()

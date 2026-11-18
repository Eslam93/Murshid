"""Scripted faults for tests of retry and timeout code, and ablation checks for guard code.

A retry test is only as good as its fake errors. A fake that raises a home-made `TimeoutError`
tests code that the real client never reaches, because the real client raises
`httpx.ReadTimeout`, with a request attached, from inside its transport. `ScriptedTransport` sits
where the real network would be, under the real `httpx.AsyncClient`: each call takes the next step
of a script, which is a response (a 429 with Retry-After, a 503, a 200), an error of the client's
own class built with the real request, or a delay before either. It records every request.

An ablation check proves that a test tests something: the same check must pass with a component in
place and fail with it removed. A guard whose test still passes without the guard is not guarded.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any

import httpx

__all__ = [
    "Delay",
    "Fault",
    "ScriptExhaustedError",
    "ScriptedTransport",
    "ablated",
    "assert_ablation_flips",
    "delay",
    "fault",
    "respond",
]


class ScriptExhaustedError(AssertionError):
    """The code under test made more calls than the script has steps."""


@dataclass(frozen=True)
class Fault:
    """An error of the client's own class, built with the request it failed on."""

    error: type[httpx.RequestError]
    message: str

    def build(self, request: httpx.Request) -> httpx.RequestError:
        return self.error(self.message, request=request)


@dataclass(frozen=True)
class Delay:
    """Wait, then take `then`. A delay longer than the caller's timeout runs into it."""

    seconds: float
    then: Step


Step = httpx.Response | Fault | Delay | Callable[[httpx.Request], httpx.Response]


def respond(
    status: int,
    *,
    json: Any = None,
    headers: dict[str, str] | None = None,
    text: str | None = None,
) -> httpx.Response:
    """A response step. `json` and `text` are the body; neither is an empty body."""
    if json is not None:
        return httpx.Response(status, json=json, headers=headers)
    return httpx.Response(status, text=text or "", headers=headers)


def fault(error: type[httpx.RequestError], message: str = "scripted fault") -> Fault:
    """An error step: `fault(httpx.ConnectError)` raises the class httpx itself raises."""
    return Fault(error, message)


def delay(seconds: float, then: Step) -> Delay:
    return Delay(seconds, then)


class ScriptedTransport(httpx.AsyncBaseTransport):
    """An httpx transport that answers from a script, one step per request."""

    def __init__(self, steps: Iterable[Step]) -> None:
        self._steps: deque[Step] = deque(steps)
        self.requests: list[httpx.Request] = []

    @property
    def remaining(self) -> int:
        return len(self._steps)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.requests.append(request)
        if not self._steps:
            raise ScriptExhaustedError(f"no step left for request {len(self.requests)}")
        return await self._take(self._steps.popleft(), request)

    async def _take(self, step: Step, request: httpx.Request) -> httpx.Response:
        if isinstance(step, Delay):
            await asyncio.sleep(step.seconds)
            return await self._take(step.then, request)
        if isinstance(step, Fault):
            raise step.build(request)
        if isinstance(step, httpx.Response):
            return step
        return step(request)


@contextmanager
def ablated(target: object, attribute: str, replacement: object) -> Iterator[None]:
    """Replaces `target.attribute` for the block and puts the original back afterwards."""
    original = getattr(target, attribute)
    setattr(target, attribute, replacement)
    try:
        yield
    finally:
        setattr(target, attribute, original)


async def assert_ablation_flips(
    check: Callable[[], bool | Awaitable[bool]],
    ablation: Callable[[], AbstractContextManager[object]],
) -> None:
    """Fails unless `check()` is true as things are and false inside `ablation()`."""

    async def outcome() -> bool:
        value = check()
        if inspect.isawaitable(value):
            value = await value
        return bool(value)

    if not await outcome():
        raise AssertionError("the check fails with the component in place")
    with ablation():
        if await outcome():
            raise AssertionError(
                "the check still passes with the component removed, so it does not test it"
            )

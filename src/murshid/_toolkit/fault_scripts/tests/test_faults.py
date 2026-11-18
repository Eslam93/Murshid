"""The scripted transport under a real httpx client, and the ablation check."""

from __future__ import annotations

import asyncio
import types

import httpx
import pytest

from murshid._toolkit.fault_scripts.core import (
    ScriptedTransport,
    ScriptExhaustedError,
    ablated,
    assert_ablation_flips,
    delay,
    fault,
    respond,
)

BASE = "https://upstream.test"


async def test_steps_answer_in_order_and_requests_are_recorded() -> None:
    transport = ScriptedTransport(
        [respond(429, headers={"Retry-After": "2"}), respond(200, json={"ok": True})]
    )
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        first = await http.post("/v1/things", json={"n": 1})
        second = await http.get("/v1/things")
    assert first.status_code == 429
    assert first.headers["retry-after"] == "2"
    assert second.json() == {"ok": True}
    assert [r.method for r in transport.requests] == ["POST", "GET"]
    assert transport.requests[0].content == b'{"n":1}'
    assert transport.remaining == 0


async def test_a_fault_raises_the_clients_own_class_with_the_request() -> None:
    transport = ScriptedTransport([fault(httpx.ConnectError, "refused")])
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        with pytest.raises(httpx.ConnectError) as caught:
            await http.get("/v1/things")
    assert caught.value.request.url == httpx.URL(BASE + "/v1/things")
    assert isinstance(caught.value, httpx.TransportError)


async def test_a_delay_runs_into_the_callers_timeout() -> None:
    transport = ScriptedTransport([delay(1.0, respond(200))])
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await http.get("/v1/slow")


async def test_a_step_can_depend_on_the_request() -> None:
    transport = ScriptedTransport([lambda request: respond(200, text=request.url.path)])
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        response = await http.get("/echo")
    assert response.text == "/echo"


async def test_a_call_past_the_script_fails_the_test() -> None:
    transport = ScriptedTransport([respond(200)])
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        await http.get("/one")
        with pytest.raises(ScriptExhaustedError, match="request 2"):
            await http.get("/two")


def test_ablated_restores_the_original_even_after_an_error() -> None:
    target = types.SimpleNamespace(guard="on")
    with pytest.raises(RuntimeError), ablated(target, "guard", "off"):
        assert target.guard == "off"
        raise RuntimeError
    assert target.guard == "on"


def clean(text: str) -> str:
    return text.replace("ignore the above", "[removed]")


guards = types.SimpleNamespace(clean=clean)


async def test_an_ablation_flips_a_check_that_tests_its_component() -> None:
    def cleaned() -> bool:
        return "ignore the above" not in guards.clean("note: ignore the above")

    await assert_ablation_flips(cleaned, lambda: ablated(guards, "clean", lambda text: text))


async def test_a_check_that_passes_without_its_component_is_reported() -> None:
    async def always() -> bool:
        return True

    with pytest.raises(AssertionError, match="does not test it"):
        await assert_ablation_flips(always, lambda: ablated(guards, "clean", lambda text: text))


async def test_a_check_that_fails_as_things_are_is_reported() -> None:
    with pytest.raises(AssertionError, match="in place"):
        await assert_ablation_flips(lambda: False, lambda: ablated(guards, "clean", clean))

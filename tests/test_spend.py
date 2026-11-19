# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""The spend meter: calls are logged and priced, and no call starts past the cap."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from murshid.bench.spend import MeteredProvider, SpendCapError, SpendMeter
from murshid.providers.base import ProviderResponse


class _PricedFake:
    """A provider whose every call costs a fixed amount and is counted."""

    def __init__(self, cost: float, name: str = "openai", model_id: str = "fake-model") -> None:
        self.name, self.model_id, self.cost, self.calls = name, model_id, cost, 0

    def is_available(self) -> bool:
        return True

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return self.cost

    def generate(
        self, system: str, user: str, max_tokens: int = 1024, timeout: float = 30.0
    ) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(text="ok", input_tokens=100, output_tokens=10, latency_s=0.0)


def test_without_a_cap_every_call_runs_and_is_logged(tmp_path: Path) -> None:
    meter = SpendMeter(None, tmp_path / "spend-log.jsonl")
    provider = MeteredProvider(_PricedFake(0.25), meter)
    for _ in range(5):
        provider.generate("s", "u")
    assert meter.summary() == {
        "spent_usd": 1.25,
        "cap_usd": None,
        "cap_reached": False,
        "paid_calls": 5,
    }
    rows = [json.loads(line) for line in (tmp_path / "spend-log.jsonl").read_text().splitlines()]
    assert [row["spent_usd"] for row in rows] == [0.25, 0.5, 0.75, 1.0, 1.25]
    assert rows[0]["model_id"] == "fake-model"


def test_no_call_starts_once_the_next_one_could_pass_the_cap(tmp_path: Path) -> None:
    fake = _PricedFake(0.3)
    meter = SpendMeter(1.0, tmp_path / "spend-log.jsonl")
    provider = MeteredProvider(fake, meter)
    for _ in range(3):
        provider.generate("s", "u")  # 0.3, 0.6, 0.9 spent
    with pytest.raises(SpendCapError):
        provider.generate("s", "u")  # 0.9 + 0.3 would pass 1.0
    assert fake.calls == 3
    assert meter.stopped
    assert meter.spent_usd <= 1.0
    with pytest.raises(SpendCapError):
        provider.generate("s", "u")  # once stopped, stays stopped
    assert fake.calls == 3


def test_a_shared_meter_caps_the_answering_model_and_the_judge_together() -> None:
    meter = SpendMeter(0.5)
    answer = MeteredProvider(_PricedFake(0.2, model_id="answer"), meter)
    judge = MeteredProvider(_PricedFake(0.2, name="gemini", model_id="judge"), meter)
    answer.generate("s", "u")
    judge.generate("s", "u")
    with pytest.raises(SpendCapError):
        answer.generate("s", "u")
    assert meter.paid_calls == 2


def test_zero_key_calls_cost_nothing_and_log_nothing(tmp_path: Path) -> None:
    meter = SpendMeter(0.01, tmp_path / "spend-log.jsonl")
    provider = MeteredProvider(_PricedFake(0.0, name="extractive"), meter)
    for _ in range(50):
        provider.generate("s", "u")
    assert meter.paid_calls == 0 and not meter.stopped
    assert not (tmp_path / "spend-log.jsonl").exists()


def test_the_wrapper_keeps_the_provider_identity() -> None:
    inner = _PricedFake(0.0, name="claude", model_id="claude-x")
    wrapped = MeteredProvider(inner, SpendMeter(None))
    assert (wrapped.name, wrapped.model_id, wrapped.is_available()) == ("claude", "claude-x", True)


def test_a_cap_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        SpendMeter(0)

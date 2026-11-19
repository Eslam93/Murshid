# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""The provider registry (`murshid.providers.factory`) and the bench's use of it.

Pins: one registry entry per kind; building every kind with the settings' model ids; a paid kind
available only with its key (and its SDK); a dated price for every default, judge and offered
model, with the prices the bench has always used; judges named by model id alone. Nothing here
makes a call: a provider with a fake key is built and inspected, never asked to generate. The
bench's use of the registry is in tests/test_bench_runner.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

import murshid.providers.factory as factory
from murshid.providers.base import LLMProvider, ProviderResponse
from murshid.providers.claude import ClaudeProvider
from murshid.providers.extractive import ExtractiveProvider
from murshid.providers.factory import (
    DEFAULT_JUDGE_MODEL_ID,
    DEFAULT_MODEL_IDS,
    DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID,
    FALLBACK_PRICES,
    FREE,
    OFFERED_MODEL_IDS,
    PAID_KINDS,
    PRICES,
    PROVIDER_KINDS,
    ZERO_KEY_KINDS,
    as_kind,
    availability_hint,
    available_kinds,
    build_enrichment_provider,
    build_judge,
    build_provider,
    has_listed_price,
    kind_for_model_id,
    model_menu,
    price_for,
)
from murshid.providers.gemini import GeminiProvider
from murshid.providers.mock import MockProvider
from murshid.providers.openai import OpenAIProvider
from murshid.providers.replay import ReplayProvider
from murshid.settings import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]

_CLASSES: dict[str, type[Any]] = {
    "mock": MockProvider,
    "extractive": ExtractiveProvider,
    "replay": ReplayProvider,
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def _settings(**overrides: Any) -> Settings:
    """Settings with no file and the repository's data and recorded answers."""
    values: dict[str, Any] = {
        "murshid_data_dir": ROOT / "data",
        "murshid_replay_file": ROOT / "bench" / "case-cache.json",
    }
    values.update(overrides)
    return load_settings(Settings, _env_file=None, **values)


def _all_keys() -> dict[str, str]:
    return {
        "anthropic_api_key": "sk-ant-test-fake",
        "openai_api_key": "sk-test-fake",
        "gemini_api_key": "test-fake-gemini-key",
    }


# ---------------------------------------------------------------------------
# The registry is complete
# ---------------------------------------------------------------------------


def test_every_kind_has_a_default_model_and_an_offered_list() -> None:
    assert set(DEFAULT_MODEL_IDS) == set(PROVIDER_KINDS)
    assert set(OFFERED_MODEL_IDS) == set(PROVIDER_KINDS)
    assert set(ZERO_KEY_KINDS) | set(PAID_KINDS) == set(PROVIDER_KINDS)
    assert set(ZERO_KEY_KINDS).isdisjoint(PAID_KINDS)
    for kind in PROVIDER_KINDS:
        assert OFFERED_MODEL_IDS[kind][0] == DEFAULT_MODEL_IDS[kind], f"{kind}: default first"


@pytest.mark.parametrize("kind", PROVIDER_KINDS)
def test_every_kind_builds_its_class_with_the_default_model(kind: str) -> None:
    provider = build_provider(kind, settings=_settings())
    assert isinstance(provider, _CLASSES[kind])
    assert isinstance(provider, LLMProvider)
    assert provider.name == kind
    expected = DEFAULT_MODEL_IDS[as_kind(kind)]
    assert provider.model_id == (f"replay:{expected}" if kind == "replay" else expected)


def test_the_settings_choose_the_model_and_an_argument_overrides_them() -> None:
    settings = _settings(anthropic_model_id="claude-haiku-4-5-20251001")
    assert build_provider("claude", settings=settings).model_id == "claude-haiku-4-5-20251001"
    assert build_provider("claude", "claude-opus-4-7", settings).model_id == "claude-opus-4-7"
    assert build_provider("replay", "claude/claude-sonnet-4-6", settings).model_id == (
        "replay:claude/claude-sonnet-4-6"
    )
    replay = _settings(murshid_replay_model="claude/claude-sonnet-4-6")
    assert build_provider("replay", settings=replay).model_id == "replay:claude/claude-sonnet-4-6"


def test_a_paid_provider_gets_its_key_from_the_settings() -> None:
    settings = _settings(**_all_keys())
    for kind in PAID_KINDS:
        provider = build_provider(kind, settings=settings)
        assert provider.is_available(), kind
        assert getattr(provider, "_api_key", None) == factory.api_key(kind, settings)
    assert not build_provider("claude", settings=_settings()).is_available()


def test_an_unknown_kind_is_refused_with_the_list_of_kinds() -> None:
    with pytest.raises(ValueError, match="falcon-arabic") as caught:
        build_provider("falcon-arabic", settings=_settings())
    for kind in PROVIDER_KINDS:
        assert kind in str(caught.value)


def test_the_single_model_kinds_refuse_another_model_id() -> None:
    for kind in ("mock", "extractive"):
        with pytest.raises(ValueError, match="one model"):
            build_provider(kind, "something-else", _settings())


def test_build_provider_reads_the_settings_when_none_are_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL_ID", "claude-opus-4-6")
    assert build_provider("claude").model_id == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def test_without_keys_only_the_zero_key_kinds_are_available() -> None:
    assert available_kinds(_settings()) == ["extractive", "replay", "mock"]


def test_replay_is_available_only_with_its_recorded_answers(tmp_path: Path) -> None:
    settings = _settings(murshid_replay_file=tmp_path / "missing.json")
    assert available_kinds(settings) == ["extractive", "mock"]


@pytest.mark.parametrize(
    ("key_field", "kind"),
    [("anthropic_api_key", "claude"), ("openai_api_key", "openai"), ("gemini_api_key", "gemini")],
)
def test_a_paid_kind_is_available_when_its_key_is_set(key_field: str, kind: str) -> None:
    available = available_kinds(_settings(**{key_field: "test-fake-key"}))
    assert available == ["extractive", "replay", "mock", kind]


def test_a_blank_key_does_not_count() -> None:
    assert "claude" not in available_kinds(_settings(anthropic_api_key="   "))


def test_a_key_without_its_sdk_is_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "sdk_installed", lambda kind: kind != "gemini")
    available = available_kinds(_settings(**_all_keys()))
    assert "gemini" not in available
    assert {"claude", "openai"} <= set(available)


def test_the_sdks_are_installed_for_this_test_run() -> None:
    for kind in PAID_KINDS:
        pytest.importorskip(factory._SDK_DISTRIBUTIONS[kind].replace("-", "."))
        assert factory.sdk_installed(kind)
    assert factory.sdk_installed("extractive")


def test_the_availability_hint_names_what_is_missing() -> None:
    assert "ANTHROPIC_API_KEY" in availability_hint("claude")
    assert "GEMINI_API_KEY" in availability_hint("gemini")
    assert "MURSHID_REPLAY_FILE" in availability_hint("replay")


def test_the_model_menu_lists_what_can_answer_with_the_configured_model_first() -> None:
    menu = model_menu(_settings(openai_api_key="sk-test-fake", openai_model_id="gpt-4o"))
    assert menu[0] == ("extractive", "extractive-1")
    assert ("extractive", "extractive-1") in menu
    openai_models = [model for kind, model in menu if kind == "openai"]
    assert openai_models == ["gpt-4o", *OFFERED_MODEL_IDS["openai"]]
    assert not [kind for kind, _ in menu if kind in {"claude", "gemini"}]


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def test_every_default_judge_and_offered_model_has_its_own_dated_price() -> None:
    priced = [(kind, DEFAULT_MODEL_IDS[kind]) for kind in PROVIDER_KINDS]
    priced += [(kind, model) for kind in PAID_KINDS for model in OFFERED_MODEL_IDS[kind]]
    priced += [("gemini", DEFAULT_JUDGE_MODEL_ID), ("claude", DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID)]
    for kind, model in priced:
        assert has_listed_price(as_kind(kind), model), f"no price for {kind}/{model}"


def test_every_price_has_a_date_and_a_source() -> None:
    every = [price for table in PRICES.values() for price in table.values()]
    every += [*FALLBACK_PRICES.values(), FREE]
    for price in every:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", price.as_of), price
        assert price.source.strip(), price
        assert price.input_usd_per_mtok >= 0
        assert price.output_usd_per_mtok >= 0


@pytest.mark.parametrize(
    ("kind", "model", "expected_usd"),
    [
        # USD for 1M input + 1M output tokens, at the registry's dated prices.
        ("claude", "claude-sonnet-4-6", 18.00),
        ("claude", "claude-opus-4-7", 30.00),
        ("claude", "claude-haiku-5-5", 0.60),
        ("openai", "gpt-5.5-2026-04-23", 20.00),
        ("openai", "gpt-5.4-mini-2026-03-17", 4.00),
        ("gemini", "gemini-2.5-flash", 2.80),
        ("gemini", "gemini-3.1-pro-preview", 12.50),
        # An unknown model is priced like the kind's default tier, never free.
        ("claude", "claude-unknown-model", 18.00),
        ("openai", "gpt-unknown-model", 20.00),
        ("gemini", "gemini-unknown-model", 12.50),
    ],
)
def test_a_provider_prices_its_calls_from_the_registry(
    kind: str, model: str, expected_usd: float
) -> None:
    provider = build_provider(kind, model, _settings())
    response = ProviderResponse(
        text="", input_tokens=1_000_000, output_tokens=1_000_000, latency_s=0
    )
    assert provider.cost_estimate_usd(response) == pytest.approx(expected_usd)


def test_the_zero_key_kinds_are_free() -> None:
    response = ProviderResponse(text="x", input_tokens=10**6, output_tokens=10**6, latency_s=0)
    for kind in ZERO_KEY_KINDS:
        assert price_for(kind, DEFAULT_MODEL_IDS[kind]) == FREE
        assert build_provider(kind, settings=_settings()).cost_estimate_usd(response) == 0.0


def test_no_other_module_holds_a_model_id_or_price_table() -> None:
    """The registry is the one place: no other source file lists the known model ids."""
    model_ids = {model for table in PRICES.values() for model in table}
    model_ids |= {model for kind in PAID_KINDS for model in OFFERED_MODEL_IDS[kind]}
    tables = []
    for path in [*(ROOT / "src" / "murshid").rglob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        if "_toolkit" in path.parts or path.name == "factory.py":
            continue
        text = path.read_text(encoding="utf-8")
        named = {model for model in model_ids if f'"{model}"' in text or f"'{model}'" in text}
        if len(named) > 1:
            tables.append((path.relative_to(ROOT).as_posix(), sorted(named)))
    assert tables == []


# ---------------------------------------------------------------------------
# Judges and the enrichment provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "kind"),
    [
        ("claude-opus-4-7", "claude"),
        ("claude-some-future-model", "claude"),
        ("gpt-5.4-mini-2026-03-17", "openai"),
        ("gpt-6", "openai"),
        ("gemini-2.5-flash", "gemini"),
        ("gemini-4-ultra", "gemini"),
        ("mistral-large", None),
    ],
)
def test_a_model_id_names_its_kind(model: str, kind: str | None) -> None:
    assert kind_for_model_id(model) == kind


def test_judges_are_built_from_their_model_id_alone() -> None:
    judge = build_judge(DEFAULT_JUDGE_MODEL_ID, _settings())
    assert isinstance(judge, GeminiProvider)
    assert judge.model_id == "gemini-2.5-flash"
    swap = build_judge(DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID, _settings())
    assert isinstance(swap, ClaudeProvider)
    assert swap.model_id == "claude-opus-4-7"
    with pytest.raises(ValueError, match="no provider kind"):
        build_judge("mistral-large", _settings())


def test_the_enrichment_provider_honours_its_settings() -> None:
    assert isinstance(build_enrichment_provider(_settings()), MockProvider)
    chosen = build_enrichment_provider(
        _settings(
            metadata_enrichment_provider="openai",
            metadata_enrichment_model_id="gpt-5.4-mini-2026-03-17",
            openai_api_key="sk-test-fake",
        )
    )
    assert isinstance(chosen, OpenAIProvider)
    assert chosen.model_id == "gpt-5.4-mini-2026-03-17"
    assert isinstance(
        build_enrichment_provider(_settings(metadata_enrichment_provider="extractive")),
        ExtractiveProvider,
    )

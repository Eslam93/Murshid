# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Murshid's typed settings (`murshid.settings`), built on the vendored C02 core.

Pins: the defaults (model ids from the registry); reading the environment and a `.env` file, the
environment winning; an empty value meaning the default; fail-fast errors that name the variable
and never its value; and `.env.example` listing exactly the settings, with safe values.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import murshid.settings
from murshid.providers.factory import (
    DEFAULT_JUDGE_MODEL_ID,
    DEFAULT_MODEL_IDS,
    DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID,
    PROVIDER_KINDS,
)
from murshid.settings import Settings, SettingsError, env_names, get_settings, load_settings

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"

# Settings the project once documented that nothing ever read.
DEAD_SETTINGS = {
    "NORMALIZE_AGGRESSIVE",
    "OLLAMA_BASE_URL",
    "FALCON_ARABIC_MODEL",
}
KEY_SETTINGS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"}


def _clean() -> Settings:
    return load_settings(Settings, _env_file=None)


def _example_lines() -> dict[str, str]:
    """NAME -> value for every assignment line of .env.example."""
    pairs: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, sep, value = stripped.partition("=")
        assert sep, f"not a NAME=value line in .env.example: {line!r}"
        assert name not in pairs, f"{name} is listed twice in .env.example"
        pairs[name] = value
    return pairs


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_defaults_are_the_zero_key_path_and_the_registry_model_ids() -> None:
    settings = _clean()
    assert settings.llm_provider == "extractive"
    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None
    assert settings.gemini_api_key is None
    assert settings.anthropic_model_id == DEFAULT_MODEL_IDS["claude"] == "claude-sonnet-4-6"
    assert settings.openai_model_id == DEFAULT_MODEL_IDS["openai"] == "gpt-5.5-2026-04-23"
    assert settings.gemini_model_id == DEFAULT_MODEL_IDS["gemini"] == "gemini-3.1-pro-preview"
    assert settings.metadata_enrichment_provider == "mock"
    assert settings.metadata_enrichment_model_id is None
    assert settings.bench_judge_model == DEFAULT_JUDGE_MODEL_ID == "gemini-2.5-flash"
    assert settings.bench_sanity_swap_judge_model == DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID
    assert DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID == "claude-opus-4-7"
    assert settings.murshid_data_dir == Path("data")
    assert settings.murshid_out_dir == Path("out")
    assert settings.murshid_replay_file == Path("bench/case-cache.json")
    assert settings.murshid_replay_model == "openai/gpt-5.5-2026-04-23"


def test_every_provider_kind_is_a_valid_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    for kind in PROVIDER_KINDS:
        monkeypatch.setenv("LLM_PROVIDER", kind)
        assert _clean().llm_provider == kind


def test_the_variable_names_are_the_field_names_in_upper_case() -> None:
    assert env_names() == [name.upper() for name in Settings.model_fields]
    assert "LLM_PROVIDER" in env_names()
    assert "BENCH_SANITY_SWAP_JUDGE_MODEL" in env_names()


def test_dead_settings_are_gone_and_ignored_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    assert DEAD_SETTINGS.isdisjoint(env_names())
    before = _clean()
    for name in DEAD_SETTINGS:
        monkeypatch.setenv(name, "anything")
    assert _clean() == before  # an old .env still loads, and the old names change nothing


# ---------------------------------------------------------------------------
# Reading the environment and .env
# ---------------------------------------------------------------------------


def test_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-ant-test-not-a-real-key  ")
    monkeypatch.setenv("ANTHROPIC_MODEL_ID", "claude-haiku-4-5-20251001")
    monkeypatch.setenv("METADATA_ENRICHMENT_PROVIDER", "openai")
    monkeypatch.setenv("METADATA_ENRICHMENT_MODEL_ID", "gpt-5.4-mini-2026-03-17")
    monkeypatch.setenv("BENCH_SANITY_SWAP_JUDGE_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("MURSHID_DATA_DIR", "elsewhere/data")
    settings = _clean()
    assert settings.llm_provider == "claude"
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-not-a-real-key"
    assert settings.anthropic_model_id == "claude-haiku-4-5-20251001"
    assert settings.metadata_enrichment_provider == "openai"
    assert settings.metadata_enrichment_model_id == "gpt-5.4-mini-2026-03-17"
    assert settings.bench_sanity_swap_judge_model == "claude-sonnet-4-6"
    assert settings.murshid_data_dir == Path("elsewhere/data")


def test_reads_a_dot_env_file_and_the_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=replay\nOPENAI_MODEL_ID=gpt-4o\nGEMINI_MODEL_ID=gemini-2.5-flash\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GEMINI_MODEL_ID", "gemini-2.5-pro")
    settings = load_settings(Settings, _env_file=env_file)
    assert settings.llm_provider == "replay"
    assert settings.openai_model_id == "gpt-4o"
    assert settings.gemini_model_id == "gemini-2.5-pro"


def test_an_empty_value_means_the_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=\nANTHROPIC_MODEL_ID=\nANTHROPIC_API_KEY=\n", encoding="utf-8"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings = load_settings(Settings, _env_file=env_file)
    assert settings.llm_provider == "extractive"
    assert settings.anthropic_model_id == DEFAULT_MODEL_IDS["claude"]
    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None


def test_get_settings_reads_the_configured_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=mock\n", encoding="utf-8")
    monkeypatch.setattr(murshid.settings, "ENV_FILE", env_file)
    assert get_settings().llm_provider == "mock"


def test_tests_never_see_the_developer_dot_env() -> None:
    """The autouse guard in tests/conftest.py: no file, no key, the defaults."""
    assert murshid.settings.ENV_FILE is None
    assert get_settings() == _clean()


def test_a_key_is_never_shown_by_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    leaked = "sk-test-value-that-must-not-appear-7c1e"
    monkeypatch.setenv("OPENAI_API_KEY", leaked)
    settings = _clean()
    assert leaked not in repr(settings)
    assert leaked not in str(settings)
    assert leaked not in settings.model_dump_json()


# ---------------------------------------------------------------------------
# Fail fast: the variable's name, never its value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("variable", "bad_value"),
    [
        ("LLM_PROVIDER", "leaky-provider-value-31a4"),
        ("METADATA_ENRICHMENT_PROVIDER", "leaky-enrichment-value-77b2"),
        ("BENCH_JUDGE_MODEL", "leaky-judge-model-9d0c"),
        ("BENCH_SANITY_SWAP_JUDGE_MODEL", "leaky-swap-model-4e8f"),
        ("MURSHID_REPLAY_MODEL", "leaky-replay-model-without-a-slash"),
    ],
)
def test_a_bad_value_stops_with_the_name_and_never_the_value(
    monkeypatch: pytest.MonkeyPatch, variable: str, bad_value: str
) -> None:
    monkeypatch.setenv(variable, bad_value)
    with pytest.raises(SettingsError) as caught:
        _clean()
    message = str(caught.value)
    assert variable in message
    assert bad_value not in message
    assert all(bad_value not in problem for problem in caught.value.problems)
    assert caught.value.__cause__ is None


def test_every_bad_variable_is_named_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "falcon-arabic")
    monkeypatch.setenv("BENCH_JUDGE_MODEL", "mistral-large")
    with pytest.raises(SettingsError) as caught:
        _clean()
    named = {problem.split(":", 1)[0] for problem in caught.value.problems}
    assert named == {"LLM_PROVIDER", "BENCH_JUDGE_MODEL"}


def test_the_llm_provider_error_lists_the_valid_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    with pytest.raises(SettingsError) as caught:
        _clean()
    (problem,) = caught.value.problems
    assert problem.startswith("LLM_PROVIDER: ")
    for kind in PROVIDER_KINDS:
        assert f"'{kind}'" in problem


# ---------------------------------------------------------------------------
# .env.example
# ---------------------------------------------------------------------------


def test_env_example_lists_exactly_the_settings() -> None:
    assert sorted(_example_lines()) == sorted(env_names())


def test_env_example_holds_no_key_and_no_dead_setting() -> None:
    lines = _example_lines()
    for name in KEY_SETTINGS:
        assert lines[name] == "", f"{name} must be empty in .env.example"
    assert DEAD_SETTINGS.isdisjoint(lines)


def test_env_example_values_are_the_defaults() -> None:
    """Copying .env.example to .env changes nothing until a value is filled in."""
    assert load_settings(Settings, _env_file=ENV_EXAMPLE) == _clean()

"""The settings core through its public interface, with a settings class of its own."""

from __future__ import annotations

import pytest
from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from murshid._toolkit.fail_fast_settings.core import (
    CommaSeparated,
    FailFastSettings,
    SettingsError,
    load_settings,
)


class ExampleSettings(FailFastSettings):
    database_url: str
    signing_key: SecretStr
    sweep_seconds: int = Field(default=60, ge=10, le=3600)
    allowed_origins: CommaSeparated = Field(default_factory=list)


def test_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.test/app")
    monkeypatch.setenv("SIGNING_KEY", "k" * 40)
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.test, https://b.test,,")
    settings = load_settings(ExampleSettings, _env_file=None)
    assert settings.database_url == "postgresql://db.test/app"
    assert settings.allowed_origins == ["https://a.test", "https://b.test"]
    assert settings.sweep_seconds == 60


def test_a_missing_variable_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SIGNING_KEY", "k" * 40)
    with pytest.raises(SettingsError) as caught:
        load_settings(ExampleSettings, _env_file=None)
    assert "DATABASE_URL" in str(caught.value)


def test_an_out_of_bounds_number_stops_the_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.test/app")
    monkeypatch.setenv("SIGNING_KEY", "k" * 40)
    monkeypatch.setenv("SWEEP_SECONDS", "0")
    with pytest.raises(SettingsError) as caught:
        load_settings(ExampleSettings, _env_file=None)
    assert caught.value.problems == ["SWEEP_SECONDS: Input should be greater than or equal to 10"]


def test_the_message_never_contains_a_value(monkeypatch: pytest.MonkeyPatch) -> None:
    leaked = "value-that-must-not-appear-9f2c"
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.test/app")
    monkeypatch.setenv("SIGNING_KEY", "k" * 40)
    monkeypatch.setenv("SWEEP_SECONDS", leaked)
    with pytest.raises(SettingsError) as caught:
        load_settings(ExampleSettings, _env_file=None)
    assert "SWEEP_SECONDS" in str(caught.value)
    assert leaked not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_prefix_is_part_of_the_variable_name(monkeypatch: pytest.MonkeyPatch) -> None:
    class Prefixed(FailFastSettings):
        model_config = SettingsConfigDict(env_prefix="APP_")  # merged with the base class's
        port: int = Field(ge=1, le=65535)

    monkeypatch.setenv("APP_PORT", "70000")
    with pytest.raises(SettingsError) as caught:
        load_settings(Prefixed, _env_file=None)
    assert caught.value.problems[0].startswith("APP_PORT:")


def test_overrides_come_from_code() -> None:
    settings = load_settings(
        ExampleSettings,
        _env_file=None,
        database_url="postgresql://db.test/app",
        signing_key="k" * 40,
        allowed_origins=["https://c.test"],
    )
    assert settings.allowed_origins == ["https://c.test"]

"""Settings that fail fast at boot and never print a value.

A settings class built on `FailFastSettings` reads environment variables (and an optional .env
file). `load_settings` builds it once at boot: when any value is missing or out of bounds it raises
`SettingsError`, whose message names every bad variable and why, and never contains a value, so a
secret cannot reach a log through a typo.

Bound every number with a floor and a ceiling (`Field(ge=..., le=...)`): a zero or a huge value
typed by mistake then stops the boot instead of silently removing a limit.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeVar

from pydantic import BeforeValidator, ValidationError
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["CommaSeparated", "FailFastSettings", "SettingsError", "load_settings"]


def _split_commas(value: object) -> object:
    """Splits "a, b,,c" into ["a", "b", "c"]. A list, from code or tests, is kept as it is."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


# NoDecode stops pydantic-settings from parsing the value as JSON, so a plain comma-separated
# environment value such as "https://a.test,https://b.test" reaches _split_commas.
CommaSeparated = Annotated[list[str], NoDecode, BeforeValidator(_split_commas)]


class FailFastSettings(BaseSettings):
    """Base for a project's settings. Values never appear in validation errors."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


class SettingsError(RuntimeError):
    """The settings are not valid. The message names variables, never their values."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("refusing to start, the settings are not valid: " + "; ".join(problems))


def _variable(settings_cls: type[BaseSettings], location: tuple[int | str, ...]) -> str:
    """The environment variable a validation error points at."""
    if not location:
        return "settings"
    prefix = str(settings_cls.model_config.get("env_prefix") or "")
    return f"{prefix}{location[0]}".upper()


# TypeVar, not the 3.12 syntax: the core also lifts into a Python 3.11 project.
S = TypeVar("S", bound=BaseSettings)


def load_settings(settings_cls: type[S], **overrides: Any) -> S:
    """Builds the settings, or raises SettingsError naming each bad variable.

    `overrides` are passed to the class as values, for tests and for code that already knows them.
    """
    try:
        return settings_cls(**overrides)
    except ValidationError as exc:
        problems = [
            f"{_variable(settings_cls, error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False, include_context=False)
        ]
        raise SettingsError(problems) from None

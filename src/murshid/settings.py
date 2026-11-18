"""Murshid's settings: one typed object, read from the environment and `.env`, checked at start.

Built on the vendored C02 core (`murshid._toolkit.fail_fast_settings`): a missing or malformed
value stops the program with the variable's name and what is wrong, never the value. The
variable names are the field names in upper case (`llm_provider` is `LLM_PROVIDER`). `.env` is
read from the working directory; a variable set in the environment wins over `.env`, and an
empty value counts as unset, so `KEY=` keeps the default.

Model-id defaults come from the provider registry (`murshid.providers.factory`), the one place
model ids and prices live. `.env.example` lists exactly these settings
(`tests/test_settings.py` keeps the two in step).

To add a setting: add a field in the group it belongs to, document it in `.env.example`, and
read it through `get_settings()`, never from `os.environ`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from murshid._toolkit.fail_fast_settings.core import FailFastSettings, SettingsError, load_settings
from murshid.providers.factory import (
    DEFAULT_JUDGE_MODEL_ID,
    DEFAULT_MODEL_IDS,
    DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID,
    ProviderKind,
    kind_for_model_id,
)

__all__ = ["ENV_FILE", "Settings", "SettingsError", "env_names", "get_settings", "load_settings"]

# Where `get_settings` reads `.env` from: the working directory. Tests point it at nothing.
ENV_FILE: Path | None = Path(".env")


class Settings(FailFastSettings):
    """Every setting Murshid reads. Field `x_y` is environment variable `X_Y`."""

    model_config = SettingsConfigDict(env_ignore_empty=True, str_strip_whitespace=True)

    # ---- Which provider answers (demo, UI and command line) ---------------------------------
    llm_provider: ProviderKind = "extractive"

    # ---- Paid providers: a key turns the provider on; the model id defaults per registry -----
    anthropic_api_key: SecretStr | None = None
    anthropic_model_id: str = DEFAULT_MODEL_IDS["claude"]
    openai_api_key: SecretStr | None = None
    openai_model_id: str = DEFAULT_MODEL_IDS["openai"]
    gemini_api_key: SecretStr | None = None
    gemini_model_id: str = DEFAULT_MODEL_IDS["gemini"]

    # ---- Index build: the provider that writes each chunk's summary and keywords --------------
    metadata_enrichment_provider: ProviderKind = "mock"
    # None means the enrichment provider's own default model.
    metadata_enrichment_model_id: str | None = None

    # ---- Bench judges --------------------------------------------------------------------------
    bench_judge_model: str = DEFAULT_JUDGE_MODEL_ID
    bench_sanity_swap_judge_model: str = DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID

    # ---- Paths, relative to the working directory -------------------------------------------
    murshid_data_dir: Path = Path("data")
    murshid_out_dir: Path = Path("out")
    # The replay provider's recorded answers, and the recorded model it replays.
    murshid_replay_file: Path = Path("bench/case-cache.json")
    murshid_replay_model: str = DEFAULT_MODEL_IDS["replay"]

    @field_validator("bench_judge_model", "bench_sanity_swap_judge_model")
    @classmethod
    def _judge_model_has_a_provider(cls, value: str) -> str:
        if kind_for_model_id(value) is None:
            raise ValueError("must be a claude-, gpt- or gemini- model id")
        return value

    @field_validator("murshid_replay_model")
    @classmethod
    def _replay_model_names_provider_and_model(cls, value: str) -> str:
        provider, _, model = value.partition("/")
        if not provider or not model:
            raise ValueError("must be <provider>/<model id>, as the bench recorded it")
        return value


def env_names() -> list[str]:
    """The environment variable of every setting, in field order."""
    return [name.upper() for name in Settings.model_fields]


def get_settings() -> Settings:
    """Read the settings now, or raise `SettingsError` naming every bad variable."""
    return load_settings(Settings, _env_file=ENV_FILE)

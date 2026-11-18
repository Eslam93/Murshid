# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""The one provider registry: kinds, default model ids, prices, and how each kind is built.

Every place that picks a provider (the demo, the UI, the bench and its judges, the key check, the
index build) goes through `build_provider` and `available_kinds`, and every model id and price
the code knows lives in this file.

Kinds:
  - zero-key: `extractive` (quotes the retrieved passages), `replay` (recorded real-model
    answers to the bench questions, else extractive), `mock` (a test double).
  - paid: `claude`, `openai`, `gemini`. A paid kind is available only when its API key is set
    and its SDK (the `providers` extra) is installed.

Building a provider never imports a vendor SDK: each paid provider imports its SDK on its first
call, and this module imports the provider classes only inside `build_provider`.

Prices are USD per million tokens, input and output, each with the date it was taken and where
from. They feed the bench's cost column, so a price changes only with a new date and source.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from pydantic import SecretStr

    from murshid.providers.base import LLMProvider
    from murshid.settings import Settings

# The zero-key default first: menus and error messages list the kinds in this order.
ProviderKind = Literal["extractive", "replay", "mock", "claude", "openai", "gemini"]
PROVIDER_KINDS: tuple[ProviderKind, ...] = get_args(ProviderKind)
ZERO_KEY_KINDS: tuple[ProviderKind, ...] = ("extractive", "replay", "mock")
PAID_KINDS: tuple[ProviderKind, ...] = ("claude", "openai", "gemini")

# ---------------------------------------------------------------------------
# Model ids
# ---------------------------------------------------------------------------

# What each kind runs when no model id is given. For `replay` it is the recorded model to replay,
# as `<provider>/<model id>` the bench wrote it (the bench's best: openai, read with critic off).
# Gemini's Pro tier is gemini-3.1-pro-preview: gemini-3-pro-preview was shut down 2026-03-09.
DEFAULT_MODEL_IDS: dict[ProviderKind, str] = {
    "mock": "mock-1",
    "extractive": "extractive-1",
    "replay": "openai/gpt-5.5-2026-04-23",
    "claude": "claude-sonnet-4-6",
    "openai": "gpt-5.5-2026-04-23",
    "gemini": "gemini-3.1-pro-preview",
}

# The bench judge: out of family for the Claude and OpenAI answers it scores.
DEFAULT_JUDGE_MODEL_ID = "gemini-2.5-flash"
# The second judge of the 3-case sanity swap, also the fallback judge when the first has no key.
DEFAULT_SANITY_SWAP_JUDGE_MODEL_ID = "claude-opus-4-7"

# The models the UI offers and `scripts/verify_keys.py --all-models` checks, default first.
OFFERED_MODEL_IDS: dict[ProviderKind, tuple[str, ...]] = {
    "mock": ("mock-1",),
    "extractive": ("extractive-1",),
    "replay": ("openai/gpt-5.5-2026-04-23", "claude/claude-sonnet-4-6"),
    "claude": ("claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"),
    "openai": ("gpt-5.5-2026-04-23", "gpt-5.4-mini-2026-03-17"),
    "gemini": ("gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-flash"),
}

# Gemini 2.5 models think by default, and their thinking tokens count against the output budget:
# with no cap, a judge asked for JSON can spend the whole budget thinking and return nothing.
# These are the thinking-budget limits each one accepts (Gemini API thinking guide). The Gemini
# provider caps thinking at half the output budget, within these limits. Gemini 3 models take a
# thinking level instead and are left at their default.
GEMINI_THINKING_BUDGET_LIMITS: dict[str, tuple[int, int]] = {
    "gemini-2.5-pro": (128, 32768),
    "gemini-2.5-flash": (0, 24576),
}

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens, with the date the price was taken and its source."""

    input_usd_per_mtok: float
    output_usd_per_mtok: float
    as_of: str
    source: str

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_usd_per_mtok + output_tokens * self.output_usd_per_mtok
        ) / 1_000_000


_ANTHROPIC_DOCS = "Anthropic models documentation (pricing table)"
_GOOGLE_DOCS = (
    "Google AI pricing page, as estimated for the 2026-05 bench runs; verify before accounting"
)
_OPENAI_ESTIMATE = (
    "estimate made for the 2026-05 bench runs, a conservative upper bound: no published GPT-5.x "
    "price table was cited"
)

PRICES: dict[ProviderKind, dict[str, ModelPrice]] = {
    "claude": {
        "claude-opus-4-7": ModelPrice(5.00, 25.00, "2026-05-22", _ANTHROPIC_DOCS),
        "claude-opus-4-6": ModelPrice(5.00, 25.00, "2026-05-22", _ANTHROPIC_DOCS),
        "claude-sonnet-4-6": ModelPrice(3.00, 15.00, "2026-05-22", _ANTHROPIC_DOCS),
        "claude-sonnet-4-5-20250929": ModelPrice(3.00, 15.00, "2026-05-22", _ANTHROPIC_DOCS),
        "claude-haiku-4-5-20251001": ModelPrice(1.00, 5.00, "2026-05-22", _ANTHROPIC_DOCS),
        "claude-haiku-4-5": ModelPrice(1.00, 5.00, "2026-05-22", _ANTHROPIC_DOCS),
    },
    "openai": {
        "gpt-5.5-2026-04-23": ModelPrice(5.00, 15.00, "2026-05-23", _OPENAI_ESTIMATE),
        "gpt-5.4-mini-2026-03-17": ModelPrice(1.00, 3.00, "2026-05-23", _OPENAI_ESTIMATE),
        "gpt-4.1": ModelPrice(2.00, 8.00, "2026-05-23", _OPENAI_ESTIMATE),
        "gpt-4o": ModelPrice(2.50, 10.00, "2026-05-23", _OPENAI_ESTIMATE),
    },
    "gemini": {
        "gemini-3.1-pro-preview": ModelPrice(2.50, 10.00, "2026-05-22", _GOOGLE_DOCS),
        "gemini-3-flash-preview": ModelPrice(0.30, 2.50, "2026-05-22", _GOOGLE_DOCS),
        "gemini-2.5-pro": ModelPrice(1.25, 5.00, "2026-05-22", _GOOGLE_DOCS),
        "gemini-2.5-flash": ModelPrice(0.075, 0.30, "2026-05-22", _GOOGLE_DOCS),
        "gemini-2.5-flash-lite": ModelPrice(0.05, 0.20, "2026-05-22", _GOOGLE_DOCS),
    },
}

# A model id the table does not know is priced like the kind's default tier, so a new model id
# never logs a cost of zero.
FALLBACK_PRICES: dict[ProviderKind, ModelPrice] = {
    "claude": ModelPrice(3.00, 15.00, "2026-05-22", "unknown Claude model, priced as Sonnet"),
    "openai": ModelPrice(5.00, 15.00, "2026-05-23", "unknown OpenAI model, priced as gpt-5.5"),
    "gemini": ModelPrice(2.50, 10.00, "2026-05-22", "unknown Gemini model, priced as 3.1 Pro"),
}

# The zero-key kinds make no API call.
FREE = ModelPrice(0.0, 0.0, "2026-11-06", "no API call")


def price_for(kind: ProviderKind, model_id: str) -> ModelPrice:
    """The price of one model: its table entry, the kind's fallback, or free for zero-key kinds."""
    if kind in ZERO_KEY_KINDS:
        return FREE
    return PRICES[kind].get(model_id, FALLBACK_PRICES[kind])


def has_listed_price(kind: ProviderKind, model_id: str) -> bool:
    """True when the model has its own dated price (zero-key kinds are free by definition)."""
    return kind in ZERO_KEY_KINDS or model_id in PRICES[kind]


# ---------------------------------------------------------------------------
# Kinds, keys and SDKs
# ---------------------------------------------------------------------------

# The distribution that installs each paid kind's SDK, and the setting that holds its key.
_SDK_DISTRIBUTIONS: dict[ProviderKind, str] = {
    "claude": "anthropic",
    "openai": "openai",
    "gemini": "google-genai",
}
KEY_SETTINGS: dict[ProviderKind, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
# Model id prefixes, for a judge model named only by its id.
_MODEL_ID_PREFIXES: tuple[tuple[str, ProviderKind], ...] = (
    ("claude-", "claude"),
    ("gpt-", "openai"),
    ("gemini-", "gemini"),
)


def sdk_installed(kind: ProviderKind) -> bool:
    """True when the kind needs no SDK or its SDK is installed.

    Reads the installed distributions' metadata, so it imports nothing: even looking up
    `google.genai` with `importlib.util.find_spec` would import the `google` package.
    """
    distribution = _SDK_DISTRIBUTIONS.get(kind)
    if distribution is None:
        return True
    try:
        importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def api_key(kind: ProviderKind, settings: Settings) -> str:
    """The kind's API key from the settings, or "" when unset or for a zero-key kind."""
    secrets: dict[ProviderKind, SecretStr | None] = {
        "claude": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
    }
    secret = secrets.get(kind)
    return secret.get_secret_value().strip() if secret is not None else ""


def available_kinds(settings: Settings) -> list[ProviderKind]:
    """The kinds that can answer now, in `PROVIDER_KINDS` order.

    A zero-key kind is always available, except `replay` without its recorded-answers file. A
    paid kind is available only when its key is set and its SDK is installed.
    """
    available: list[ProviderKind] = []
    for kind in PROVIDER_KINDS:
        if kind == "replay":
            if settings.murshid_replay_file.is_file():
                available.append(kind)
        elif kind in ZERO_KEY_KINDS or (api_key(kind, settings) and sdk_installed(kind)):
            available.append(kind)
    return available


def availability_hint(kind: ProviderKind) -> str:
    """What makes an unavailable provider of `kind` available, for a message to the person."""
    if kind in KEY_SETTINGS:
        return (
            f"set {KEY_SETTINGS[kind]} and install the providers extra (uv sync --extra providers)"
        )
    if kind == "replay":
        return "point MURSHID_REPLAY_FILE at a bench case cache that recorded MURSHID_REPLAY_MODEL"
    return "nothing: it needs no key"


def kind_for_model_id(model_id: str) -> ProviderKind | None:
    """The paid kind that serves `model_id`: the price table first, then the id's prefix."""
    for kind in PAID_KINDS:
        if model_id in PRICES[kind] or model_id in OFFERED_MODEL_IDS[kind]:
            return kind
    for prefix, kind in _MODEL_ID_PREFIXES:
        if model_id.startswith(prefix):
            return kind
    return None


def configured_model_id(kind: ProviderKind, settings: Settings) -> str:
    """The model id the settings choose for `kind` (the registry default unless overridden)."""
    configured: dict[ProviderKind, str] = {
        "replay": settings.murshid_replay_model,
        "claude": settings.anthropic_model_id,
        "openai": settings.openai_model_id,
        "gemini": settings.gemini_model_id,
    }
    return configured.get(kind, DEFAULT_MODEL_IDS[kind])


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _build_mock(model_id: str, settings: Settings) -> LLMProvider:
    from murshid.providers.mock import MockProvider

    return MockProvider()


def _build_extractive(model_id: str, settings: Settings) -> LLMProvider:
    from murshid.providers.extractive import ExtractiveProvider

    return ExtractiveProvider()


def _build_replay(model_id: str, settings: Settings) -> LLMProvider:
    from murshid.providers.replay import ReplayProvider

    return ReplayProvider(
        model_id,
        replay_file=settings.murshid_replay_file,
        data_dir=settings.murshid_data_dir,
    )


def _build_claude(model_id: str, settings: Settings) -> LLMProvider:
    from murshid.providers.claude import ClaudeProvider

    return ClaudeProvider(model_id, api_key=api_key("claude", settings))


def _build_openai(model_id: str, settings: Settings) -> LLMProvider:
    from murshid.providers.openai import OpenAIProvider

    return OpenAIProvider(model_id, api_key=api_key("openai", settings))


def _build_gemini(model_id: str, settings: Settings) -> LLMProvider:
    from murshid.providers.gemini import GeminiProvider

    return GeminiProvider(model_id, api_key=api_key("gemini", settings))


_BUILDERS: dict[ProviderKind, Callable[[str, Settings], LLMProvider]] = {
    "mock": _build_mock,
    "extractive": _build_extractive,
    "replay": _build_replay,
    "claude": _build_claude,
    "openai": _build_openai,
    "gemini": _build_gemini,
}


def as_kind(kind: str) -> ProviderKind:
    """`kind` as a ProviderKind, or a ValueError that lists the kinds."""
    for known in PROVIDER_KINDS:
        if kind == known:
            return known
    raise ValueError(
        f"unknown provider kind {kind!r}; expected one of: {', '.join(PROVIDER_KINDS)}"
    )


def build_provider(
    kind: str,
    model_id: str | None = None,
    settings: Settings | None = None,
) -> LLMProvider:
    """Build the provider of `kind`, with `model_id` or the one the settings choose.

    The mock and extractive kinds have one model each; another model id for them is an error.
    Building never calls the network: a paid provider without a key builds, and reports
    `is_available() == False`.
    """
    resolved = as_kind(kind)
    if settings is None:
        from murshid.settings import get_settings  # that module imports this one

        settings = get_settings()
    chosen = model_id or configured_model_id(resolved, settings)
    if resolved in ("mock", "extractive") and chosen != DEFAULT_MODEL_IDS[resolved]:
        raise ValueError(f"the {resolved} provider has one model, {DEFAULT_MODEL_IDS[resolved]}")
    return _BUILDERS[resolved](chosen, settings)


def build_enrichment_provider(settings: Settings | None = None) -> LLMProvider:
    """The provider that writes each chunk's summary and keywords when an index is built."""
    if settings is None:
        from murshid.settings import get_settings  # that module imports this one

        settings = get_settings()
    return build_provider(
        settings.metadata_enrichment_provider,
        settings.metadata_enrichment_model_id,
        settings,
    )


def build_judge(model_id: str, settings: Settings | None = None) -> LLMProvider:
    """A judge named by its model id alone (`BENCH_JUDGE_MODEL`, the sanity-swap judge)."""
    kind = kind_for_model_id(model_id)
    if kind is None:
        raise ValueError(f"no provider kind serves the judge model {model_id!r}")
    return build_provider(kind, model_id, settings)


def model_menu(settings: Settings) -> list[tuple[ProviderKind, str]]:
    """The (kind, model id) pairs a person can pick from now: available kinds only.

    Each kind lists the model the settings choose first, then the other offered models.
    """
    menu: list[tuple[ProviderKind, str]] = []
    for kind in available_kinds(settings):
        first = configured_model_id(kind, settings)
        for model in (first, *OFFERED_MODEL_IDS[kind]):
            if (kind, model) not in menu:
                menu.append((kind, model))
    return menu

# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Verify configured API keys with one minimal call per paid provider.

Reads the settings (`.env` or the environment), builds each paid provider through the registry
(`murshid.providers.factory`), and sends one tiny generation through the same provider class the
pipeline uses, so the check covers the real request path: client, timeout, retries, response
parsing. It reports success or failure per provider. It never prints a key, and masks any
auth-token-shaped string that leaks into an error message.

This makes real, billed calls (a few tokens each). Nothing in the test suite runs it.

Usage:
  uv run python scripts/verify_keys.py                # ping the configured model per provider
  uv run python scripts/verify_keys.py --all-models   # also ping every offered model
                                                      # (8 calls, ~$0.01)

The --all-models list is the registry's `OFFERED_MODEL_IDS`, the same models scripts/ui.py offers;
useful for confirming exactly which model ids your account/region/quota can actually reach before
kicking off a paid bench run.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from murshid.providers.factory import (  # noqa: E402
    KEY_SETTINGS,
    OFFERED_MODEL_IDS,
    PAID_KINDS,
    ProviderKind,
    api_key,
    build_provider,
    configured_model_id,
)
from murshid.settings import Settings, SettingsError, get_settings  # noqa: E402

_PING_SYSTEM = "You are a connectivity check."
_PING_USER = "Reply with just the word OK."

_DISPLAY_NAMES: dict[ProviderKind, str] = {
    "claude": "Anthropic Claude",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
}

# Any auth-token-shaped string in error messages gets masked before printing.
_TOKEN_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"AIza[A-Za-z0-9_-]+"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
    re.compile(r"sk-proj-[A-Za-z0-9_-]+"),
]


def _sanitize(msg: str) -> str:
    out = msg
    for pat in _TOKEN_PATTERNS:
        out = pat.sub("<REDACTED>", out)
    return out


def _short(s: str, n: int = 240) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "..."


def ping(kind: ProviderKind, model_id: str, settings: Settings) -> tuple[bool, str]:
    """One minimal call to `model_id` through the provider class. Returns (ok, message)."""
    if not api_key(kind, settings):
        return False, f"no {KEY_SETTINGS[kind]} set"
    provider = build_provider(kind, model_id, settings)
    if not provider.is_available():
        return False, "the SDK is not installed: uv sync --extra providers"
    try:
        resp = provider.generate(system=_PING_SYSTEM, user=_PING_USER, max_tokens=20, timeout=30.0)
    except Exception as e:
        return False, f"{type(e).__name__}: {_sanitize(_short(str(e)))}"
    return True, (
        f"model={model_id} | reply={resp.text.strip()!r} | finish={resp.finish_reason} | "
        f"tokens_in={resp.input_tokens} tokens_out={resp.output_tokens}"
    )


def verify(kind: ProviderKind, settings: Settings) -> tuple[bool, str]:
    """Ping the configured model; for Gemini, fall back to the other offered models.

    Gemini Pro is often gated by quota where Flash is not, so a failed default is retried on the
    registry's other Gemini models, and the default's error is reported alongside.
    """
    model = configured_model_id(kind, settings)
    ok, msg = ping(kind, model, settings)
    if ok or kind != "gemini" or not api_key(kind, settings):
        return ok, msg
    for fallback_model in OFFERED_MODEL_IDS[kind]:
        if fallback_model == model:
            continue
        fallback_ok, fallback_msg = ping(kind, fallback_model, settings)
        if fallback_ok:
            return True, f"{fallback_msg}  [PRIMARY {model} FAILED: {msg}]"
    return False, msg


def verify_all_models(settings: Settings) -> list[tuple[str, str, bool, str]]:
    """Ping every offered paid model. Returns (kind, model, ok, msg)."""
    out: list[tuple[str, str, bool, str]] = []
    for kind in PAID_KINDS:
        for m in OFFERED_MODEL_IDS[kind]:
            ok, msg = ping(kind, m, settings)
            print(f"  [{'OK ' if ok else 'FAIL'}] {kind:7s} {m:34s} {_sanitize(_short(msg, 120))}")
            out.append((kind, m, ok, msg))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify API keys + (optionally) model availability."
    )
    parser.add_argument(
        "--all-models",
        action="store_true",
        help="Also ping each offered model (8 extra calls, ~$0.01).",
    )
    args = parser.parse_args()

    try:
        settings = get_settings()
    except SettingsError as e:
        print(e)
        return 2

    print("Verifying configured API keys (no key leakage)...")
    print()

    results: list[tuple[str, bool, str]] = []
    for kind in PAID_KINDS:
        name = _DISPLAY_NAMES[kind]
        ok, msg = verify(kind, settings)
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {name}: {_sanitize(msg)}")
        results.append((name, ok, msg))

    print()
    print("Summary (configured model per provider):")
    for name, ok, _ in results:
        print(f"  {name:25s} {'OK' if ok else 'FAILED'}")

    if args.all_models:
        print()
        print("Pinging every offered model (matches scripts/ui.py)...")
        print()
        all_results = verify_all_models(settings)
        print()
        print("Summary (per-model availability):")
        n_ok = sum(1 for _, _, ok, _ in all_results if ok)
        n_total = len(all_results)
        print(f"  {n_ok}/{n_total} models reachable")
        for kind, m, ok, _ in all_results:
            print(f"    {kind:7s} {m:34s} {'OK' if ok else 'FAILED'}")

    failed = [name for name, ok, _ in results if not ok]
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())

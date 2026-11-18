"""Verify configured API keys with one minimal call per provider.

Loads `.env`, runs a small generation against each provider's default model,
and reports success / failure. Never prints the raw key — masks any
auth-token-shaped string that leaks into an error message.

Usage:
  python scripts/verify_keys.py                # ping default model per provider
  python scripts/verify_keys.py --all-models   # also ping each model in the
                                               # inventory (8 calls, ~$0.01)

The --all-models option matches the model dropdown surfaced by scripts/ui.py;
useful for confirming exactly which model IDs your account/region/quota can
actually reach before kicking off a paid bench run.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)


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


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------

def verify_anthropic(model_id: str | None = None) -> tuple[bool, str]:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = (model_id or os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")).strip()
    if not key:
        return False, "no ANTHROPIC_API_KEY set"
    try:
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=model,
            max_tokens=20,
            messages=[{"role": "user", "content": "Reply with just the word OK."}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text")).strip()
        return True, (
            f"model={model} | reply={text!r} | "
            f"tokens_in={resp.usage.input_tokens} tokens_out={resp.usage.output_tokens}"
        )
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {_sanitize(_short(str(e)))}"


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def verify_openai(model_id: str | None = None) -> tuple[bool, str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = (model_id or os.environ.get("OPENAI_MODEL_ID", "gpt-5.5-2026-04-23")).strip()
    if not key:
        return False, "no OPENAI_API_KEY set"
    try:
        from openai import OpenAI  # noqa: PLC0415

        client = OpenAI(api_key=key)
        # GPT-5.x uses `max_completion_tokens` (new responses-API convention).
        # GPT-4.x style `max_tokens` is rejected by gpt-5.5.
        resp = client.chat.completions.create(
            model=model,
            max_completion_tokens=20,
            messages=[{"role": "user", "content": "Reply with just the word OK."}],
        )
        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        return True, (
            f"model={model} | reply={text!r} | "
            f"tokens_in={usage.prompt_tokens} tokens_out={usage.completion_tokens}"
        )
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {_sanitize(_short(str(e)))}"


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

def _try_gemini_model(key: str, model: str) -> tuple[bool, str]:
    """One ping against a specific Gemini model."""
    import google.generativeai as genai  # noqa: PLC0415

    genai.configure(api_key=key)
    gmodel = genai.GenerativeModel(model)
    resp = gmodel.generate_content(
        "Reply with just the word OK.",
        generation_config={"max_output_tokens": 20, "temperature": 0.0},
    )
    text = (resp.text or "").strip()
    usage = getattr(resp, "usage_metadata", None)
    token_str = (
        f"tokens_in={usage.prompt_token_count} tokens_out={usage.candidates_token_count}"
        if usage
        else "tokens=n/a"
    )
    return True, f"model={model} | reply={text!r} | {token_str}"


def verify_gemini(model_id: str | None = None) -> tuple[bool, str]:
    """Ping a Gemini model. When model_id is None, use the configured default
    and fall back to Flash if Pro is gated. When model_id is explicit, ping
    only that model and report whatever the API returns."""
    key = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        return False, "no GEMINI_API_KEY set"

    if model_id is not None:
        # Explicit model: no fallback. Report exactly what this model does.
        try:
            return _try_gemini_model(key, model_id)
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {_sanitize(_short(str(e)))}"

    model = os.environ.get("GEMINI_MODEL_ID", "gemini-3.1-pro-preview").strip()
    # First try the configured (Pro by default) model.
    try:
        return _try_gemini_model(key, model)
    except Exception as e:  # noqa: BLE001
        primary_err = f"{type(e).__name__}: {_sanitize(_short(str(e)))}"

    # Fallback: Flash variants commonly available on free tier.
    for fallback_model in ("gemini-3-flash-preview", "gemini-2.5-flash"):
        try:
            ok, msg = _try_gemini_model(key, fallback_model)
            return True, f"{msg}  [PRIMARY {model} FAILED: {primary_err}]"
        except Exception:  # noqa: BLE001
            continue

    return False, primary_err


# ---------------------------------------------------------------------------
# Model inventory (matches scripts/ui.py dropdown — keeps a single source of
# truth visible to reviewers about exactly which model IDs the project knows
# how to call).
# ---------------------------------------------------------------------------

MODEL_INVENTORY: dict[str, list[str]] = {
    "claude": [
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-haiku-4-5-20251001",
    ],
    "openai": [
        "gpt-5.5-2026-04-23",
        "gpt-5.4-mini-2026-03-17",
    ],
    "gemini": [
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
    ],
}

_VERIFY_BY_KIND = {
    "claude": verify_anthropic,
    "openai": verify_openai,
    "gemini": verify_gemini,
}


def verify_all_models() -> list[tuple[str, str, bool, str]]:
    """Ping every model in MODEL_INVENTORY. Returns (kind, model, ok, msg)."""
    out: list[tuple[str, str, bool, str]] = []
    for kind, models in MODEL_INVENTORY.items():
        for m in models:
            ok, msg = _VERIFY_BY_KIND[kind](model_id=m)
            print(f"  [{'OK ' if ok else 'FAIL'}] {kind:7s} {m:34s} {_sanitize(_short(msg, 120))}")
            out.append((kind, m, ok, msg))
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Verify API keys + (optionally) model availability.")
    parser.add_argument(
        "--all-models",
        action="store_true",
        help="Also ping each model in MODEL_INVENTORY (8 extra calls, ~$0.01).",
    )
    args = parser.parse_args()

    print("Verifying configured API keys (no key leakage)...")
    print()

    providers: list[tuple[str, callable]] = [
        ("Anthropic Claude", verify_anthropic),
        ("OpenAI", verify_openai),
        ("Google Gemini", verify_gemini),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, fn in providers:
        ok, msg = fn()
        marker = "OK " if ok else "FAIL"
        print(f"  [{marker}] {name}: {_sanitize(msg)}")
        results.append((name, ok, msg))

    print()
    print("Summary (configured default per provider):")
    for name, ok, _ in results:
        print(f"  {name:25s} {'OK' if ok else 'FAILED'}")

    if args.all_models:
        print()
        print("Pinging every model in inventory (matches scripts/ui.py dropdown)...")
        print()
        all_results = verify_all_models()
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

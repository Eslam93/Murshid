# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Importing Murshid imports no vendor SDK.

The paid providers' SDKs (anthropic, openai, google-genai) are an optional extra, and each is
imported only when its provider makes its first call. A fresh interpreter imports the package,
the pipeline, the settings, the registry and every provider module, builds every kind of provider
with a fake key and asks each whether it is available, and then must hold no module of any SDK.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from murshid.providers.factory import PAID_KINDS, PROVIDER_KINDS, sdk_installed

ROOT = Path(__file__).resolve().parents[1]
VENDOR_PACKAGES = ("anthropic", "openai", "google")

_PROBE = """
import json, sys
{extra_import}
import murshid, murshid.pipeline
imported_by_the_pipeline = sorted(
    name for name in sys.modules if name.split(".")[0] in {vendors}
)
import murshid.settings, murshid.providers, murshid.bench.runner
from murshid.providers.factory import PROVIDER_KINDS, available_kinds, build_provider
from murshid.settings import Settings, load_settings
settings = load_settings(
    Settings,
    _env_file=None,
    anthropic_api_key="sk-ant-test-fake",
    openai_api_key="sk-test-fake",
    gemini_api_key="test-fake",
    murshid_data_dir={data!r},
    murshid_replay_file={replay!r},
)
built = [build_provider(kind, settings=settings).is_available() for kind in PROVIDER_KINDS]
available = available_kinds(settings)
print(json.dumps({{
    "pipeline": imported_by_the_pipeline,
    "everything": sorted(name for name in sys.modules if name.split(".")[0] in {vendors}),
    "available": available,
    "built": built,
}}))
"""


def _probe(tmp_path: Path, extra_import: str = "") -> dict[str, Any]:
    script = _PROBE.format(
        extra_import=extra_import,
        vendors=set(VENDOR_PACKAGES),
        data=str(ROOT / "data"),
        replay=str(ROOT / "bench" / "case-cache.json"),
    )
    # A clean environment and an empty working directory: no .env, no key, nothing inherited.
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE"}
    }
    result = subprocess.run(  # noqa: S603 - this interpreter and a fixed script, no shell
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
        env=environment,
        timeout=120,
    )
    report: dict[str, Any] = json.loads(result.stdout)
    return report


def test_importing_murshid_and_building_providers_imports_no_vendor_sdk(tmp_path: Path) -> None:
    report = _probe(tmp_path)
    assert report["pipeline"] == []
    assert report["everything"] == []
    # The probe really built and checked every provider; a paid one is available where its SDK
    # is installed (CI installs the providers extra).
    installed = [kind for kind in PAID_KINDS if sdk_installed(kind)]
    assert report["available"] == ["extractive", "replay", "mock", *installed]
    assert report["built"] == [
        kind not in PAID_KINDS or sdk_installed(kind) for kind in PROVIDER_KINDS
    ]


def test_the_probe_sees_an_sdk_that_is_imported(tmp_path: Path) -> None:
    """The control: the same probe, with an SDK imported first, reports it."""
    pytest.importorskip("anthropic")
    report = _probe(tmp_path, extra_import="import anthropic")
    assert "anthropic" in report["pipeline"]
    assert "anthropic" in report["everything"]

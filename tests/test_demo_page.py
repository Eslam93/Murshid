# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""The static demo page: built from the recorded run only, labelled as recorded, and current.

`scripts/build_demo_page.py` renders `docs/demo/index.html` from `bench/case-cache.json` and
`bench/run-manifest.json`. These tests rebuild it and compare it with the committed page, so the
page cannot drift from the recording; and they pin that it runs no script and fetches nothing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "demo" / "index.html"


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_demo_page", ROOT / "scripts" / "build_demo_page.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build() -> str:
    builder = _builder()
    raw = (ROOT / "bench" / "case-cache.json").read_bytes()
    manifest = json.loads((ROOT / "bench" / "run-manifest.json").read_text(encoding="utf-8"))
    page: str = builder.build_page(
        json.loads(raw.decode("utf-8")), manifest, ROOT / "data", hashlib.sha256(raw).hexdigest()
    )
    return page


def test_the_committed_page_is_what_the_recording_builds() -> None:
    committed = PAGE.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    assert committed == _build(), "run `uv run python scripts/build_demo_page.py` and commit"


def test_the_page_says_it_shows_recorded_synthetic_data() -> None:
    page = _build()
    assert "Recorded data, not a live system." in page
    assert "recorded on 2026-05-23" in page
    assert "The corpus is synthetic." in page
    assert "the items the rules were tuned on" in page


def test_the_page_runs_no_script_and_fetches_nothing() -> None:
    page = _build()
    assert "<script" not in page.lower()
    assert not re.search(r"""\b(src|srcset)\s*=""", page)
    assert "@import" not in page and "url(" not in page
    assert not re.search(r"<link\b", page, re.IGNORECASE)


def test_every_real_provider_cell_is_on_the_page() -> None:
    page = _build()
    cases = json.loads((ROOT / "bench" / "case-cache.json").read_text(encoding="utf-8"))
    real = [c for c in cases if c["provider_name"] in ("claude", "openai")]
    assert page.count('<article class="cell">') == len(real) == 104
    assert page.count("<details ") == 26
    assert "[MOCK ANSWER]" not in page, "the mock provider's placeholder answers stay off the page"


def test_answers_render_their_markdown_instead_of_showing_it() -> None:
    page = _build()
    assert "**" not in page
    assert not re.search(r"(?m)^\s*-{3,}\s*$", page), "a rule line left as text"
    assert "<strong>" in page and "<hr>" in page and "<blockquote>" in page


def test_the_markdown_renderer_escapes_before_it_formats() -> None:
    markdown = _builder()._markdown
    html = markdown("<script>alert(1)</script> **bold** <b>x</b>\n---\n> quoted\n- item")
    assert "<script>" not in html and "<b>x</b>" not in html
    assert "&lt;script&gt;" in html and "<strong>bold</strong>" in html
    assert "<hr>" in html and "<blockquote>quoted</blockquote>" in html
    assert "<ul><li>item</li></ul>" in html


def test_fact_lists_run_right_to_left_so_their_bullets_stay_in_the_card() -> None:
    page = _build()
    lists = re.findall(r'<div class="facts"><h5>[^<]*</h5>(<ul[^>]*>)', page)
    assert lists, "the page has fact lists"
    assert all('dir="' in tag for tag in lists)


def test_each_retrieved_source_is_listed_once() -> None:
    page = _build()
    lines = re.findall(r"Sources retrieved: ([^<]*)</p>", page)
    assert lines
    for line in lines:
        ids = [part.split(" (")[0].strip() for part in line.split(",")]
        assert len(ids) == len(set(ids)), line
    assert "(2 chunks)" in page

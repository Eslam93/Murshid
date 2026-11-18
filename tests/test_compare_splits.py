# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""scripts/compare_splits.py on two tiny synthetic runs: counts, intervals, rules and misses."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def compare() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "compare_splits", ROOT / "scripts" / "compare_splits.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _case(qid: str, expected: str, taken: str, *, red_team: bool = False) -> dict[str, Any]:
    return {
        "question_id": qid,
        "expected_behavior": expected,
        "behavior_taken": taken,
        "behavior_match": expected == taken,
        "is_red_team": red_team,
        "red_team_category": "prompt_injection" if red_team else "",
    }


def _write_run(folder: Path, cases: list[dict[str, Any]], reasons: dict[str, str]) -> None:
    folder.mkdir(parents=True)
    (folder / "case-cache.json").write_text(json.dumps(cases), encoding="utf-8")
    (folder / "run-manifest.json").write_text(
        json.dumps(
            {
                "git_commit": "abc123",
                "providers": [{"name": "extractive", "model_id": "e1"}],
                "critic_modes": ["off"],
            }
        ),
        encoding="utf-8",
    )
    (folder / "refusal-log.jsonl").write_text(
        "".join(
            json.dumps({"question": q, "refusal_reason": r}) + "\n" for q, r in reasons.items()
        ),
        encoding="utf-8",
    )


def _write_data(
    folder: Path, questions: list[dict[str, Any]], red_team: list[dict[str, Any]]
) -> None:
    folder.mkdir(parents=True)
    (folder / "questions.json").write_text(json.dumps(questions), encoding="utf-8")
    (folder / "red_team.json").write_text(json.dumps(red_team), encoding="utf-8")


def test_the_report_keeps_the_splits_apart_and_lists_every_miss(
    compare: ModuleType, tmp_path: Path
) -> None:
    question = {"register": "dialect", "dialect_family": "hijazi"}
    _write_data(
        tmp_path / "tuned-data",
        [{"question_id": "q-1", "text": "س1", **question, "expected_behavior": "answer"}],
        [{"case_id": "rt-1", "question_text": "ر1", "category": "out_of_scope", "register": "MSA"}],
    )
    _write_data(
        tmp_path / "heldout-data",
        [
            {"question_id": "h-1", "text": "س2", **question, "expected_behavior": "answer"},
            {
                "question_id": "h-2",
                "text": "س3",
                **question,
                "expected_behavior": "refuse_with_redirect",
            },
        ],
        [
            {
                "case_id": "hr-1",
                "question_text": "ر2",
                "category": "prompt_injection",
                "register": "MSA",
            }
        ],
    )
    _write_run(tmp_path / "tuned", [_case("q-1", "answer", "answer")], {})
    _write_run(
        tmp_path / "heldout",
        [
            _case("h-1", "answer", "ask_clarification"),
            _case("h-2", "refuse_with_redirect", "answer"),
            _case("hr-1", "answer", "answer", red_team=True),
        ],
        {"س2": "soft out-of-scope: no in-corpus category matched (confidence 0.50)"},
    )
    report = compare.build_report(
        tmp_path / "tuned", tmp_path / "heldout", tmp_path / "tuned-data", tmp_path / "heldout-data"
    )
    assert "| tuned (" in report and "| held-out (" in report
    assert "1 / 3 (33%" in report, "the held-out row counts its own cells only"
    assert "router: no category matched" in report
    assert "no rule fired (answer path)" in report
    assert "## Held-out: the 2 cells that missed" in report
    assert "prompt_injection *" in report, "a category the tuned set lacks is starred"


def test_wilson_interval_bounds(compare: ModuleType) -> None:
    lo, hi = compare.wilson(26, 26)
    assert hi == pytest.approx(1.0)
    assert 0.86 < lo < 0.88
    assert compare.wilson(0, 0) == (0.0, 0.0)

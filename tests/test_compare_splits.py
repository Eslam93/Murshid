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
    assert "Answer quality" not in report, "a run with no judge scores gets no quality section"


def test_judged_runs_get_their_scores_side_by_side(compare: ModuleType, tmp_path: Path) -> None:
    question = {"register": "MSA", "dialect_family": "none", "expected_behavior": "answer"}
    _write_data(
        tmp_path / "tuned-data",
        [{"question_id": "q-1", "text": "س1", **question}],
        [{"case_id": "rt-1", "question_text": "ر1", "category": "out_of_scope", "register": "MSA"}],
    )
    _write_data(
        tmp_path / "heldout-data",
        [
            {"question_id": "h-1", "text": "س2", **question},
            {"question_id": "h-2", "text": "س3", **question},
        ],
        [],
    )
    scored = {"correctness_score": 3, "faithfulness_score": 3, "register_match_score": 3}
    tuned = [
        {**_case("q-1", "answer", "answer"), **scored},
        {
            **_case("rt-1", "refuse_with_redirect", "refuse_with_redirect", red_team=True),
            "red_team_rubric_pass": True,
            "refusal_tone_score": 2,
        },
    ]
    held = [
        {**_case("h-1", "answer", "answer"), **scored},
        {
            **_case("h-2", "answer", "answer"),
            **scored,
            "correctness_score": 1,
            "faithfulness_score": None,
            "judge_faithfulness_error": "judge_faithfulness_parse_error: JSONDecodeError",
        },
    ]
    for name, cases in (("tuned", tuned), ("heldout", held)):
        _write_run(tmp_path / name, cases, {})
        (tmp_path / name / "run-manifest.json").write_text(
            json.dumps(
                {
                    "judge_model_id": "judge-1",
                    "spend": {"spent_usd": 0.25, "paid_calls": 40},
                    "providers": [{"name": "claude", "model_id": "c1"}],
                }
            ),
            encoding="utf-8",
        )
    report = compare.build_report(
        tmp_path / "tuned", tmp_path / "heldout", tmp_path / "tuned-data", tmp_path / "heldout-data"
    )
    assert "## Answer quality, as the judge scored it" in report
    rows = {line.split(" | ")[0]: line for line in report.splitlines() if line.startswith("| ")}
    # Correctness 3 and 1: mean 2.00, sd 1.41, half-width 1.96 * 1.41 / sqrt(2) = 1.96.
    assert "| 2.00 ± 1.96 (n=2) |" in rows["| held-out"]
    assert "| 3.00 (n=1) |" in rows["| held-out"], "faithfulness rests on the one scored cell"
    assert "| 1 | $0.25 over 40 calls |" in rows["| held-out"], "one judge error, the spend"
    assert "1 / 1 (100%" in rows["| tuned"], "the tuned red-team case passed its rubric"
    assert "## Held-out: the 1 cells scored 1 or 0 for correctness" in report
    assert "| h-2 | answer | answer | 1 | — | س3 |" in report


def test_wilson_interval_bounds(compare: ModuleType) -> None:
    lo, hi = compare.wilson(26, 26)
    assert hi == pytest.approx(1.0)
    assert 0.86 < lo < 0.88
    assert compare.wilson(0, 0) == (0.0, 0.0)

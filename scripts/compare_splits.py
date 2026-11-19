# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Report two bench runs side by side: the tuned split and the held-out split, never pooled.

    uv run python scripts/compare_splits.py \\
        --tuned bench/rules-only/tuned --heldout bench/rules-only/heldout \\
        --out bench/rules-only/REPORT.md

Each folder is one bench run (`case-cache.json`, `refusal-log.jsonl`, `run-manifest.json`).
The report gives, for each split, how many cells took the expected behavior (with a 95% Wilson
interval), then for the held-out split the table of expected against taken behavior, the results
by expected behavior, register, dialect family and red-team category, which rule decided each
cell, and every cell that missed. When a run was judged, it also gives each split's judge scores
(means with a 95% interval, the red-team rubric pass rate, judge errors, the logged spend) and the
held-out answers the judge scored lowest for correctness. It reads recorded output only; it runs
nothing.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BEHAVIORS = (
    "answer",
    "partial_answer_with_escalation",
    "refuse_with_redirect",
    "ask_clarification",
)
SHORT = {
    "answer": "answer",
    "partial_answer_with_escalation": "partial",
    "refuse_with_redirect": "refuse",
    "ask_clarification": "clarify",
    "error": "error",
}
# The judge's scores, each 0 to 3, and the columns that report them.
SCORES = (
    ("correctness_score", "Correctness"),
    ("faithfulness_score", "Faithfulness"),
    ("register_match_score", "Register match"),
    ("refusal_tone_score", "Refusal tone"),
)
JUDGE_ERRORS = (
    "judge_correctness_error",
    "judge_faithfulness_error",
    "judge_refusal_tone_error",
    "judge_red_team_error",
)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The 95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    pct = 100 * k / n if n else 0.0
    return f"{k} / {n} ({pct:.0f}%; 95% CI {100 * lo:.0f}–{100 * hi:.0f}%)"


def mean_interval(values: list[float]) -> str:
    """The mean, a 95% normal-approximation half-width, and how many values it rests on."""
    n = len(values)
    if n == 0:
        return "—"
    mean = sum(values) / n
    if n == 1:
        return f"{mean:.2f} (n=1)"
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    return f"{mean:.2f} ± {1.96 * sd / math.sqrt(n):.2f} (n={n})"


def was_judged(cases: list[dict[str, Any]]) -> bool:
    """True when any cell of the run carries a judge score."""
    return any(c.get(key) is not None for c in cases for key in [k for k, _ in SCORES]) or any(
        c.get("red_team_rubric_pass") is not None for c in cases
    )


def section_quality(name: str, cases: list[dict[str, Any]], manifest: dict[str, Any]) -> list[str]:
    scores = [
        mean_interval([float(c[k]) for c in cases if c.get(k) is not None]) for k, _ in SCORES
    ]
    rubric = [c for c in cases if c["is_red_team"] and c.get("red_team_rubric_pass") is not None]
    passed = (
        rate(sum(bool(c["red_team_rubric_pass"]) for c in rubric), len(rubric)) if rubric else "—"
    )
    errors = sum(1 for c in cases for key in JUDGE_ERRORS if c.get(key))
    spend = manifest.get("spend") or {}
    spent = (
        f"${spend['spent_usd']:.2f} over {spend.get('paid_calls', 0)} calls"
        if spend.get("paid_calls")
        else "—"
    )
    return [
        f"| {name} | {manifest.get('judge_model_id') or '—'} | {' | '.join(scores)} | {passed} | "
        f"{errors} | {spent} |"
    ]


def load_run(folder: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """The run's cases, its manifest, and the refusal log's reason per question text."""
    cases = json.loads((folder / "case-cache.json").read_text(encoding="utf-8"))
    manifest_path = folder / "run-manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    reasons: dict[str, str] = {}
    log = folder / "refusal-log.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                reasons[row["question"]] = row.get("refusal_reason") or ""
    return cases, manifest, reasons


def load_items(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Question and red-team records of a split, by id, with a common `text` field."""
    items: dict[str, dict[str, Any]] = {}
    for q in json.loads((data_dir / "questions.json").read_text(encoding="utf-8")):
        items[q["question_id"]] = {**q, "kind": "question"}
    for r in json.loads((data_dir / "red_team.json").read_text(encoding="utf-8")):
        items[r["case_id"]] = {**r, "text": r["question_text"], "kind": "red_team"}
    return items


def decided_by(case: dict[str, Any], reason: str) -> str:
    """Which rule decided a cell, from what the run recorded."""
    taken = case["behavior_taken"]
    if taken == "error":
        return "error"
    if reason.startswith("hard out-of-scope"):
        return "router: out-of-scope trigger"
    if reason.startswith("soft out-of-scope"):
        return "router: no category matched"
    if reason.startswith("ambiguous date"):
        return "ambiguous-date check"
    if reason.startswith("low in-category"):
        return "router: low confidence"
    if reason.startswith("pre_gen_support_gate"):
        return "support gate"
    if taken == "partial_answer_with_escalation":
        return "partial-escalation terms"
    if taken == "refuse_with_redirect":
        return "critic"
    return "no rule fired (answer path)"


def section_split(name: str, cases: list[dict[str, Any]], manifest: dict[str, Any]) -> list[str]:
    total = len(cases)
    ok = sum(c["behavior_match"] for c in cases)
    qs = [c for c in cases if not c["is_red_team"]]
    rt = [c for c in cases if c["is_red_team"]]
    providers = ", ".join(f"{p['name']} ({p['model_id']})" for p in manifest.get("providers", []))
    return [
        f"| {name} | {rate(ok, total)} | {rate(sum(c['behavior_match'] for c in qs), len(qs))} | "
        f"{rate(sum(c['behavior_match'] for c in rt), len(rt))} | "
        f"{manifest.get('git_commit', '—')} | {providers or '—'} | "
        f"{', '.join(manifest.get('critic_modes', [])) or '—'} |"
    ]


def build_report(tuned_dir: Path, heldout_dir: Path, tuned_data: Path, heldout_data: Path) -> str:
    tuned, tuned_manifest, _ = load_run(tuned_dir)
    held, held_manifest, reasons = load_run(heldout_dir)
    items = load_items(heldout_data)
    lines: list[str] = []
    lines += [
        "# Tuned split and held-out split, side by side",
        "",
        "Never pooled: each row is one run of one split. Behavior match counts cells whose taken",
        "behavior equals the expected one. Intervals are 95% Wilson intervals.",
        "",
        "| Split | All cells | Questions | Red-team cases | Commit | Providers | Critic |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines += section_split(f"tuned (`{tuned_dir.as_posix()}`)", tuned, tuned_manifest)
    lines += section_split(f"held-out (`{heldout_dir.as_posix()}`)", held, held_manifest)
    lines.append("")

    if was_judged(tuned) or was_judged(held):
        lines += [
            "## Answer quality, as the judge scored it",
            "",
            "Each score is 0 to 3: the mean, ± the half-width of a 95% normal-approximation",
            "interval, and the number of cells scored. Correctness and register match need a gold",
            "answer; faithfulness is scored against the retrieved passages for the same cells;",
            "refusal tone scores every cell that did not answer. A red-team case passes its rubric",
            "at a score of 2 or more. Spend is what the run logged for every paid call.",
            "",
            "| Split | Judge | "
            + " | ".join(label for _, label in SCORES)
            + " | Red-team rubric passed | Judge errors | Spend |",
            "| --- | --- | " + " | ".join("---" for _ in SCORES) + " | --- | ---: | --- |",
        ]
        lines += section_quality("tuned", tuned, tuned_manifest)
        lines += section_quality("held-out", held, held_manifest)
        lines.append("")
        low = [
            c
            for c in held
            if c.get("correctness_score") is not None and float(c["correctness_score"]) <= 1
        ]
        lines += [
            f"## Held-out: the {len(low)} cells scored 1 or 0 for correctness",
            "",
            "| Item | Expected | Taken | Correctness | Faithfulness | Question |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
        for c in sorted(low, key=lambda c: (float(c["correctness_score"]), c["question_id"])):
            text = items.get(c["question_id"], {}).get("text", "").replace("|", "\\|")
            faith = c.get("faithfulness_score")
            lines.append(
                f"| {c['question_id']} | {SHORT[c['expected_behavior']]} | "
                f"{SHORT.get(c['behavior_taken'], c['behavior_taken'])} | "
                f"{float(c['correctness_score']):g} | {'—' if faith is None else f'{float(faith):g}'} | "
                f"{text.replace(chr(10), ' ')} |"
            )
        lines.append("")

    # Expected against taken, held-out.
    grid: Counter[tuple[str, str]] = Counter(
        (c["expected_behavior"], c["behavior_taken"]) for c in held
    )
    taken_cols = [b for b in (*BEHAVIORS, "error") if any(t == b for _, t in grid)]
    lines += [
        "## Held-out: expected behavior against the behavior taken",
        "",
        "| Expected ↓ / taken → | " + " | ".join(SHORT[t] for t in taken_cols) + " | Matched |",
        "| --- | " + " | ".join("---:" for _ in taken_cols) + " | ---: |",
    ]
    for expected in BEHAVIORS:
        row_cases = [c for c in held if c["expected_behavior"] == expected]
        if not row_cases:
            continue
        cells = " | ".join(str(grid[(expected, t)]) for t in taken_cols)
        matched = sum(c["behavior_match"] for c in row_cases)
        lines.append(f"| {SHORT[expected]} | {cells} | {rate(matched, len(row_cases))} |")
    lines.append("")

    # Which rule decided each held-out cell.
    lines += [
        "## Held-out: which rule decided each cell",
        "",
        "| Decided by | Cells | Of which matched |",
        "| --- | ---: | ---: |",
    ]
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in held:
        text = items.get(c["question_id"], {}).get("text", "")
        by_rule[decided_by(c, reasons.get(text, ""))].append(c)
    for rule, cs in sorted(by_rule.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {rule} | {len(cs)} | {sum(c['behavior_match'] for c in cs)} |")
    lines.append("")

    # Attributes.
    def table(title: str, key: Any, subset: list[dict[str, Any]]) -> None:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in subset:
            groups[key(c)].append(c)
        lines.extend([f"## Held-out: {title}", "", "| Group | Matched |", "| --- | --- |"])
        for g, cs in sorted(groups.items()):
            lines.append(f"| {g} | {rate(sum(c['behavior_match'] for c in cs), len(cs))} |")
        lines.append("")

    held_q = [c for c in held if not c["is_red_team"]]
    held_rt = [c for c in held if c["is_red_team"]]
    table("questions by expected behavior", lambda c: SHORT[c["expected_behavior"]], held_q)
    table("questions by register", lambda c: items[c["question_id"]]["register"], held_q)
    table(
        "questions by dialect family",
        lambda c: items[c["question_id"]]["dialect_family"],
        held_q,
    )
    tuned_categories = {
        r["category"]
        for r in json.loads((tuned_data / "red_team.json").read_text(encoding="utf-8"))
    }
    table(
        "red-team cases by category (* = a category the tuned set does not have)",
        lambda c: (
            c["red_team_category"] + ("" if c["red_team_category"] in tuned_categories else " *")
        ),
        held_rt,
    )

    # Every miss.
    misses = [c for c in held if not c["behavior_match"]]
    lines += [
        f"## Held-out: the {len(misses)} cells that missed",
        "",
        "| Item | Kind | Register | Expected | Taken | Decided by | Question |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in sorted(misses, key=lambda c: c["question_id"]):
        item = items.get(c["question_id"], {})
        kind = item.get("category") or item.get("kind", "")
        text = item.get("text", "").replace("|", "\\|").replace("\n", " ")
        rule = decided_by(c, reasons.get(item.get("text", ""), ""))
        lines.append(
            f"| {c['question_id']} | {kind} | {item.get('register', '')} | "
            f"{SHORT[c['expected_behavior']]} | {SHORT.get(c['behavior_taken'], c['behavior_taken'])} | "
            f"{rule} | {text} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tuned", type=Path, required=True, help="the tuned run's folder")
    parser.add_argument("--heldout", type=Path, required=True, help="the held-out run's folder")
    parser.add_argument("--tuned-data", type=Path, default=ROOT / "data")
    parser.add_argument("--heldout-data", type=Path, default=ROOT / "data" / "heldout")
    parser.add_argument("--out", type=Path, required=True, help="the report to write")
    args = parser.parse_args(argv)
    report = build_report(args.tuned, args.heldout, args.tuned_data, args.heldout_data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8", newline="\n")
    print(f"[compare] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

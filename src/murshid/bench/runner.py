# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Bench runner — entry point for `python -m murshid.bench`.

Runs the full pipeline against each available provider over the gold answers
+ remaining standard questions. Two passes per provider:
  - `--critic off`: critic LLM call skipped. Deterministic orchestration
                    (router hard/soft OOS, ambiguous-date short-circuit, and
                    the pre-generation support gate) is STILL ACTIVE per
                    `support_gate_enabled=True` default on `answer_question`.
                    For true raw-provider-without-orchestration measurement,
                    `answer_question(..., support_gate_enabled=False)` is the
                    signature-level ablation; not currently exposed as a CLI.
  - `--critic on`:  critic gate Option B active (grounded=false → refuse;
                    register-only mismatch → log + ship). All deterministic
                    orchestration runs in addition.

Plus the 3-case judge sanity swap (`BENCH_SANITY_SWAP_JUDGE_MODEL`, by default Claude Opus 4.7)
to quantify self-preference bias (re-scoring the SAME predicted answer across two judges).

Providers and judges come from the provider registry (`murshid.providers.factory`) and the
settings (`murshid.settings`): the judge is `BENCH_JUDGE_MODEL`, the data is read from
`MURSHID_DATA_DIR`, and the index is enriched by `METADATA_ENRICHMENT_PROVIDER`.

Splits: `--split tuned` (the default) scores the question sets in `data/`, which the rules were
tuned on; `--split heldout` scores `data/heldout/`, which they never saw. A run scores one split,
and each split writes to its own folder, so the two are never pooled: `bench/` for tuned and
`bench/heldout/` for held-out, unless `--out-dir` names another. A run refuses to write into a
folder that holds a run of the other split, and into any folder that holds a run at all unless
`--overwrite` is given.

Outputs, in the run's folder:
  - `results.md`         — aggregate + per-case results
  - `cost-log.jsonl`     — per-call token usage / cost (answer-call only)
  - `refusal-log.jsonl`  — per refuse/escalate/clarify response trace
  - `case-cache.json`    — per-case results for `--render-only` re-renders
  - `run-manifest.json`  — the split, the commit, the model ids, the dates and the data files'
                           sha256, so a reader can tell what produced the numbers
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, Protocol, TypedDict

# Allow `python -m murshid.bench` from the repo root.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from murshid.bench.metrics import (  # noqa: E402
    AggregateMetrics,
    CaseResult,
    GoldAnswer,
    Question,
    RedTeamCase,
    aggregate,
    dump_cases,
    evaluate_case,
    evaluate_red_team_case,
    judge_correctness,
    load_cases,
)
from murshid.ingest import Index, build_index  # noqa: E402
from murshid.pipeline import Answer, answer_question  # noqa: E402
from murshid.providers.base import LLMProvider, ProviderResponse  # noqa: E402
from murshid.providers.factory import (  # noqa: E402
    PROVIDER_KINDS,
    as_kind,
    availability_hint,
    build_enrichment_provider,
    build_judge,
    build_provider,
)
from murshid.retrieve import BM25Index, build_bm25_index  # noqa: E402
from murshid.settings import Settings, SettingsError, get_settings  # noqa: E402

BENCH_DIR = ROOT / "bench"
COST_LOG_PATH = BENCH_DIR / "cost-log.jsonl"
REFUSAL_LOG_PATH = BENCH_DIR / "refusal-log.jsonl"
RESULTS_MD_PATH = BENCH_DIR / "results.md"
CASE_CACHE_PATH = BENCH_DIR / "case-cache.json"
MANIFEST_NAME = "run-manifest.json"

# The question sets a run can score: the folder under the data directory that holds each.
SPLITS: dict[str, str] = {"tuned": "", "heldout": "heldout"}
# How the results page names each split.
SPLIT_LABELS: dict[str, str] = {
    "tuned": "tuned (`data/`, the items the rules were tuned on)",
    "heldout": "heldout (`data/heldout/`, items the rules never saw)",
}
# What `ingest.build_index` embeds the corpus with.
EMBEDDER_MODEL_ID = "BAAI/bge-m3"


@dataclass(frozen=True)
class RunPaths:
    """Where one bench run writes its results, case cache, logs and manifest."""

    out_dir: Path
    results_md: Path
    case_cache: Path
    cost_log: Path
    refusal_log: Path
    manifest: Path


def run_paths(split: str, out_dir: Path | None = None) -> RunPaths:
    """A run's files: under `out_dir` if given, else `bench/` (tuned) or `bench/heldout/`."""
    if out_dir is None and split == "tuned":
        return RunPaths(
            out_dir=BENCH_DIR,
            results_md=RESULTS_MD_PATH,
            case_cache=CASE_CACHE_PATH,
            cost_log=COST_LOG_PATH,
            refusal_log=REFUSAL_LOG_PATH,
            manifest=BENCH_DIR / MANIFEST_NAME,
        )
    base = out_dir if out_dir is not None else BENCH_DIR / SPLITS[split]
    return RunPaths(
        out_dir=base,
        results_md=base / "results.md",
        case_cache=base / "case-cache.json",
        cost_log=base / "cost-log.jsonl",
        refusal_log=base / "refusal-log.jsonl",
        manifest=base / MANIFEST_NAME,
    )


def split_data_dir(data_dir: Path, split: str) -> Path:
    """The folder that holds a split's questions, gold answers and red-team cases."""
    return data_dir / SPLITS[split] if SPLITS[split] else data_dir


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def build_providers(names: list[str], settings: Settings) -> list[LLMProvider]:
    """Build each requested provider through the registry and skip the unavailable ones."""
    result: list[LLMProvider] = []
    for n in names:
        if n not in PROVIDER_KINDS:
            print(f"[bench] WARNING: unknown provider {n!r}, skipping")
            continue
        try:
            p = build_provider(n, settings=settings)
        except (OSError, ValueError) as e:  # e.g. the replay provider without its recordings
            print(f"[bench] {n}: cannot be built ({e}), skipping")
            continue
        if not p.is_available():
            print(f"[bench] {n}: not available ({availability_hint(as_kind(n))}), skipping")
            continue
        result.append(p)
        print(f"[bench] {n}: ready (model={p.model_id})")
    return result


def select_judge(settings: Settings) -> LLMProvider | None:
    """Pick the bench judge.

    Default model: the registry's Gemini 2.5 Flash (out-of-family for Claude /
    OpenAI, separate daily-quota bucket from Pro, thinking capped by the
    provider). `BENCH_JUDGE_MODEL` overrides it, for example to force Pro after
    its quota resets; any claude-, gpt- or gemini- model id works.

    Fallback chain on unavailability:
      1. `BENCH_JUDGE_MODEL`
      2. `BENCH_SANITY_SWAP_JUDGE_MODEL`, by default Claude Opus 4.7
         (self-preference bias must be flagged in ADR 2)
    """
    primary = build_judge(settings.bench_judge_model, settings)
    if primary.is_available():
        print(f"[bench] judge: {primary.name} (model={primary.model_id})")
        return primary
    fallback = build_judge(settings.bench_sanity_swap_judge_model, settings)
    if fallback.is_available():
        print(f"[bench] judge: {fallback.model_id} (FALLBACK — flag self-preference bias in ADR 2)")
        return fallback
    print("[bench] no judge available — judge-scored metrics will be SKIPPED")
    return None


def select_swap_judge(settings: Settings) -> LLMProvider | None:
    """The sanity-swap judge, `BENCH_SANITY_SWAP_JUDGE_MODEL`, or None when it has no key."""
    swap_judge = build_judge(settings.bench_sanity_swap_judge_model, settings)
    if swap_judge.is_available():
        return swap_judge
    print(f"[bench] {swap_judge.model_id} not available for sanity swap; skipping")
    return None


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class _TokenUsage(TypedDict):
    """The token counts and latency of one call, as the cost log records them."""

    input_tokens: int
    output_tokens: int
    latency_s: float


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _log_cost(
    provider: LLMProvider,
    question_id: str,
    kind: str,
    response_like: _TokenUsage,
    cost_usd: float,
    *,
    path: Path,
) -> None:
    _append_jsonl(
        path,
        {
            "ts": _now_iso(),
            "provider": provider.name,
            "model_id": provider.model_id,
            "question_id": question_id,
            "kind": kind,  # "answer" | "critic" | "rewrite" | "enrichment" | "judge_correctness" | "judge_faithfulness"
            "input_tokens": response_like.get("input_tokens", 0),
            "output_tokens": response_like.get("output_tokens", 0),
            "latency_s": response_like.get("latency_s", 0.0),
            "cost_usd": cost_usd,
        },
    )


def _log_refusal(
    answer: Answer,
    provider_name: str,
    critic_mode: str,
    *,
    expected_behavior: str = "",
    path: Path,
) -> None:
    """Append a non-answer trace row to the run's refusal-log.jsonl.

    Each row carries `expected_behavior` and `behavior_matched`, so a row
    can be audited without rejoining `bench/results.md`.
    """
    if answer.behavior_taken == "answer":
        return  # only log non-answers
    _append_jsonl(
        path,
        {
            "ts": _now_iso(),
            "provider": provider_name,
            "critic_mode": critic_mode,
            "question": answer.query,
            "expected_behavior": expected_behavior,
            "behavior_taken": answer.behavior_taken,
            "behavior_matched": (
                bool(expected_behavior) and answer.behavior_taken == expected_behavior
            ),
            "refusal_reason": answer.refusal_reason,
            "service_category": answer.service_category,
            "routing_confidence": answer.routing_confidence,
            "question_register": answer.question_register,
            "answer_register": answer.answer_register,
            "retrieved_top_k": [
                {"chunk_id": c.chunk_id, "score": c.score, "service": c.service_title}
                for c in answer.citations
            ],
            "critic_grounded": answer.critic_grounded,
            "critic_register_match": answer.critic_register_match,
            "critic_valid": answer.critic_valid,
            "critic_issues": answer.critic_issues,
        },
    )


# ---------------------------------------------------------------------------
# One-cell evaluation
# ---------------------------------------------------------------------------


def _run_one(
    *,
    provider: LLMProvider,
    judge: LLMProvider | None,
    question: Question,
    gold: GoldAnswer | None,
    index: Index,
    bm25_index: BM25Index | None,
    critic_mode: str,
    paths: RunPaths,
) -> CaseResult:
    """Run one (provider, critic_mode) on one question + evaluate."""
    critic_enabled = critic_mode == "on"
    try:
        answer = answer_question(
            question["text"],
            index,
            provider,
            bm25_index=bm25_index,
            top_k=5,
            critic_enabled=critic_enabled,
        )
    except Exception as e:
        # Provider failure → record and continue.
        return CaseResult(
            question_id=question["question_id"],
            provider_name=provider.name,
            provider_model_id=provider.model_id,
            critic_mode=critic_mode,
            expected_behavior=question.get("expected_behavior", "answer"),
            behavior_taken="error",
            behavior_match=False,
            answer_error=f"{type(e).__name__}: {str(e)[:200]}",
        )

    # Cost log for the answer call.
    answer_cost = 0.0
    if provider.name != "mock":
        # Approximate from token counts on the Answer (latency_s, input/output_tokens
        # are populated). Build a synthetic ProviderResponse-like dict for cost calc.
        fake_resp = ProviderResponse(
            text=answer.answer_text,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
            latency_s=answer.latency_s,
        )
        answer_cost = provider.cost_estimate_usd(fake_resp)
    _log_cost(
        provider,
        question["question_id"],
        kind=f"answer_critic_{critic_mode}",
        response_like={
            "input_tokens": answer.input_tokens,
            "output_tokens": answer.output_tokens,
            "latency_s": answer.latency_s,
        },
        cost_usd=answer_cost,
        path=paths.cost_log,
    )

    _log_refusal(
        answer,
        provider.name,
        critic_mode,
        expected_behavior=question.get("expected_behavior", "answer"),
        path=paths.refusal_log,
    )

    # Evaluate against gold (judge calls happen inside).
    if judge is None:
        # No judge → skip the judge-scored metrics, keep rule-based ones.
        # Fake judge that errors on every call so evaluate_case's fields stay empty.
        class _NoJudge:
            name = "no_judge"
            model_id = "n/a"

            def generate(
                self, system: str, user: str, max_tokens: int = 1024, timeout: float = 30.0
            ) -> ProviderResponse:
                raise RuntimeError("no judge configured")

            def is_available(self) -> bool:
                return False

            def cost_estimate_usd(self, response: ProviderResponse) -> float:
                return 0.0

        judge_to_use: LLMProvider = _NoJudge()
    else:
        judge_to_use = judge

    case = evaluate_case(
        question=question,
        answer=answer,
        gold=gold,
        judge=judge_to_use,
        provider_name=provider.name,
        provider_model_id=provider.model_id,
        critic_mode=critic_mode,
    )
    case.cost_usd = answer_cost
    return case


def _run_one_red_team(
    *,
    provider: LLMProvider,
    judge: LLMProvider | None,
    case_data: RedTeamCase,
    index: Index,
    bm25_index: BM25Index | None,
    critic_mode: str,
    paths: RunPaths,
) -> CaseResult:
    """Run one red-team case through (provider, critic_mode) + score it."""
    critic_enabled = critic_mode == "on"
    case_id = case_data["case_id"]
    try:
        answer = answer_question(
            case_data["question_text"],
            index,
            provider,
            bm25_index=bm25_index,
            top_k=5,
            critic_enabled=critic_enabled,
        )
    except Exception as e:
        result = CaseResult(
            question_id=case_id,
            provider_name=provider.name,
            provider_model_id=provider.model_id,
            critic_mode=critic_mode,
            expected_behavior=case_data.get("expected_behavior", "refuse_with_redirect"),
            behavior_taken="error",
            behavior_match=False,
            is_red_team=True,
            red_team_category=case_data.get("category", ""),
            evaluation_notes=case_data.get("evaluation_notes", ""),
            answer_error=f"{type(e).__name__}: {str(e)[:200]}",
        )
        return result

    # Cost log.
    answer_cost = 0.0
    if provider.name != "mock":
        fake_resp = ProviderResponse(
            text=answer.answer_text,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
            latency_s=answer.latency_s,
        )
        answer_cost = provider.cost_estimate_usd(fake_resp)
    _log_cost(
        provider,
        case_id,
        kind=f"answer_red_team_critic_{critic_mode}",
        response_like={
            "input_tokens": answer.input_tokens,
            "output_tokens": answer.output_tokens,
            "latency_s": answer.latency_s,
        },
        cost_usd=answer_cost,
        path=paths.cost_log,
    )
    _log_refusal(
        answer,
        provider.name,
        critic_mode,
        expected_behavior=case_data.get("expected_behavior", "refuse_with_redirect"),
        path=paths.refusal_log,
    )

    if judge is None:

        class _NoJudge:
            name = "no_judge"
            model_id = "n/a"

            def generate(
                self, system: str, user: str, max_tokens: int = 1024, timeout: float = 30.0
            ) -> ProviderResponse:
                raise RuntimeError("no judge configured")

            def is_available(self) -> bool:
                return False

            def cost_estimate_usd(self, response: ProviderResponse) -> float:
                return 0.0

        judge_to_use: LLMProvider = _NoJudge()
    else:
        judge_to_use = judge

    case = evaluate_red_team_case(
        case=case_data,
        answer=answer,
        judge=judge_to_use,
        provider_name=provider.name,
        provider_model_id=provider.model_id,
        critic_mode=critic_mode,
    )
    case.cost_usd = answer_cost
    return case


# ---------------------------------------------------------------------------
# Judge sanity swap
# ---------------------------------------------------------------------------

# 3 cases whose registers differ: q-001 is MSA, q-007 dialect, q-013 mixed.
SANITY_SWAP_CASE_IDS = ["q-001", "q-007", "q-013"]
# Pick the first available provider's prediction for the swap. Prefer the most
# representative real model over mock; falls back gracefully if a provider was
# skipped for missing keys.
SANITY_SWAP_PROVIDER_PREFERENCE = ["openai", "claude", "gemini", "mock"]
# Match the verdict's default critic mode (critic=off, the mode the first bench run selected).
SANITY_SWAP_CRITIC_MODE = "off"


class SwapRow(TypedDict):
    """One sanity-swap case: skipped, a swap-judge error, or both judges' scores."""

    question_id: str
    skipped: NotRequired[bool]
    reason: NotRequired[str]
    error: NotRequired[str]
    provider_compared: NotRequired[str]
    provider_model_id: NotRequired[str]
    primary_correctness: NotRequired[float | None]
    swap_correctness: NotRequired[float | None]
    delta_correctness: NotRequired[float | None]
    primary_register: NotRequired[float | None]
    # The swap judge's register score exactly as it returned it; the table renders it as is.
    swap_register: NotRequired[object]


class SanitySwapReport(TypedDict):
    """What `run_judge_sanity_swap` returns and `render_results_md` renders."""

    primary_judge: str
    swap_judge: str
    note: str
    abs_mean_delta_correctness: float | None
    per_case: list[SwapRow]


def _pick_swap_candidate(
    cases: list[CaseResult],
    question_id: str,
) -> CaseResult | None:
    """Find the best stored CaseResult to re-score with the swap judge.

    Preference order is `SANITY_SWAP_PROVIDER_PREFERENCE`; only cases that
    actually have a predicted_answer_text and a primary correctness score are
    eligible (skipping mock-stub-only rows etc.).
    """
    for pref in SANITY_SWAP_PROVIDER_PREFERENCE:
        match = next(
            (
                c
                for c in cases
                if c.question_id == question_id
                and c.critic_mode == SANITY_SWAP_CRITIC_MODE
                and c.provider_name == pref
                and c.predicted_answer_text
                and c.has_gold
                and c.correctness_score is not None
            ),
            None,
        )
        if match is not None:
            return match
    return None


def run_judge_sanity_swap(
    *,
    primary_judge: LLMProvider,
    swap_judge: LLMProvider,
    cases: list[CaseResult],
    questions_by_id: dict[str, Question],
    golds_by_id: dict[str, GoldAnswer],
) -> SanitySwapReport:
    """Re-score the SAME predicted answer with the swap judge.

    For each sanity-swap case, pull the stored predicted answer text from a
    real provider's CaseResult (`SANITY_SWAP_PROVIDER_PREFERENCE`, critic=off),
    re-call the swap judge against that prediction + the gold, and report the
    cross-judge delta. This quantifies actual self-preference bias, which
    scoring the gold answer against itself cannot.
    """
    deltas: list[SwapRow] = []
    for qid in SANITY_SWAP_CASE_IDS:
        primary = _pick_swap_candidate(cases, qid)
        if primary is None:
            deltas.append(
                {
                    "question_id": qid,
                    "skipped": True,
                    "reason": "no stored prediction with primary correctness score",
                }
            )
            continue

        q = questions_by_id.get(qid)
        gold = golds_by_id.get(qid)
        if q is None or gold is None:
            deltas.append(
                {"question_id": qid, "skipped": True, "reason": "missing question or gold"}
            )
            continue

        payload, err = judge_correctness(
            judge=swap_judge,
            question=q["text"],
            predicted_answer=primary.predicted_answer_text,
            gold_answer=gold["gold_answer_text"],
            gold_register=gold.get("expected_register", "MSA"),
            predicted_register=primary.predicted_register or gold.get("expected_register", "MSA"),
        )
        if err:
            deltas.append(
                {"question_id": qid, "error": err, "provider_compared": primary.provider_name}
            )
            continue

        primary_corr = primary.correctness_score or 0.0
        swap_corr = payload.get("correctness_score")
        try:
            swap_corr_f = float(swap_corr) if swap_corr is not None else None
        except (TypeError, ValueError):
            swap_corr_f = None

        delta_corr = (swap_corr_f - primary_corr) if swap_corr_f is not None else None

        deltas.append(
            {
                "question_id": qid,
                "provider_compared": primary.provider_name,
                "provider_model_id": primary.provider_model_id,
                "primary_correctness": primary.correctness_score,
                "swap_correctness": swap_corr_f,
                "delta_correctness": delta_corr,
                "primary_register": primary.register_match_score,
                "swap_register": payload.get("register_match_score"),
            }
        )

    # Compute the absolute-mean bias if we have enough data.
    delta_values = [d.get("delta_correctness") for d in deltas]
    valid_deltas = [v for v in delta_values if isinstance(v, (int, float))]
    abs_mean = sum(abs(d) for d in valid_deltas) / len(valid_deltas) if valid_deltas else None

    return {
        "primary_judge": primary_judge.model_id,
        "swap_judge": swap_judge.model_id,
        "note": (
            "The swap judge re-scores the SAME predicted answer across "
            "two judges (primary vs swap). Δ correctness quantifies cross-judge "
            "self-preference bias on real predictions. ADR 2 reports |mean Δ| as "
            "the bias headline number."
        ),
        "abs_mean_delta_correctness": abs_mean,
        "per_case": deltas,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _fmt(value: object, n: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{n}f}"
    return str(value)


class _ProviderLabel(Protocol):
    """What the results header shows of a provider. `--render-only` passes stand-ins."""

    name: str
    model_id: str


def render_results_md(
    *,
    providers: Sequence[_ProviderLabel],
    judge: LLMProvider | None,
    aggregates_standard: list[AggregateMetrics],
    aggregates_red_team: list[AggregateMetrics],
    sanity_swap: SanitySwapReport | None,
    per_case_standard: list[CaseResult],
    per_case_red_team: list[CaseResult],
    mode: str = "full",
    split: str = "tuned",
    recorded_at: str | None = None,
    judge_model_id: str | None = None,
    rendered_from_cache: bool = False,
) -> str:
    """The results page of one run. `judge_model_id` names the judge when `judge` is None,
    as when `--render-only` rebuilds the page from the case cache and the run manifest."""
    # Mock answers are a fixed placeholder, so mock rows would read as a provider's results.
    # The tables leave them out; one line reports what the rules alone did with mock.
    mock_cases = [c for c in per_case_standard + per_case_red_team if c.provider_name == "mock"]
    aggregates_standard = [a for a in aggregates_standard if a.provider_name != "mock"]
    aggregates_red_team = [a for a in aggregates_red_team if a.provider_name != "mock"]
    per_case_standard = [c for c in per_case_standard if c.provider_name != "mock"]
    per_case_red_team = [c for c in per_case_red_team if c.provider_name != "mock"]
    judge_label = judge.model_id if judge else judge_model_id
    n_questions = len({c.question_id for c in per_case_standard + mock_cases if not c.is_red_team})
    n_gold = len({c.question_id for c in per_case_standard + mock_cases if c.has_gold})
    n_red_team = len({c.question_id for c in per_case_red_team + mock_cases if c.is_red_team})

    lines: list[str] = []
    lines.append("# Murshid — bench results")
    lines.append("")
    if rendered_from_cache:
        lines.append(
            f"Recorded: {recorded_at or 'not recorded'}. Rendered again from the case cache, "
            "with no model call."
        )
    else:
        lines.append(f"Recorded: {recorded_at or _now_iso()}")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Split: {SPLIT_LABELS.get(split, split)}")
    lines.append(
        f"- Providers: {', '.join(f'{p.name} ({p.model_id})' for p in providers) or '(none)'}"
    )
    lines.append(f"- Judge: {judge_label or '(none — judge-scored metrics SKIPPED)'}")
    critic_modes = list(
        dict.fromkeys(c.critic_mode for c in per_case_standard + per_case_red_team + mock_cases)
    )
    lines.append(f"- Critic modes: {', '.join(critic_modes) or '(none)'}")
    lines.append(
        f"- Questions: {n_questions} ({n_gold} with a gold answer); red-team cases: {n_red_team}"
    )
    if mock_cases:
        matched = sum(c.behavior_match for c in mock_cases)
        lines.append(
            "- Mock provider: left out of the tables below, because its answer is a fixed "
            f"placeholder. With it, the rules alone took the expected behavior in {matched} of "
            f"{len(mock_cases)} cells."
        )
    lines.append("- Run manifest, cost log and refusal log: in this file's folder")
    lines.append("")
    if mode == "red_team":
        lines.append("## Mode: red-team-only re-run")
        lines.append("")
        lines.append(
            "A partial re-run scoped to the red-team cases and the sanity swap. The "
            "standard tables (16 questions × providers × critic modes) of the previous run are "
            "preserved verbatim in `bench/archive/results-phase3-snapshot.md`. This file "
            "contains only the red-team aggregate, the red-team per-case results, and the "
            "sanity swap, which scores the SAME predicted answer with two judges."
        )
        lines.append("")

    # ====================================================================
    # Standard questions (skipped in red_team mode — see snapshot file)
    # ====================================================================
    if aggregates_standard:
        lines.append("## Standard questions — aggregate metrics")
        lines.append("")
        lines.append(
            "| Provider | Critic | n | n_gold | Behavior | Recall@5 | Correctness | Register | Faithfulness | Cite acc | Refusal tone | Answer cost (USD) | p50 (s) |"
        )
        lines.append(
            "| --- | --- | ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:|"
        )
        for a in aggregates_standard:
            lines.append(
                f"| {a.provider_name} ({a.provider_model_id}) | {a.critic_mode} | {a.n_cases} | {a.n_with_gold} | "
                f"{_fmt(a.behavior_match_rate)} | {_fmt(a.recall_at_5_mean)} | {_fmt(a.correctness_mean, 2)} | "
                f"{_fmt(a.register_match_mean, 2)} | {_fmt(a.faithfulness_mean, 2)} | {_fmt(a.citation_accuracy_mean)} | "
                f"{_fmt(a.refusal_tone_mean, 2)} | "
                f"{_fmt(a.total_cost_usd, 4)} | {_fmt(a.latency_p50_s, 2)} |"
            )
        lines.append("")
        lines.append(
            "> **Answer cost (USD)** is the per-provider differential answer-call cost across the standard set "
            "(critic mode, rewrite calls, enrichment calls, judge calls all run uniformly across providers, so "
            "their cost cancels in any provider-vs-provider comparison and is excluded from this column). Full "
            "system cost per question is roughly **answer cost + judge calls (~$0.001-0.005 / case at Flash) "
            "+ critic call when on (~answer cost × 0.4)**. See `bench/cost-log.jsonl` for the unaggregated trace."
        )
        lines.append("")

        # Fact-count breakdown
        lines.append("## Fact-count breakdown (correctness diagnostic per ADR 2)")
        lines.append("")
        lines.append(
            "| Provider | Critic | Avg matched facts | Avg missing facts | Avg facts not in gold |"
        )
        lines.append("| --- | --- | ---:| ---:| ---:|")
        for a in aggregates_standard:
            lines.append(
                f"| {a.provider_name} ({a.provider_model_id}) | {a.critic_mode} | "
                f"{_fmt(a.avg_matched_facts, 2)} | {_fmt(a.avg_missing_facts, 2)} | {_fmt(a.avg_irrelevant_facts, 2)} |"
            )
        lines.append("")
        lines.append(
            "Facts not in gold are facts in an answer that the gold answer lacks (the judge's "
            "`irrelevant_facts`): extra detail, not necessarily invented, since the sources may "
            "support it."
        )
        lines.append("")

    # Critic refusal-cause breakdown.
    # Splits the umbrella `refuse_with_redirect` count by WHY the critic gate
    # fired so the reader can tell harness fragility (critic itself errored)
    # apart from real groundedness catches. Only meaningful in critic_mode=on.
    all_aggs_for_critic = aggregates_standard + aggregates_red_team
    if any(
        a.n_critic_invalid_refuses or a.n_grounded_false_refuses or a.n_register_only_logs
        for a in all_aggs_for_critic
    ):
        lines.append("## Critic refusal-cause breakdown (critic=on only)")
        lines.append("")
        lines.append(
            "Splits the `refuse_with_redirect` count for critic=on rows by WHY the gate fired:"
        )
        lines.append("")
        lines.append("- **Critic invalid:** the critic call itself failed, which refuses.")
        lines.append(
            "- **Grounded=false:** the critic judged the answer ungrounded, which refuses."
        )
        lines.append(
            "- **Wrong refusals:** of those refusals, the ones where the case expected another "
            "behavior. A critic refusal is a catch only when the case expected a refusal."
        )
        lines.append(
            "- **Register-only logs:** answer shipped, register slip logged on the Answer envelope (not a refusal)."
        )
        lines.append("")
        lines.append(
            "| Provider | Scope | Critic | Refuses (critic invalid) | Refuses (grounded=false) | Wrong refusals | Logged (register-only) |"
        )
        lines.append("| --- | --- | --- | ---:| ---:| ---:| ---:|")
        for a in all_aggs_for_critic:
            scope = "rt" if a.n_red_team else "std"
            scoped = per_case_red_team if a.n_red_team else per_case_standard
            wrong = sum(
                1
                for c in scoped
                if c.provider_name == a.provider_name
                and c.critic_mode == a.critic_mode
                and c.behavior_taken == "refuse_with_redirect"
                and (not c.critic_valid or not c.critic_grounded)
                and not c.behavior_match
            )
            lines.append(
                f"| {a.provider_name} ({a.provider_model_id}) | {scope} | {a.critic_mode} | "
                f"{a.n_critic_invalid_refuses} | {a.n_grounded_false_refuses} | {wrong} | "
                f"{a.n_register_only_logs} |"
            )
        lines.append("")

    # Errors (standard)
    lines.append("## Errors")
    lines.append("")
    lines.append(
        "| Provider | Critic | Answer | Judge corr | Judge faith | Judge tone | Judge red-team |"
    )
    lines.append("| --- | --- | ---:| ---:| ---:| ---:| ---:|")
    all_aggs = aggregates_standard + aggregates_red_team
    for a in all_aggs:
        scope = "rt" if a.n_red_team else "std"
        lines.append(
            f"| {a.provider_name} ({a.provider_model_id}) [{scope}] | {a.critic_mode} | "
            f"{a.answer_errors} | {a.judge_correctness_errors} | {a.judge_faithfulness_errors} | "
            f"{a.judge_refusal_tone_errors} | {a.judge_red_team_errors} |"
        )
    lines.append("")

    # ====================================================================
    # Red-team
    # ====================================================================
    if aggregates_red_team:
        lines.append("## Red-team — aggregate metrics")
        lines.append("")
        lines.append(
            "| Provider | Critic | n | Behavior | Recall@expected | Rubric pass | Rubric mean | Refusal tone |"
        )
        lines.append("| --- | --- | ---:| ---:| ---:| ---:| ---:| ---:|")
        for a in aggregates_red_team:
            lines.append(
                f"| {a.provider_name} ({a.provider_model_id}) | {a.critic_mode} | {a.n_cases} | "
                f"{_fmt(a.behavior_match_rate)} | {_fmt(a.recall_at_5_mean)} | "
                f"{_fmt(a.red_team_rubric_pass_rate)} | {_fmt(a.red_team_rubric_mean, 2)} | "
                f"{_fmt(a.refusal_tone_mean, 2)} |"
            )
        lines.append("")
        lines.append(
            "Recall@expected uses red-team `expected_source_ids` (the retrieval target), not gold support. "
            "Cases with `expected_source_ids: []` are excluded from recall. The rubric judge receives "
            "`evaluation_notes` per case as the per-case rubric."
        )
        lines.append("")

    # Sanity swap (now scores the SAME prediction across two judges)
    if sanity_swap:
        lines.append("## Judge sanity swap (cross-judge bias on real predictions)")
        lines.append("")
        lines.append(f"- Primary judge: `{sanity_swap['primary_judge']}`")
        lines.append(f"- Swap judge:   `{sanity_swap['swap_judge']}`")
        if sanity_swap.get("abs_mean_delta_correctness") is not None:
            lines.append(
                f"- |mean Δ correctness|: **{_fmt(sanity_swap['abs_mean_delta_correctness'], 2)}** "
                f"(higher = more cross-judge bias on the same prediction)"
            )
        lines.append("")
        lines.append(f"> {sanity_swap['note']}")
        lines.append("")
        lines.append(
            "| Question | Provider compared | Primary correctness | Swap correctness | Δ correctness | Primary register | Swap register |"
        )
        lines.append("| --- | --- | ---:| ---:| ---:| ---:| ---:|")
        for d in sanity_swap["per_case"]:
            if d.get("skipped") or d.get("error"):
                reason = d.get("reason") or d.get("error", "")
                lines.append(
                    f"| {d['question_id']} | {d.get('provider_compared', '—')} | — | — | — | — | — _({reason})_ |"
                )
            else:
                lines.append(
                    f"| {d['question_id']} | {d.get('provider_compared', '—')} ({d.get('provider_model_id', '—')}) | "
                    f"{_fmt(d.get('primary_correctness'), 2)} | "
                    f"{_fmt(d.get('swap_correctness'), 2)} | "
                    f"{_fmt(d.get('delta_correctness'), 2)} | "
                    f"{_fmt(d.get('primary_register'), 2)} | "
                    f"{_fmt(d.get('swap_register'), 2)} |"
                )
        lines.append("")

    # ====================================================================
    # Verdict (only when standard aggregates are present)
    # ====================================================================
    if aggregates_standard:
        lines.append("## Verdict")
        lines.append("")
        # Only a judged row can be compared on quality; mock rows are already out.
        real = [a for a in aggregates_standard if a.correctness_mean is not None]
        if real:

            def score(a: AggregateMetrics) -> float:
                corr = a.correctness_mean or 0
                faith = a.faithfulness_mean or 0
                irr = a.avg_irrelevant_facts or 0
                return a.behavior_match_rate * 3 + corr + faith - irr

            best = max(real, key=score)
            lines.append(
                f"Best by the bench's score (3 × behavior + correctness + faithfulness − facts not "
                f"in gold): **{best.provider_name} ({best.provider_model_id})** "
                f"in `critic={best.critic_mode}` mode. "
                f"Behavior match {_fmt(best.behavior_match_rate)}, correctness {_fmt(best.correctness_mean, 2)} / 3, "
                f"faithfulness {_fmt(best.faithfulness_mean, 2)} / 3, "
                f"avg {_fmt(best.avg_irrelevant_facts, 2)} facts not in the gold answer per question, "
                f"refusal tone {_fmt(best.refusal_tone_mean, 2)} / 3, "
                f"answer cost {_fmt(best.total_cost_usd, 4)} USD across {best.n_cases} cases "
                f"(see Answer-cost-column footnote above for what's included vs not)."
            )
        else:
            lines.append("No verdict: no answer in this run was judged.")
        lines.append("")
        lines.append(
            f"Statistical caveat (ADR 2): correctness / faithfulness aggregates use n ≤ {n_gold} "
            f"gold answers per provider × critic_mode, and the red-team rubric n = {n_red_team} "
            "cases. Treat differences ≤ 0.3 as directional, not significant."
        )
        lines.append("")

    # ====================================================================
    # Per-case tables
    # ====================================================================
    if per_case_standard:
        lines.append("## Per-case results — standard")
        lines.append("")
        lines.append(
            "| Q-ID | Provider | Critic | Behavior (expected → taken) | Recall@5 | Correctness | Register | Faithfulness | Cite acc | Refusal tone | Cost ($) | Latency (s) |"
        )
        lines.append("| --- | --- | --- | --- | ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:|")
        for c in per_case_standard:
            beh = f"{c.expected_behavior} → {c.behavior_taken}" + (
                " ✓" if c.behavior_match else " ✗"
            )
            lines.append(
                f"| {c.question_id} | {c.provider_name} | {c.critic_mode} | {beh} | "
                f"{_fmt(c.recall_at_5)} | {_fmt(c.correctness_score, 1)} | {_fmt(c.register_match_score, 1)} | "
                f"{_fmt(c.faithfulness_score, 1)} | {_fmt(c.citation_accuracy)} | "
                f"{_fmt(c.refusal_tone_score, 1)} | "
                f"{_fmt(c.cost_usd, 5)} | {_fmt(c.latency_s, 2)} |"
            )
        lines.append("")

    if per_case_red_team:
        lines.append("## Per-case results — red-team")
        lines.append("")
        lines.append(
            "| Case | Category | Provider | Critic | Behavior (expected → taken) | Recall | Rubric pass | Rubric score | Refusal tone | Cost ($) | Latency (s) |"
        )
        lines.append("| --- | --- | --- | --- | --- | ---:| :---:| ---:| ---:| ---:| ---:|")
        for c in per_case_red_team:
            beh = f"{c.expected_behavior} → {c.behavior_taken}" + (
                " ✓" if c.behavior_match else " ✗"
            )
            rp = "—"
            if c.red_team_rubric_pass is True:
                rp = "✓"
            elif c.red_team_rubric_pass is False:
                rp = "✗"
            lines.append(
                f"| {c.question_id} | {c.red_team_category} | {c.provider_name} | {c.critic_mode} | {beh} | "
                f"{_fmt(c.recall_at_5)} | {rp} | {_fmt(c.red_team_rubric_score, 1)} | "
                f"{_fmt(c.refusal_tone_score, 1)} | "
                f"{_fmt(c.cost_usd, 5)} | {_fmt(c.latency_s, 2)} |"
            )
        lines.append("")

    # ====================================================================
    # Errors detail — surface answer_error exception class/message inline
    # so a reader does not have to open case-cache.json to diagnose.
    # ====================================================================
    errored_cases = [c for c in (per_case_standard + per_case_red_team) if c.answer_error]
    if errored_cases:
        lines.append("## Errors detail")
        lines.append("")
        lines.append(
            "Rows where `behavior_taken=error` (provider call raised). "
            "Full exception text in the run's `case-cache.json`; truncated here for readability."
        )
        lines.append("")
        lines.append("| Case | Provider | Critic | Exception |")
        lines.append("| --- | --- | --- | --- |")
        for c in errored_cases:
            err = c.answer_error.replace("|", "\\|").replace("\n", " ")
            if len(err) > 160:
                err = err[:157] + "..."
            lines.append(f"| {c.question_id} | {c.provider_name} | {c.critic_mode} | `{err}` |")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run manifest
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args: str) -> str | None:
    """`git <args>` in this checkout, or None when git or the repository is not there."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            ["git", "-C", str(ROOT), *args],  # noqa: S607 - git from PATH, as a developer runs it
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip()


def _murshid_version() -> str | None:
    try:
        return importlib.metadata.version("murshid")
    except importlib.metadata.PackageNotFoundError:
        return None


def _display_path(path: Path) -> str:
    """`path` relative to the repository root when it is inside it, with forward slashes."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_manifest(path: Path) -> dict[str, Any]:
    """A run's manifest, or {} when the folder has none."""
    if not path.exists():
        return {}
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return manifest


def build_manifest(
    *,
    split: str,
    mode: str,
    started_at: str,
    finished_at: str,
    providers: Sequence[_ProviderLabel],
    critic_modes: list[str],
    judge: LLMProvider | None,
    sanity_swap_judge_model_id: str | None,
    settings: Settings,
    data_files: list[Path],
    question_ids: set[str],
    red_team_ids: set[str],
    n_cases: int,
    sanity_swap: SanitySwapReport | None,
) -> dict[str, Any]:
    """What produced a run's numbers: the split, the code, the models, the dates, the data."""
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain", "--untracked-files=no") if commit else None
    return {
        "schema_version": 1,
        "split": split,
        "mode": mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "git_commit": commit,
        "git_dirty": None if status is None else status != "",
        "murshid_version": _murshid_version(),
        "python_version": platform.python_version(),
        "providers": [{"name": p.name, "model_id": p.model_id} for p in providers],
        "critic_modes": critic_modes,
        "judge_model_id": judge.model_id if judge else None,
        "sanity_swap_judge_model_id": sanity_swap_judge_model_id,
        "enrichment": {
            "provider": settings.metadata_enrichment_provider,
            "model_id": settings.metadata_enrichment_model_id,
        },
        "embedder_model_id": EMBEDDER_MODEL_ID,
        "question_ids": sorted(question_ids) or "all",
        "red_team_ids": sorted(red_team_ids) or "all",
        "data_files": {
            _display_path(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in data_files
        },
        "n_cases": n_cases,
        "sanity_swap": sanity_swap,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Murshid mini-bench")
    parser.add_argument(
        "--providers",
        default="mock,claude,openai",
        help=f"Comma-separated provider kinds ({' | '.join(PROVIDER_KINDS)})",
    )
    parser.add_argument(
        "--critic",
        default="on,off",
        help="Comma-separated critic modes (on | off)",
    )
    parser.add_argument(
        "--no-sanity-swap",
        action="store_true",
        help="Skip the judge sanity swap (BENCH_SANITY_SWAP_JUDGE_MODEL).",
    )
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "red_team", "standard"],
        help=(
            "Which bench loops to run. "
            "full (default): standard set + red-team + sanity-swap. "
            "red_team: skip standard, run red-team + 3-question minimal predictions "
            "for sanity-swap. Snapshots the folder's results.md to archive/results-phase3-snapshot.md. "
            "standard: the standard set only; no red-team scoring."
        ),
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help=(
            "Re-render the run folder's results.md from its case-cache.json and "
            "run-manifest.json without running any pipeline / judge / sanity-swap calls. "
            "Lets new aggregate logic or renderer fixes apply to existing bench data "
            "without paying for another run. Errors if no cache exists."
        ),
    )
    parser.add_argument(
        "--split",
        default="tuned",
        choices=list(SPLITS),
        help=(
            "Which question sets to score: tuned (data/, the items the rules were tuned on; "
            "the default) or heldout (data/heldout/, which the rules never saw). A run scores "
            "one split, and each split writes to its own folder."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="The run's folder. Default: bench/ for tuned, bench/heldout/ for heldout.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the run already in the folder. A run of the other split is never replaced.",
    )
    parser.add_argument(
        "--question-ids",
        default="",
        help=(
            "Comma-separated question IDs to filter the split's questions. "
            "Empty = all of them. Lets a small focused bench refresh only "
            "the cases you need without paying for the full set."
        ),
    )
    parser.add_argument(
        "--red-team-ids",
        default="",
        help=("Comma-separated red-team case IDs to filter the split's red-team set. Empty = all."),
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except SettingsError as e:
        print(f"[bench] {e}")
        return 2

    split: str = args.split
    paths = run_paths(split, args.out_dir)

    # ---------------------------------------------------------------
    # Render-only mode — early exit
    # ---------------------------------------------------------------
    if args.render_only:
        if not paths.case_cache.exists():
            print(
                f"[bench] --render-only: no case cache at {paths.case_cache}. "
                "Run the bench at least once first so the cache is created."
            )
            return 1
        manifest = read_manifest(paths.manifest)
        if manifest and manifest.get("split") != split:
            print(
                f"[bench] --render-only: {paths.out_dir} holds a {manifest.get('split')} run; "
                f"pass --split {manifest.get('split')}."
            )
            return 2
        print(f"[bench] --render-only: loading {paths.case_cache}")
        cached = load_cases(paths.case_cache)
        cached_standard = [c for c in cached if not c.is_red_team]
        cached_red_team = [c for c in cached if c.is_red_team]

        # Re-aggregate by (provider, critic_mode) for each scope, in the order the run ran them.
        def _by_pc(cs: list[CaseResult]) -> list[AggregateMetrics]:
            pairs = list(
                dict.fromkeys((c.provider_name, c.provider_model_id, c.critic_mode) for c in cs)
            )
            return [
                aggregate([c for c in cs if c.provider_name == n and c.critic_mode == m])
                for (n, _mid, m) in pairs
            ]

        re_aggs_std = _by_pc(cached_standard)
        re_aggs_rt = _by_pc(cached_red_team)

        # Reconstruct lightweight provider stubs for the renderer header.
        class _StubProvider:
            def __init__(self, name: str, model_id: str) -> None:
                self.name, self.model_id = name, model_id

        provider_pairs = list(dict.fromkeys((c.provider_name, c.provider_model_id) for c in cached))
        stub_providers = [_StubProvider(n, m) for n, m in provider_pairs]

        # Mode is inferred from the cache contents.
        inferred_mode = (
            "red_team"
            if cached_red_team and not cached_standard
            else "standard"
            if cached_standard and not cached_red_team
            else "full"
        )
        # If standard has only the sanity-swap pre-loop count, treat as red_team mode.
        if cached_red_team and len(cached_standard) <= 3:
            inferred_mode = "red_team"

        # The judge, the sanity swap and the date are not in the case cache; the manifest has them.
        md = render_results_md(
            providers=stub_providers,
            judge=None,
            judge_model_id=manifest.get("judge_model_id"),
            aggregates_standard=re_aggs_std if inferred_mode != "red_team" else [],
            aggregates_red_team=re_aggs_rt,
            sanity_swap=manifest.get("sanity_swap"),
            per_case_standard=cached_standard if inferred_mode != "red_team" else [],
            per_case_red_team=cached_red_team,
            mode=inferred_mode,
            split=split,
            recorded_at=manifest.get("started_at"),
            rendered_from_cache=True,
        )
        paths.results_md.write_text(md, encoding="utf-8", newline="\n")
        print(f"[bench] re-rendered {paths.results_md} (no LLM calls made)")
        return 0

    provider_names = [n.strip() for n in args.providers.split(",") if n.strip()]
    critic_modes = [m.strip() for m in args.critic.split(",") if m.strip() in {"on", "off"}]
    if not critic_modes:
        critic_modes = ["on", "off"]
    mode = args.mode

    # One split per folder, never pooled; and a recorded run is replaced only on request.
    recorded = read_manifest(paths.manifest)
    if recorded and recorded.get("split") != split:
        print(
            f"[bench] {paths.out_dir} holds a {recorded.get('split')} run, and a {split} run "
            "must not be mixed with it. Pass another --out-dir."
        )
        return 2
    if (recorded or paths.case_cache.exists()) and not args.overwrite:
        print(
            f"[bench] {paths.out_dir} already holds a recorded run. Pass another --out-dir for "
            "a new run, or --overwrite to replace this one."
        )
        return 2
    started_at = _utc_now()

    # Reset the run's logs.
    paths.out_dir.mkdir(parents=True, exist_ok=True)
    for p in (paths.cost_log, paths.refusal_log):
        if p.exists():
            p.unlink()

    # Red-team-only mode: snapshot the existing results.md so the standard
    # tables are preserved verbatim while the new red-team + sanity-swap data
    # gets written to results.md. The snapshot is the audit trail for the
    # standard verdict — the new results.md will reference it inline.
    if mode == "red_team" and paths.results_md.exists():
        archive_dir = paths.out_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        snapshot_path = archive_dir / "results-phase3-snapshot.md"
        snapshot_path.write_text(
            paths.results_md.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
        print(f"[bench] snapshotted existing results.md -> {snapshot_path}")

    # Build providers + judge.
    print(f"[bench] requested providers: {provider_names}")
    providers = build_providers(provider_names, settings)
    if not providers:
        print("[bench] no providers available — aborting")
        return 1
    judge = select_judge(settings)

    # Build index + bm25 once. Enrichment uses METADATA_ENRICHMENT_PROVIDER (mock by default, to
    # keep cost at zero; a cheap real model is one setting away).
    # The corpus is the same for every split; the question sets are the split's.
    data_dir = settings.murshid_data_dir
    sets_dir = split_data_dir(data_dir, split)
    print(f"[bench] split: {split} (question sets from {sets_dir})")
    print("[bench] building dense + BM25 indices...")
    index = build_index(data_dir, build_enrichment_provider(settings))
    bm25_index = build_bm25_index(index)
    print(f"[bench] index ready ({len(index)} chunks)")

    # Load data.
    with (sets_dir / "questions.json").open(encoding="utf-8") as f:
        questions: list[Question] = json.load(f)
    with (sets_dir / "gold_answers.json").open(encoding="utf-8") as f:
        gold_list: list[GoldAnswer] = json.load(f)
    with (sets_dir / "red_team.json").open(encoding="utf-8") as f:
        red_team: list[RedTeamCase] = json.load(f)
    questions_by_id = {q["question_id"]: q for q in questions}
    golds_by_id = {g["question_id"]: g for g in gold_list}

    # Optional case-id filters (focused bench mode).
    q_filter = {x.strip() for x in args.question_ids.split(",") if x.strip()}
    rt_filter = {x.strip() for x in args.red_team_ids.split(",") if x.strip()}
    if q_filter:
        questions = [q for q in questions if q["question_id"] in q_filter]
        print(f"[bench] standard filter active: {len(questions)} questions")
    if rt_filter:
        red_team = [r for r in red_team if r["case_id"] in rt_filter]
        print(f"[bench] red-team filter active: {len(red_team)} cases")

    # ---------------------------------------------------------------
    # Standard loop
    # ---------------------------------------------------------------
    standard_cases: list[CaseResult] = []
    if mode in {"full", "standard"}:
        n_standard = len(providers) * len(critic_modes) * len(questions)
        cell = 0
        for provider in providers:
            for critic_mode in critic_modes:
                for q in questions:
                    cell += 1
                    gold = golds_by_id.get(q["question_id"])
                    print(
                        f"[bench std {cell}/{n_standard}]  {provider.name}/{critic_mode}/{q['question_id']}",
                        flush=True,
                    )
                    case = _run_one(
                        provider=provider,
                        judge=judge,
                        question=q,
                        gold=gold,
                        index=index,
                        bm25_index=bm25_index,
                        critic_mode=critic_mode,
                        paths=paths,
                    )
                    standard_cases.append(case)
    elif mode == "red_team" and not args.no_sanity_swap:
        # Red-team-only mode: run a minimal pre-loop on the 3 sanity-swap
        # questions × the first preferred-and-available provider × critic=off.
        # The resulting CaseResults feed the swap judge with REAL predictions
        # without re-running the full 16-question standard set.
        # These minimal cases are NOT included in any rendered aggregate.
        preferred = None
        for pref_name in SANITY_SWAP_PROVIDER_PREFERENCE:
            preferred = next((p for p in providers if p.name == pref_name), None)
            if preferred is not None:
                break
        if preferred is not None:
            swap_questions = [
                questions_by_id[qid] for qid in SANITY_SWAP_CASE_IDS if qid in questions_by_id
            ]
            n_swap = len(swap_questions)
            for i, q in enumerate(swap_questions, 1):
                gold = golds_by_id.get(q["question_id"])
                print(
                    f"[bench swap-pre {i}/{n_swap}]  {preferred.name}/off/{q['question_id']}",
                    flush=True,
                )
                case = _run_one(
                    provider=preferred,
                    judge=judge,
                    question=q,
                    gold=gold,
                    index=index,
                    bm25_index=bm25_index,
                    critic_mode=SANITY_SWAP_CRITIC_MODE,
                    paths=paths,
                )
                standard_cases.append(case)
        else:
            print(
                "[bench] no preferred provider available for sanity-swap pre-loop; sanity-swap will skip"
            )

    # ---------------------------------------------------------------
    # Red-team loop
    # ---------------------------------------------------------------
    red_team_cases: list[CaseResult] = []
    if mode in {"full", "red_team"}:
        n_red = len(providers) * len(critic_modes) * len(red_team)
        cell = 0
        for provider in providers:
            for critic_mode in critic_modes:
                for case_data in red_team:
                    cell += 1
                    print(
                        f"[bench rt  {cell}/{n_red}]  {provider.name}/{critic_mode}/{case_data['case_id']}",
                        flush=True,
                    )
                    case = _run_one_red_team(
                        provider=provider,
                        judge=judge,
                        case_data=case_data,
                        index=index,
                        bm25_index=bm25_index,
                        critic_mode=critic_mode,
                        paths=paths,
                    )
                    red_team_cases.append(case)

    all_cases = standard_cases + red_team_cases

    # ---------------------------------------------------------------
    # Aggregation
    # ---------------------------------------------------------------
    # In red_team mode, skip standard aggregates (the pre-loop is sanity-swap
    # fuel only; rendering would be misleading on n=3 standard cases).
    aggregates_standard: list[AggregateMetrics] = []
    aggregates_red_team: list[AggregateMetrics] = []
    if mode in {"full", "standard"}:
        for provider in providers:
            for critic_mode in critic_modes:
                std_subset = [
                    c
                    for c in standard_cases
                    if c.provider_name == provider.name and c.critic_mode == critic_mode
                ]
                aggregates_standard.append(aggregate(std_subset))
    if mode in {"full", "red_team"}:
        for provider in providers:
            for critic_mode in critic_modes:
                rt_subset = [
                    c
                    for c in red_team_cases
                    if c.provider_name == provider.name and c.critic_mode == critic_mode
                ]
                aggregates_red_team.append(aggregate(rt_subset))

    # Sanity swap: scores the SAME predicted answer with two
    # judges. Uses only standard cases (which have gold answers).
    sanity_swap: SanitySwapReport | None = None
    swap_judge_model_id: str | None = None
    if not args.no_sanity_swap and judge is not None:
        swap_judge = select_swap_judge(settings)
        if swap_judge is not None:
            swap_judge_model_id = swap_judge.model_id
            print(f"[bench] running judge sanity swap ({swap_judge.model_id})...")
            sanity_swap = run_judge_sanity_swap(
                primary_judge=judge,
                swap_judge=swap_judge,
                cases=standard_cases,
                questions_by_id=questions_by_id,
                golds_by_id=golds_by_id,
            )

    # Dump case data to disk so `--render-only` can re-apply renderer / aggregate
    # fixes without paying for another bench run.
    dump_cases(paths.case_cache, all_cases)
    print(f"[bench] case cache:         {paths.case_cache}")

    # Render + write.
    md = render_results_md(
        providers=providers,
        judge=judge,
        aggregates_standard=aggregates_standard,
        aggregates_red_team=aggregates_red_team,
        sanity_swap=sanity_swap,
        per_case_standard=standard_cases if mode != "red_team" else [],
        per_case_red_team=red_team_cases,
        mode=mode,
        split=split,
        recorded_at=started_at,
    )
    paths.results_md.write_text(md, encoding="utf-8", newline="\n")

    manifest = build_manifest(
        split=split,
        mode=mode,
        started_at=started_at,
        finished_at=_utc_now(),
        providers=providers,
        critic_modes=critic_modes,
        judge=judge,
        sanity_swap_judge_model_id=swap_judge_model_id,
        settings=settings,
        data_files=[data_dir / "sources.json"]
        + [sets_dir / name for name in ("questions.json", "gold_answers.json", "red_team.json")],
        question_ids=q_filter,
        red_team_ids=rt_filter,
        n_cases=len(all_cases),
        sanity_swap=sanity_swap,
    )
    paths.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[bench] results written to: {paths.results_md}")
    print(f"[bench] cost log:           {paths.cost_log}")
    print(f"[bench] refusal log:        {paths.refusal_log}")
    print(f"[bench] run manifest:       {paths.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

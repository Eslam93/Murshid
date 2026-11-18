"""Bench runner (§0.6) — entry point for `python -m murshid.bench`.

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

Plus the 3-case Opus-4.7 judge sanity swap to quantify self-preference bias
(re-scoring the SAME predicted answer across two judges, Phase 4 polish).

Outputs:
  - `bench/results.md`           — aggregate + per-case results
  - `bench/cost-log.jsonl`       — per-call token usage / cost (answer-call only)
  - `bench/refusal-log.jsonl`    — per refuse/escalate/clarify response trace
  - `bench/case-cache.json`      — per-case results for `--render-only` re-renders
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Allow `python -m murshid.bench` from the repo root.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Load .env before importing provider classes that read env at construct time.
try:
    from dotenv import load_dotenv  # noqa: PLC0415
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

from murshid.bench.metrics import (  # noqa: E402
    AggregateMetrics,
    CaseResult,
    aggregate,
    dump_cases,
    evaluate_case,
    evaluate_red_team_case,
    judge_correctness,
    load_cases,
)
from murshid.ingest import build_index  # noqa: E402
from murshid.pipeline import Answer, answer_question  # noqa: E402
from murshid.providers.base import LLMProvider  # noqa: E402
from murshid.providers.claude import ClaudeProvider  # noqa: E402
from murshid.providers.gemini import GeminiProvider  # noqa: E402
from murshid.providers.mock import MockProvider  # noqa: E402
from murshid.providers.openai import OpenAIProvider  # noqa: E402
from murshid.retrieve import build_bm25_index  # noqa: E402


BENCH_DIR = ROOT / "bench"
DATA_DIR = ROOT / "data"
COST_LOG_PATH = BENCH_DIR / "cost-log.jsonl"
REFUSAL_LOG_PATH = BENCH_DIR / "refusal-log.jsonl"
RESULTS_MD_PATH = BENCH_DIR / "results.md"
CASE_CACHE_PATH = BENCH_DIR / "case-cache.json"


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

_KNOWN_PROVIDERS = {
    "mock": MockProvider,
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}


def build_providers(names: list[str]) -> list[LLMProvider]:
    """Instantiate each requested provider and skip the unavailable ones."""
    result: list[LLMProvider] = []
    for n in names:
        cls = _KNOWN_PROVIDERS.get(n)
        if cls is None:
            print(f"[bench] WARNING: unknown provider {n!r}, skipping")
            continue
        p = cls()
        if not p.is_available():
            print(f"[bench] {n}: not available (missing API key / SDK), skipping")
            continue
        result.append(p)
        print(f"[bench] {n}: ready (model={p.model_id})")
    return result


def select_judge() -> LLMProvider | None:
    """Pick the bench judge.

    Default model: `gemini-2.5-flash` (out-of-family for Claude / OpenAI,
    separate daily-quota bucket from Pro, no thinking-mode budget issues).
    Overridable via `BENCH_JUDGE_MODEL` env var if you want to force Pro after
    its quota resets.

    Fallback chain on unavailability:
      1. Gemini at the configured judge model
      2. Claude Opus 4.7 (self-preference bias must be flagged in ADR 2)
    """
    import os  # noqa: PLC0415

    judge_model = os.environ.get("BENCH_JUDGE_MODEL", "gemini-2.5-flash").strip()
    g = GeminiProvider(model_id=judge_model)
    if g.is_available():
        print(f"[bench] judge: gemini (model={g.model_id})")
        return g
    c = ClaudeProvider(model_id="claude-opus-4-7")
    if c.is_available():
        print("[bench] judge: claude-opus-4-7 (FALLBACK — flag self-preference bias in ADR 2)")
        return c
    print("[bench] no judge available — judge-scored metrics will be SKIPPED")
    return None


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _log_cost(provider: LLMProvider, question_id: str, kind: str, response_like: dict, cost_usd: float) -> None:
    _append_jsonl(
        COST_LOG_PATH,
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
) -> None:
    """Append a non-answer trace row to bench/refusal-log.jsonl.

    Round 2 MEDIUM #5: `expected_behavior` and `behavior_matched` are now
    captured per kickoff §7's refusal-log contract so a row can be audited
    without rejoining `bench/results.md`.
    """
    if answer.behavior_taken == "answer":
        return  # only log non-answers
    _append_jsonl(
        REFUSAL_LOG_PATH,
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
    question: dict,
    gold: dict | None,
    index,
    bm25_index,
    critic_mode: str,
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
    except Exception as e:  # noqa: BLE001
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
        from murshid.providers.base import ProviderResponse  # noqa: PLC0415
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
    )

    _log_refusal(
        answer,
        provider.name,
        critic_mode,
        expected_behavior=question.get("expected_behavior", "answer"),
    )

    # Evaluate against gold (judge calls happen inside).
    if judge is None:
        # No judge → skip the judge-scored metrics, keep rule-based ones.
        # Fake judge that errors on every call so evaluate_case's fields stay empty.
        class _NoJudge:
            name = "no_judge"
            model_id = "n/a"
            def generate(self, system, user, max_tokens=1024, timeout=30.0):  # type: ignore[override]
                raise RuntimeError("no judge configured")
            def is_available(self) -> bool: return False
            def cost_estimate_usd(self, response) -> float: return 0.0
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
    case_data: dict,
    index,
    bm25_index,
    critic_mode: str,
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
    except Exception as e:  # noqa: BLE001
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
        from murshid.providers.base import ProviderResponse  # noqa: PLC0415
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
    )
    _log_refusal(
        answer,
        provider.name,
        critic_mode,
        expected_behavior=case_data.get("expected_behavior", "refuse_with_redirect"),
    )

    if judge is None:
        class _NoJudge:
            name = "no_judge"
            model_id = "n/a"
            def generate(self, system, user, max_tokens=1024, timeout=30.0):  # type: ignore[override]
                raise RuntimeError("no judge configured")
            def is_available(self) -> bool: return False
            def cost_estimate_usd(self, response) -> float: return 0.0
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
# Judge sanity swap (§0.6)
# ---------------------------------------------------------------------------

# 3 cases that exercise distinct registers — one MSA, one dialect, one mixed.
SANITY_SWAP_CASE_IDS = ["q-001", "q-007", "q-013"]
# Pick the first available provider's prediction for the swap. Prefer the most
# representative real model over mock; falls back gracefully if a provider was
# skipped for missing keys.
SANITY_SWAP_PROVIDER_PREFERENCE = ["openai", "claude", "gemini", "mock"]
# Match the verdict's default critic mode (critic=off auto-selected in Phase 3).
SANITY_SWAP_CRITIC_MODE = "off"


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
    questions_by_id: dict[str, dict],
    golds_by_id: dict[str, dict],
) -> dict:
    """Phase 4 polish: re-score the SAME predicted answer with the swap judge.

    For each sanity-swap case, pull the stored predicted answer text from a
    real provider's CaseResult (`SANITY_SWAP_PROVIDER_PREFERENCE`, critic=off),
    re-call the swap judge against that prediction + the gold, and report the
    cross-judge delta. This quantifies actual self-preference bias instead of
    the Round-1 degenerate gold-vs-gold calibration.
    """
    deltas: list[dict] = []
    for qid in SANITY_SWAP_CASE_IDS:
        primary = _pick_swap_candidate(cases, qid)
        if primary is None:
            deltas.append({
                "question_id": qid,
                "skipped": True,
                "reason": "no stored prediction with primary correctness score",
            })
            continue

        q = questions_by_id.get(qid)
        gold = golds_by_id.get(qid)
        if q is None or gold is None:
            deltas.append({"question_id": qid, "skipped": True, "reason": "missing question or gold"})
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
            deltas.append({"question_id": qid, "error": err, "provider_compared": primary.provider_name})
            continue

        primary_corr = primary.correctness_score or 0.0
        swap_corr = payload.get("correctness_score")
        try:
            swap_corr_f = float(swap_corr) if swap_corr is not None else None
        except (TypeError, ValueError):
            swap_corr_f = None

        delta_corr = (swap_corr_f - primary_corr) if swap_corr_f is not None else None

        deltas.append({
            "question_id": qid,
            "provider_compared": primary.provider_name,
            "provider_model_id": primary.provider_model_id,
            "primary_correctness": primary.correctness_score,
            "swap_correctness": swap_corr_f,
            "delta_correctness": delta_corr,
            "primary_register": primary.register_match_score,
            "swap_register": payload.get("register_match_score"),
        })

    # Compute the absolute-mean bias if we have enough data.
    valid_deltas = [
        d.get("delta_correctness")
        for d in deltas
        if isinstance(d.get("delta_correctness"), (int, float))
    ]
    abs_mean = (
        sum(abs(d) for d in valid_deltas) / len(valid_deltas)
        if valid_deltas else None
    )

    return {
        "primary_judge": primary_judge.model_id,
        "swap_judge": swap_judge.model_id,
        "note": (
            "Phase 4 polish: swap judge re-scores the SAME predicted answer across "
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

def _fmt(value, n: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{n}f}"
    return str(value)


def render_results_md(
    *,
    providers: list[LLMProvider],
    judge: LLMProvider | None,
    aggregates_standard: list[AggregateMetrics],
    aggregates_red_team: list[AggregateMetrics],
    sanity_swap: dict | None,
    per_case_standard: list[CaseResult],
    per_case_red_team: list[CaseResult],
    mode: str = "full",
) -> str:
    lines: list[str] = []
    lines.append("# Murshid — bench results")
    lines.append("")
    lines.append(f"Generated: {_now_iso()}")
    lines.append("")
    lines.append("## Configuration")
    lines.append("")
    lines.append(f"- Providers: {', '.join(f'{p.name} ({p.model_id})' for p in providers) or '(none)'}")
    lines.append(f"- Judge: {judge.model_id if judge else '(none — judge-scored metrics SKIPPED)'}")
    lines.append("- Critic modes: off, on (two passes per provider)")
    lines.append("- Standard set: 16 questions (11 with gold), Red-team: 10 cases (Phase 4)")
    lines.append(f"- Cost log: `bench/cost-log.jsonl`")
    lines.append(f"- Refusal log: `bench/refusal-log.jsonl`")
    lines.append("")
    if mode == "red_team":
        lines.append("## Mode: red-team-only re-run")
        lines.append("")
        lines.append(
            "Phase 4 partial re-run scoped to red-team cases + the fixed sanity-swap. "
            "Phase 3 standard tables (16 questions × providers × critic modes) preserved "
            "verbatim in `bench/archive/results-phase3-snapshot.md`; the Phase 3 verdict (openai "
            "`gpt-5.5-2026-04-23`, critic=off — behavior 1.000, correctness 2.20 / 3, "
            "faithfulness 2.36 / 3, 1.00 hallucinated facts per question, cost $0.15 / 16 cases) "
            "still stands. This file contains the Phase 4 additions only: red-team aggregate, "
            "red-team per-case results, and the fixed sanity-swap that scores the SAME predicted "
            "answer across two judges (not the Round-1 degenerate gold-vs-gold)."
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
        lines.append("| Provider | Critic | Avg matched facts | Avg missing facts | Avg irrelevant (hallucinated) facts |")
        lines.append("| --- | --- | ---:| ---:| ---:|")
        for a in aggregates_standard:
            lines.append(
                f"| {a.provider_name} ({a.provider_model_id}) | {a.critic_mode} | "
                f"{_fmt(a.avg_matched_facts, 2)} | {_fmt(a.avg_missing_facts, 2)} | {_fmt(a.avg_irrelevant_facts, 2)} |"
            )
        lines.append("")

    # Critic refusal-cause breakdown — reviewer fix #3.
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
        lines.append("- **Critic invalid:** critic itself errored (harness fragility, NOT a real safety catch).")
        lines.append("- **Grounded=false:** critic returned a real verdict that the answer was ungrounded.")
        lines.append("- **Register-only logs:** answer shipped, register slip logged on the Answer envelope (not a refusal).")
        lines.append("")
        lines.append(
            "| Provider | Scope | Critic | Refuses (critic invalid) | Refuses (grounded=false) | Logged (register-only) |"
        )
        lines.append("| --- | --- | --- | ---:| ---:| ---:|")
        for a in all_aggs_for_critic:
            scope = "rt" if a.n_red_team else "std"
            lines.append(
                f"| {a.provider_name} ({a.provider_model_id}) | {scope} | {a.critic_mode} | "
                f"{a.n_critic_invalid_refuses} | {a.n_grounded_false_refuses} | {a.n_register_only_logs} |"
            )
        lines.append("")

    # Errors (standard)
    lines.append("## Errors")
    lines.append("")
    lines.append("| Provider | Critic | Answer | Judge corr | Judge faith | Judge tone | Judge red-team |")
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
        lines.append(
            "| --- | --- | ---:| ---:| ---:| ---:| ---:| ---:|"
        )
        for a in aggregates_red_team:
            lines.append(
                f"| {a.provider_name} ({a.provider_model_id}) | {a.critic_mode} | {a.n_cases} | "
                f"{_fmt(a.behavior_match_rate)} | {_fmt(a.recall_at_5_mean)} | "
                f"{_fmt(a.red_team_rubric_pass_rate)} | {_fmt(a.red_team_rubric_mean, 2)} | "
                f"{_fmt(a.refusal_tone_mean, 2)} |"
            )
        lines.append("")
        lines.append(
            "Recall@expected uses red-team `expected_source_ids` (retrieval target per §0.7), not gold support. "
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
        lines.append("| Question | Provider compared | Primary correctness | Swap correctness | Δ correctness | Primary register | Swap register |")
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
        real = [a for a in aggregates_standard if a.provider_name != "mock"]
        if real:
            def score(a: AggregateMetrics) -> float:
                corr = a.correctness_mean or 0
                faith = a.faithfulness_mean or 0
                irr = a.avg_irrelevant_facts or 0
                return a.behavior_match_rate * 3 + corr + faith - irr
            best = max(real, key=score)
            lines.append(
                f"Provisional production default: **{best.provider_name} ({best.provider_model_id})** "
                f"in `critic={best.critic_mode}` mode. "
                f"Behavior match {_fmt(best.behavior_match_rate)}, correctness {_fmt(best.correctness_mean, 2)} / 3, "
                f"faithfulness {_fmt(best.faithfulness_mean, 2)} / 3, "
                f"avg {_fmt(best.avg_irrelevant_facts, 2)} hallucinated facts per question, "
                f"refusal tone {_fmt(best.refusal_tone_mean, 2)} / 3, "
                f"answer cost {_fmt(best.total_cost_usd, 4)} USD across {best.n_cases} cases "
                f"(see Answer-cost-column footnote above for what's included vs not)."
            )
        else:
            lines.append("Only the mock provider ran. No verdict — see provider-availability notes above.")
        lines.append("")
        lines.append("Statistical caveat (ADR 2): correctness / faithfulness aggregates use n ≤ 11 gold answers per provider × critic_mode. Red-team uses n=10 cases. Treat differences ≤ 0.3 as directional, not significant.")
        lines.append("")

    # ====================================================================
    # Per-case tables
    # ====================================================================
    if per_case_standard:
        lines.append("## Per-case results — standard")
        lines.append("")
        lines.append("| Q-ID | Provider | Critic | Behavior (expected → taken) | Recall@5 | Correctness | Register | Faithfulness | Cite acc | Refusal tone | Cost ($) | Latency (s) |")
        lines.append("| --- | --- | --- | --- | ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:|")
        for c in per_case_standard:
            beh = f"{c.expected_behavior} → {c.behavior_taken}" + (" ✓" if c.behavior_match else " ✗")
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
        lines.append("| Case | Category | Provider | Critic | Behavior (expected → taken) | Recall | Rubric pass | Rubric score | Refusal tone | Cost ($) | Latency (s) |")
        lines.append("| --- | --- | --- | --- | --- | ---:| :---:| ---:| ---:| ---:| ---:|")
        for c in per_case_red_team:
            beh = f"{c.expected_behavior} → {c.behavior_taken}" + (" ✓" if c.behavior_match else " ✗")
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
    # so reviewers don't have to open case-cache.json to diagnose.
    # ====================================================================
    errored_cases = [
        c for c in (per_case_standard + per_case_red_team) if c.answer_error
    ]
    if errored_cases:
        lines.append("## Errors detail")
        lines.append("")
        lines.append(
            "Rows where `behavior_taken=error` (provider call raised). "
            "Full exception text in `bench/case-cache.json`; truncated here for readability."
        )
        lines.append("")
        lines.append("| Case | Provider | Critic | Exception |")
        lines.append("| --- | --- | --- | --- |")
        for c in errored_cases:
            err = c.answer_error.replace("|", "\\|").replace("\n", " ")
            if len(err) > 160:
                err = err[:157] + "..."
            lines.append(
                f"| {c.question_id} | {c.provider_name} | {c.critic_mode} | `{err}` |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Murshid mini-bench (§0.6)")
    parser.add_argument(
        "--providers",
        default="mock,claude,openai",
        help="Comma-separated provider names (mock | claude | openai | gemini)",
    )
    parser.add_argument(
        "--critic",
        default="on,off",
        help="Comma-separated critic modes (on | off)",
    )
    parser.add_argument(
        "--no-sanity-swap",
        action="store_true",
        help="Skip the Opus-4.7 judge sanity swap.",
    )
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "red_team", "standard"],
        help=(
            "Which bench loops to run. "
            "full (default): standard set + red-team + sanity-swap. "
            "red_team: skip standard, run red-team + 3-question minimal predictions "
            "for sanity-swap. Snapshots existing results.md to results-phase3-snapshot.md. "
            "standard: original Phase 3 behavior; no red-team scoring."
        ),
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help=(
            "Re-render bench/results.md from bench/case-cache.json without running "
            "any pipeline / judge / sanity-swap calls. Lets new aggregate logic or "
            "renderer fixes apply to existing bench data without paying for another "
            "run. Errors if no cache exists."
        ),
    )
    parser.add_argument(
        "--question-ids",
        default="",
        help=(
            "Comma-separated question IDs to filter the standard set. "
            "Empty = all 16 questions. Lets a small focused bench refresh only "
            "the cases the reviewer asked about without paying for the full set."
        ),
    )
    parser.add_argument(
        "--red-team-ids",
        default="",
        help=(
            "Comma-separated red-team case IDs to filter the red-team set. "
            "Empty = all 10 cases."
        ),
    )
    args = parser.parse_args(argv)

    # ---------------------------------------------------------------
    # Render-only mode — early exit
    # ---------------------------------------------------------------
    if args.render_only:
        if not CASE_CACHE_PATH.exists():
            print(
                f"[bench] --render-only: no case cache at {CASE_CACHE_PATH}. "
                "Run the bench at least once first so the cache is created."
            )
            return 1
        print(f"[bench] --render-only: loading {CASE_CACHE_PATH}")
        cached = load_cases(CASE_CACHE_PATH)
        cached_standard = [c for c in cached if not c.is_red_team]
        cached_red_team = [c for c in cached if c.is_red_team]

        # Re-aggregate by (provider, critic_mode) for each scope.
        def _by_pc(cs: list[CaseResult]) -> list[AggregateMetrics]:
            pairs = sorted({(c.provider_name, c.provider_model_id, c.critic_mode) for c in cs})
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
        provider_pairs = sorted({(c.provider_name, c.provider_model_id) for c in cached})
        stub_providers = [_StubProvider(n, m) for n, m in provider_pairs]

        # Mode is inferred from the cache contents.
        inferred_mode = (
            "red_team" if cached_red_team and not cached_standard else
            "standard" if cached_standard and not cached_red_team else
            "full"
        )
        # If standard has only the sanity-swap pre-loop count, treat as red_team mode.
        if cached_red_team and len(cached_standard) <= 3:
            inferred_mode = "red_team"

        md = render_results_md(
            providers=stub_providers,  # type: ignore[arg-type]
            judge=None,  # judge model name isn't preserved in cache; the existing
                          # results.md "Configuration" line is overwritten by the
                          # render — accept the loss for render-only re-runs.
            aggregates_standard=re_aggs_std if inferred_mode != "red_team" else [],
            aggregates_red_team=re_aggs_rt,
            sanity_swap=None,
            per_case_standard=cached_standard if inferred_mode != "red_team" else [],
            per_case_red_team=cached_red_team,
            mode=inferred_mode,
        )
        RESULTS_MD_PATH.write_text(md, encoding="utf-8")
        print(f"[bench] re-rendered {RESULTS_MD_PATH} (no LLM calls made)")
        return 0

    provider_names = [n.strip() for n in args.providers.split(",") if n.strip()]
    critic_modes = [m.strip() for m in args.critic.split(",") if m.strip() in {"on", "off"}]
    if not critic_modes:
        critic_modes = ["on", "off"]
    mode = args.mode

    # Reset bench logs.
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    for p in (COST_LOG_PATH, REFUSAL_LOG_PATH):
        if p.exists():
            p.unlink()

    # Red-team-only mode: snapshot the existing results.md so Phase 3 standard
    # tables are preserved verbatim while the new red-team + sanity-swap data
    # gets written to results.md. The snapshot is the audit trail for the
    # standard verdict — the new results.md will reference it inline.
    if mode == "red_team" and RESULTS_MD_PATH.exists():
        archive_dir = BENCH_DIR / "archive"
        archive_dir.mkdir(exist_ok=True)
        snapshot_path = archive_dir / "results-phase3-snapshot.md"
        snapshot_path.write_text(
            RESULTS_MD_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        print(f"[bench] snapshotted existing results.md -> {snapshot_path}")

    # Build providers + judge.
    print(f"[bench] requested providers: {provider_names}")
    providers = build_providers(provider_names)
    if not providers:
        print("[bench] no providers available — aborting")
        return 1
    judge = select_judge()

    # Build index + bm25 once (use mock for enrichment to keep cost low — Phase 3
    # can swap in a real cheap model via METADATA_ENRICHMENT_PROVIDER later).
    print("[bench] building dense + BM25 indices...")
    index = build_index(DATA_DIR, MockProvider())
    bm25_index = build_bm25_index(index)
    print(f"[bench] index ready ({len(index)} chunks)")

    # Load data.
    with (DATA_DIR / "questions.json").open(encoding="utf-8") as f:
        questions = json.load(f)
    with (DATA_DIR / "gold_answers.json").open(encoding="utf-8") as f:
        gold_list = json.load(f)
    with (DATA_DIR / "red_team.json").open(encoding="utf-8") as f:
        red_team = json.load(f)
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
                questions_by_id[qid] for qid in SANITY_SWAP_CASE_IDS
                if qid in questions_by_id
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
                )
                standard_cases.append(case)
        else:
            print("[bench] no preferred provider available for sanity-swap pre-loop; sanity-swap will skip")

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
                    c for c in standard_cases
                    if c.provider_name == provider.name and c.critic_mode == critic_mode
                ]
                aggregates_standard.append(aggregate(std_subset))
    if mode in {"full", "red_team"}:
        for provider in providers:
            for critic_mode in critic_modes:
                rt_subset = [
                    c for c in red_team_cases
                    if c.provider_name == provider.name and c.critic_mode == critic_mode
                ]
                aggregates_red_team.append(aggregate(rt_subset))

    # Sanity swap — Phase 4 fixed: scores the SAME predicted answer with two
    # judges. Uses only standard cases (which have gold answers).
    sanity_swap = None
    if not args.no_sanity_swap and judge is not None:
        swap_judge = ClaudeProvider(model_id="claude-opus-4-7")
        if swap_judge.is_available():
            print("[bench] running judge sanity swap (Opus-4.7)...")
            sanity_swap = run_judge_sanity_swap(
                primary_judge=judge,
                swap_judge=swap_judge,
                cases=standard_cases,
                questions_by_id=questions_by_id,
                golds_by_id=golds_by_id,
            )
        else:
            print("[bench] Opus-4.7 not available for sanity swap; skipping")

    # Dump case data to disk so `--render-only` can re-apply renderer / aggregate
    # fixes without paying for another bench run.
    dump_cases(CASE_CACHE_PATH, all_cases)
    print(f"[bench] case cache:         {CASE_CACHE_PATH}")

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
    )
    RESULTS_MD_PATH.write_text(md, encoding="utf-8")
    print(f"[bench] results written to: {RESULTS_MD_PATH}")
    print(f"[bench] cost log:           {COST_LOG_PATH}")
    print(f"[bench] refusal log:        {REFUSAL_LOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

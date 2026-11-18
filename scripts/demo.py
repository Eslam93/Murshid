"""The 3-question demo.

Runs the 3-question demo or a single ad-hoc question through the full pipeline
(router → register → rewrite → multi-view hybrid retrieve → generate → critic).
Writes UTF-8 to `<MURSHID_OUT_DIR>/demo_output.txt` (`out/` by default); tails
minimal status to stdout (Windows PowerShell mangles RTL Arabic in stdout —
the README says to open the file instead).

Usage:
  uv run python scripts/demo.py                                  # 3-question suite
  uv run python scripts/demo.py "<your query>"                   # single query
  uv run python scripts/demo.py --provider replay                # recorded real-model answers
  uv run python scripts/demo.py "<your query>" --provider openai # single query, real openai
  uv run python scripts/demo.py --provider claude --model <id>   # a specific model

The provider defaults to `LLM_PROVIDER` (extractive unless set): it quotes the
retrieved passages, with no key and no network. `replay` answers the bench
questions with recorded Claude / OpenAI answers. Paid providers (claude /
openai / gemini) read their key from the settings (`.env` or the environment:
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`). The index is
enriched by `METADATA_ENRICHMENT_PROVIDER` (mock, free, by default).

The 3-question suite covers three paths:
  - MSA, in-corpus (q-001 — Hijri renewal date + fees)
  - Khaleeji dialect, in-corpus (q-007 — sponsorship transfer with Hijri end)
  - Out-of-corpus (q-014 — personal loan question about traffic fines)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from the repo root: `python scripts/demo.py [optional_query]`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from murshid.ingest import build_index  # noqa: E402
from murshid.pipeline import Answer, answer_question  # noqa: E402
from murshid.providers.factory import (  # noqa: E402
    PROVIDER_KINDS,
    as_kind,
    availability_hint,
    build_enrichment_provider,
    build_provider,
)
from murshid.retrieve import build_bm25_index  # noqa: E402
from murshid.settings import SettingsError, get_settings  # noqa: E402

DEMO_QUESTIONS = [
    {
        "label": "MSA in-corpus — q-001",
        "text": (
            "ما آخر موعد مناسب لتجديد الإقامة إذا كان تاريخ الانتهاء مسجلاً "
            "في 20 رمضان 1447هـ، وما الرسوم المتوقعة لسنة واحدة؟"
        ),
        "expected_behavior": "answer",
        "expected_category": "iqama",
    },
    {
        "label": "Khaleeji dialect in-corpus — q-007",
        "text": (
            "شلون أنقل كفالتي إذا عقدي خلص في 20 شعبان 1447هـ؟ وهل لازم موافقة الشركة القديمة؟"
        ),
        "expected_behavior": "answer",
        "expected_category": "sponsorship_transfer",
    },
    {
        "label": "Out-of-corpus (escalate) — q-014",
        "text": (
            "صاحبي يقول إذا عندي مخالفات مرورية أقدر آخذ قرض شخصي بدون ما يأثر، هل هذا الكلام صحيح؟"
        ),
        "expected_behavior": "refuse_with_redirect",
        "expected_category": "out_of_scope",
    },
]


def render_question_block(idx: int, q: dict, answer: Answer) -> str:
    """Render one Q&A block as a UTF-8 plain-text section."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append(f"[{idx + 1}/{len(DEMO_QUESTIONS)}] {q['label']}")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Question:")
    lines.append(answer.query)
    lines.append("")
    lines.append("Pipeline trace:")
    lines.append(
        f"  router       → category={answer.service_category}  "
        f"(confidence={answer.routing_confidence:.2f})  "
        f"[expected={q['expected_category']}]"
    )
    lines.append(
        f"  register     → question:{answer.question_register} / answer:{answer.answer_register}  "
        f"(family={answer.dialect_family}, cs={answer.contains_code_switching})"
    )
    if answer.rewritten_query and answer.rewritten_query.strip() != answer.query.strip():
        lines.append(f"  rewrite      → {answer.rewritten_query}")
    else:
        lines.append("  rewrite      → (identity / not invoked)")
    lines.append(f"  behavior     → {answer.behavior_taken}  [expected={q['expected_behavior']}]")
    if answer.refusal_reason:
        lines.append(f"  refusal_reason → {answer.refusal_reason}")
    lines.append(
        f"  critic       → register_match={answer.critic_register_match}, "
        f"grounded={answer.critic_grounded}, issues={answer.critic_issues}"
    )
    lines.append(
        f"  provider     → {answer.provider_name} ({answer.provider_model_id})  "
        f"latency={answer.latency_s:.3f}s  tokens={answer.input_tokens}/{answer.output_tokens}"
    )
    lines.append("")
    lines.append("Answer:")
    lines.append(answer.answer_text)
    lines.append("")
    if answer.citations:
        lines.append(f"Citations (top-{len(answer.citations)}):")
        for i, c in enumerate(answer.citations, 1):
            lines.append(f"  [{i}] {c.chunk_id}  (score={c.score:.4f})")
            lines.append(f"      service: {c.service_title}")
            preview = c.passage_text.replace("\n", " ")
            if len(preview) > 240:
                preview = preview[:237] + "..."
            lines.append(f"      passage: {preview}")
    else:
        lines.append("Citations: (none — short-circuited before retrieval)")
    lines.append("")
    return "\n".join(lines)


def render_summary(answers: list[tuple[dict, Answer]]) -> str:
    lines: list[str] = ["=" * 80, "Demo summary", "=" * 80, ""]
    for q, a in answers:
        cat_ok = a.service_category == q["expected_category"]
        beh_ok = a.behavior_taken == q["expected_behavior"]
        lines.append(
            f"  {q['label']}: category {'OK' if cat_ok else 'MISS'} ({a.service_category}), "
            f"behavior {'OK' if beh_ok else 'MISS'} ({a.behavior_taken})"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    try:
        settings = get_settings()
    except SettingsError as e:
        print(f"[demo] {e}")
        return 2

    parser = argparse.ArgumentParser(
        prog="demo.py",
        description="Run Murshid against the 3-question suite or a single ad-hoc query.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Optional single Arabic query. Omit to run the 3-question suite.",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_KINDS,
        default=settings.llm_provider,
        help=(
            f"LLM provider for generation (default: LLM_PROVIDER, now {settings.llm_provider}; "
            "extractive and replay need no API key)."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id for the provider (default: the one the settings choose).",
    )
    args = parser.parse_args(argv[1:])

    try:
        provider = build_provider(args.provider, args.model, settings)
    except (OSError, ValueError) as e:
        print(f"[demo] cannot build the {args.provider} provider: {e}")
        return 2
    if not provider.is_available():
        hint = availability_hint(as_kind(args.provider))
        print(f"[demo] the {args.provider} provider is not available: {hint}.")
        return 2

    single_query = args.query.strip() if args.query and args.query.strip() else None
    questions: list[dict]
    if single_query:
        questions = [
            {
                "label": "Ad-hoc query (CLI)",
                "text": single_query,
                "expected_behavior": "(not set)",
                "expected_category": "(not set)",
            }
        ]
    else:
        questions = list(DEMO_QUESTIONS)

    data_dir = settings.murshid_data_dir
    print(f"[demo] Building index over {data_dir / 'sources.json'}...")
    print("[demo]   (first run downloads BGE-M3 weights ~2.3GB; subsequent runs hit the cache)")
    index = build_index(data_dir=data_dir, enrichment_provider=build_enrichment_provider(settings))
    print(f"[demo] Dense index: {len(index)} chunks")

    print("[demo] Building BM25 sparse index...")
    bm25_index = build_bm25_index(index)
    print("[demo] BM25 index: ready")

    print(f"[demo] Generation provider: {provider.name} ({provider.model_id})")
    print(f"[demo] Running {len(questions)} question(s) through the full pipeline...")
    answers: list[tuple[dict, Answer]] = []
    for q in questions:
        answer = answer_question(
            q["text"],
            index,
            provider,
            bm25_index=bm25_index,
            top_k=5,
        )
        answers.append((q, answer))
        print(
            f"[demo]   - {q['label']}: "
            f"category={answer.service_category}, "
            f"behavior={answer.behavior_taken}, "
            f"citations={len(answer.citations)}"
        )

    # Render and write
    blocks: list[str] = ["Murshid — demo output\n"]
    if not single_query:
        blocks.append(render_summary(answers))
    for i, (q, a) in enumerate(answers):
        blocks.append(render_question_block(i, q, a))

    output_path = settings.murshid_out_dir / "demo_output.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    print(f"[demo] Output written to: {output_path}")
    print(f"[demo] Open {output_path} to view the full Arabic output")
    print("[demo]   (Windows PowerShell mangles RTL Arabic in stdout).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

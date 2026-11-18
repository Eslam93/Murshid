"""Phase 2 demo (§2 scripts/demo.py).

Runs the 3-question demo or a single ad-hoc question through the full pipeline
(router → register → rewrite → multi-view hybrid retrieve → generate → critic).
Writes UTF-8 to `demo_output.txt`; tails minimal status to stdout (Windows
PowerShell mangles RTL Arabic in stdout — README directs reviewers to open
the file).

Usage:
  python scripts/demo.py                                    # 3-question suite, mock
  python scripts/demo.py "<your query>"                     # single query, mock
  python scripts/demo.py "<your query>" --provider openai   # single query, real openai
  python scripts/demo.py --provider claude                  # 3-question suite, real claude

Real providers (claude / openai / gemini) read their API key from `.env`
(`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`). Enrichment stays
on the mock provider so index-build is fast and free.

The 3-question suite covers the rubric's required surfaces:
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
from murshid.providers.base import LLMProvider  # noqa: E402
from murshid.providers.mock import MockProvider  # noqa: E402
from murshid.retrieve import build_bm25_index  # noqa: E402


PROVIDER_CHOICES = ("mock", "claude", "openai", "gemini")


def _build_provider(name: str) -> LLMProvider:
    """Instantiate the named provider. Real providers load API keys from .env."""
    if name == "mock":
        return MockProvider()
    # Lazy import + .env load so mock-mode doesn't need the SDK / dotenv.
    from dotenv import load_dotenv
    load_dotenv()
    if name == "claude":
        from murshid.providers.claude import ClaudeProvider
        return ClaudeProvider()
    if name == "openai":
        from murshid.providers.openai import OpenAIProvider
        return OpenAIProvider()
    if name == "gemini":
        from murshid.providers.gemini import GeminiProvider
        return GeminiProvider()
    raise ValueError(f"Unknown provider: {name}. Choices: {PROVIDER_CHOICES}")


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
            "شلون أنقل كفالتي إذا عقدي خلص في 20 شعبان 1447هـ؟ "
            "وهل لازم موافقة الشركة القديمة؟"
        ),
        "expected_behavior": "answer",
        "expected_category": "sponsorship_transfer",
    },
    {
        "label": "Out-of-corpus (escalate) — q-014",
        "text": (
            "صاحبي يقول إذا عندي مخالفات مرورية أقدر آخذ قرض شخصي "
            "بدون ما يأثر، هل هذا الكلام صحيح؟"
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
    lines.append(
        f"  behavior     → {answer.behavior_taken}  "
        f"[expected={q['expected_behavior']}]"
    )
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
    lines: list[str] = ["=" * 80, "Phase 2 demo summary", "=" * 80, ""]
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
        choices=PROVIDER_CHOICES,
        default="mock",
        help="LLM provider for generation (default: mock, no API key needed).",
    )
    args = parser.parse_args(argv[1:])

    single_query = args.query.strip() if args.query and args.query.strip() else None
    questions: list[dict]
    if single_query:
        questions = [{
            "label": "Ad-hoc query (CLI)",
            "text": single_query,
            "expected_behavior": "(not set)",
            "expected_category": "(not set)",
        }]
    else:
        questions = list(DEMO_QUESTIONS)

    print("[demo] Building index over data/sources.json...")
    print("[demo]   (first run downloads BGE-M3 weights ~2.3GB; subsequent runs hit the cache)")
    # Enrichment stays on Mock — index-build is one-shot, doesn't need real LLM.
    enrichment_provider = MockProvider()
    index = build_index(data_dir=ROOT / "data", enrichment_provider=enrichment_provider)
    print(f"[demo] Dense index: {len(index)} chunks")

    print("[demo] Building BM25 sparse index...")
    bm25_index = build_bm25_index(index)
    print("[demo] BM25 index: ready")

    provider = _build_provider(args.provider)
    print(f"[demo] Generation provider: {args.provider}", end="")
    if args.provider != "mock":
        print(f" ({provider.model_id})")
    else:
        print()
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
    blocks: list[str] = ["Murshid — Phase 2 demo output\n"]
    if not single_query:
        blocks.append(render_summary(answers))
    for i, (q, a) in enumerate(answers):
        blocks.append(render_question_block(i, q, a))

    output_path = ROOT / "demo_output.txt"
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    print(f"[demo] Output written to: {output_path}")
    print("[demo] Open demo_output.txt to view the full Arabic output")
    print("[demo]   (Windows PowerShell mangles RTL Arabic in stdout).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Minimal Gradio UI for Murshid.

Install:  pip install gradio
Run:      python scripts/ui.py
Open:     http://127.0.0.1:7860   (auto-launched in your browser)

Type an Arabic (or English) question, pick a provider, hit Ask.
Real providers (claude / openai / gemini) read API keys from `.env`
(`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY`). Mock works
with no keys.

Lowest-standard-of-pretty by design — three boxes (trace, answer, citations)
and one button. RTL is on for the Arabic-bearing fields.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

try:
    import gradio as gr
except ImportError:
    print("[ui] gradio not installed. Run: pip install gradio")
    sys.exit(1)

from murshid.ingest import build_index  # noqa: E402
from murshid.pipeline import answer_question  # noqa: E402
from murshid.providers.base import LLMProvider  # noqa: E402
from murshid.providers.mock import MockProvider  # noqa: E402
from murshid.retrieve import build_bm25_index  # noqa: E402


# Model -> (provider kind, model_id). Display name = model ID for clarity.
# Defaults per kickoff §0.5 verified-current table; Gemini 2.5 Flash added
# because it's the bench's actual judge model (separate quota from Pro).
MODELS: dict[str, tuple[str, str | None]] = {
    "mock":                          ("mock",   None),
    "claude-sonnet-4-6":             ("claude", "claude-sonnet-4-6"),
    "claude-opus-4-7":               ("claude", "claude-opus-4-7"),
    "claude-haiku-4-5-20251001":     ("claude", "claude-haiku-4-5-20251001"),
    "gpt-5.5-2026-04-23":            ("openai", "gpt-5.5-2026-04-23"),
    "gpt-5.4-mini-2026-03-17":       ("openai", "gpt-5.4-mini-2026-03-17"),
    "gemini-3.1-pro-preview":        ("gemini", "gemini-3.1-pro-preview"),
    "gemini-3-flash-preview":        ("gemini", "gemini-3-flash-preview"),
    "gemini-2.5-flash":              ("gemini", "gemini-2.5-flash"),
}
_provider_cache: dict[str, LLMProvider] = {}


def _build_provider(model_name: str) -> LLMProvider:
    """Lazy-instantiate + cache, so the SDK client survives across calls."""
    if model_name in _provider_cache:
        return _provider_cache[model_name]
    if model_name not in MODELS:
        raise ValueError(f"Unknown model: {model_name}. Choices: {list(MODELS)}")
    kind, model_id = MODELS[model_name]
    if kind == "mock":
        p: LLMProvider = MockProvider()
    else:
        from dotenv import load_dotenv
        load_dotenv()
        if kind == "claude":
            from murshid.providers.claude import ClaudeProvider
            p = ClaudeProvider(model_id=model_id)
        elif kind == "openai":
            from murshid.providers.openai import OpenAIProvider
            p = OpenAIProvider(model_id=model_id)
        elif kind == "gemini":
            from murshid.providers.gemini import GeminiProvider
            p = GeminiProvider(model_id=model_id)
        else:
            raise ValueError(f"Unknown kind: {kind}")
    _provider_cache[model_name] = p
    return p


print("[ui] Building dense + BM25 index (first run downloads BGE-M3 ~2.3GB)...")
INDEX = build_index(data_dir=ROOT / "data", enrichment_provider=MockProvider())
BM25 = build_bm25_index(INDEX)
print(f"[ui] Ready. {len(INDEX)} chunks indexed.")


def ask(
    query: str,
    provider_name: str,
    critic_enabled: bool,
    support_gate_enabled: bool,
) -> tuple[str, str, str]:
    """Return (trace, answer, citations) as three plain-text blocks."""
    if not query or not query.strip():
        return "", "(empty question)", ""
    try:
        provider = _build_provider(provider_name)
    except Exception as e:
        return "", f"Provider init failed: {type(e).__name__}: {e}", ""
    try:
        ans = answer_question(
            query.strip(), INDEX, provider,
            bm25_index=BM25, top_k=5,
            critic_enabled=critic_enabled,
            support_gate_enabled=support_gate_enabled,
        )
    except Exception as e:
        return "", f"Pipeline error: {type(e).__name__}: {e}", ""
    critic_line = (
        f"critic: grounded={ans.critic_grounded} register_match={ans.critic_register_match} "
        f"valid={ans.critic_valid} issues={ans.critic_issues or '[]'}"
    )
    trace_parts = [
        f"category={ans.service_category} (conf {ans.routing_confidence:.2f}) | "
        f"register={ans.question_register} -> {ans.answer_register} | "
        f"behavior={ans.behavior_taken} | "
        f"provider={ans.provider_name}/{ans.provider_model_id} | "
        f"latency={ans.latency_s:.2f}s",
        critic_line,
    ]
    if ans.refusal_reason:
        trace_parts.append(f"refusal_reason: {ans.refusal_reason}")
    trace = "\n".join(trace_parts)
    citations = "\n\n".join(
        f"[{i+1}] {c.chunk_id}  ({c.service_title})  score={c.score:.3f}\n"
        f"{c.passage_text[:300]}{'...' if len(c.passage_text) > 300 else ''}"
        for i, c in enumerate(ans.citations)
    ) or "(no citations — short-circuited before retrieval)"
    return trace, ans.answer_text, citations


with gr.Blocks(title="Murshid") as demo:
    gr.Markdown(
        "# Murshid — Arabic Government-Services RAG\n"
        "Type a question, pick a provider, hit **Ask**. "
        "Real providers need an API key in `.env`."
    )
    with gr.Row():
        query_in = gr.Textbox(
            label="Question",
            lines=3,
            rtl=True,
            placeholder="اكتب سؤالك هنا...",
        )
        provider_in = gr.Dropdown(
            choices=list(MODELS.keys()),
            value="mock",
            label="Model",
        )
    with gr.Row():
        critic_in = gr.Checkbox(
            value=False,
            label="Critic gate",
            info=(
                "Adds a second LLM call to check whether the generated answer "
                "is fully grounded in the retrieved passages and matches the "
                "user's register. If grounded=false → refuses with a template; "
                "if only register mismatches → ships the answer + logs the slip. "
                "Trade-off: extra LLM cost and latency in exchange for catching "
                "ungrounded claims. Off by default here for ad-hoc exploration."
            ),
        )
        support_gate_in = gr.Checkbox(
            value=True,
            label="Support gate",
            info=(
                "Deterministic heuristic (no LLM call). Scans the question for "
                "known policy-hallucination bait patterns (hearsay markers, "
                "auto-action verbs + تلقائياً, special-exemption phrasing) and "
                "verifies the retrieved passages mention every specific claim "
                "term extracted from the question. If a required term is missing "
                "→ refuses before the model generates. Closes the rt-001 / rt-002 "
                "red-team bait class."
            ),
        )
    btn = gr.Button("Ask", variant="primary")
    trace_out = gr.Textbox(label="Pipeline trace", lines=4)
    answer_out = gr.Textbox(label="Answer", lines=6, rtl=True)
    citations_out = gr.Textbox(label="Citations (top-5)", lines=10, rtl=True)
    btn.click(
        ask,
        inputs=[query_in, provider_in, critic_in, support_gate_in],
        outputs=[trace_out, answer_out, citations_out],
    )


if __name__ == "__main__":
    demo.launch()

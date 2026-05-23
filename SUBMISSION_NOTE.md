# Submission Note

**Most proud of:** the AI-first, review-phased build approach. Instead of one pass then review, I ran an interleaved loop — three pre-Phase-1 reviewer rounds on the design contract, then five rounds on shipped code (R1 → R2 → R2-followup → R3 → R3-followup) plus a private adversarial pass between phases. Each round used a reviewer-prompt template (`planning/REVIEW_PROMPT_ROUND{1,2,3}.md`) so calibration compounded. Stale model IDs, `صدر` polysemy false-refuse, APIError over-retry, `code_switched` register-collapse, rt-001/rt-002 bait — all caught early. The 2026-05-23 rerun closed Phase 3's hallucination gap (Claude 3.27 → 1.09; OpenAI steady) after the scope-discipline rule shipped — measurable proof the review loop moved numbers.

**Would revisit:** a judge-based support assessor for novel bait outside the heuristic gate's patterns, plus a critic relevance-axis to close the over-inclusion gap (`avg_irrelevant_facts`).

**LLM provider:** `openai/gpt-5.5-2026-04-23`, `critic=off`. Behavior 1.000, correctness 2.18/3, **1.09 hallucinated facts/q**, $0.14 / 16 cases.

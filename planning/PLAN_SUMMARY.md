# Murshid — Plan Summary (plain English)

Latest version. Source of truth is `MURSHID_KICKOFF.md`; this doc is for quick reorientation.

## What we're building

An Arabic-first system that reads questions about Saudi government services (residency permits, traffic fines, sponsorship transfer, municipal permits, labor office) and answers them in **the same dialect the user wrote in**, with citations back to source documents. If the answer isn't in the documents, it politely declines instead of making something up. CLI only — clone the repo, run one command, see three test questions work (one formal Arabic, one dialect, one out-of-scope refusal).

## Why it's interesting

The RAG pipeline itself is commodity. The hard part is making it Arabic-aware: don't mangle text during cleanup, detect dialect vs. formal Arabic, preserve English domain terms like "OTP" without flipping into "mixed" mode, handle Hijri dates without auto-converting, refuse in a culturally appropriate way. The grading rubric weights Arabic-depth heavier than anything else. We've also folded in four practical techniques from production-grade RAG (chunk metadata enrichment, query routing, structured judge output, refusal logging) that punch above their build cost.

## The data is already done

20 fabricated MSA government FAQ docs, 16 user questions (formal Arabic, Najdi/Khaleeji/Hijazi dialects, code-switched, mixed), 11 gold answers, 10 red-team adversarial cases. Schema clean, citations verbatim-supportable, register taxonomy aligned with the detector. Three rounds of reviewer feedback resolved.

## The plan in steps

**Phase 1 — Make it work end-to-end with fake answers** *(~1.5 hr)*
Set up the repo. Read the data. Build the Arabic text cleaner (lightly — preserve ى/ة/hamza). Build chunking that auto-detects FAQ-style vs. prose-style sources and splits accordingly. **For each chunk, make one cheap LLM call to generate a one-line Arabic summary + 5–10 keywords; concatenate both into the keyword index AND the embedding input so retrieval has more match surface — but leave the raw passage text untouched so citation accuracy still anchors on the verbatim quote.** Build a basic retriever. Plug in a "mock provider" that returns canned answers. Run one demo question. *Done = pipe flows; every chunk has enrichment metadata.*

**Phase 2 — Make it Arabic-aware** *(~1.5 hr)*
Add the register detector (formal/dialect/mixed). **Add a service-category router that classifies every query into one of `{iqama, traffic_fines, sponsorship_transfer, municipal_permits, labor_office, out_of_scope}` — rules-first using Arabic service keywords like `إقامة / مخالفة مرورية / كفالة / رخصة بلدية / رخصة عمل`, with LLM fallback for low-confidence cases. The category becomes a metadata filter on retrieval; `out_of_scope` short-circuits to escalation before retrieval even runs.** Add the dialect-to-formal query rewriter. Wire multi-view retrieval (raw + cleaned + MSA-rewrite) with the category filter. Add keyword (BM25) search alongside meaning-based. Add a self-check pass that confirms the answer matches the question's register and is grounded. Run the three-question demo on the mock provider. *Done = the demo works on all three, including the out-of-scope question being classified and refused before retrieval runs.*

**Phase 3 — Plug in real LLMs and run the first benchmark** *(~1.5 hr)*
Wire up Claude (`sonnet-4-6`) and OpenAI (`gpt-5.5`). Build the bench runner. Score each provider on 7 dimensions. **The correctness + register-match judge returns a structured object — `{matched_facts, missing_facts, irrelevant_facts, correctness_score, register_match_score}` — so the results table shows per-provider fact-level breakdowns ("model X retrieved 3/4 gold facts and hallucinated 1") instead of just aggregate 0–3 numbers.** Two passes per provider — critic on AND off — to separate raw model quality from orchestration. Judge is Gemini (out-of-family), with a 3-case Opus-4.7 sanity swap to measure judge self-preference bias. *Done = a comparison table for Claude vs. OpenAI with real fact-level diagnostics + the quantified judge-bias delta.*

**Phase 4 — Run the trust-thinking tests** *(~30 min)*
Run the 10 red-team cases: policy-hallucination bait, code-switched multi-clause, Ramadan/Hijri-context, low-confidence retrieval, dialect-vs-MSA mismatch, Hijri ambiguity, out-of-scope, authority bait, citation-translation trap. Score the 4-state behavior match. **Every refusal, partial-escalation, or clarification request writes a JSONL entry to `bench/refusal-log.jsonl` capturing the question, the retrieved top-k, and why the system stopped — that becomes concrete material for the AI journal ("here's exactly what the system declined and why") and demonstrates engineering rigor.** Start drafting CREATIVE.md with the red-team harness as the centerpiece, plus three "what we'd build at scale" mentions: per-service-category dual-source retriever, conversational mode (standalone-question condensation), knowledge-graph cross-doc reasoning. *Done = system survives adversarial pressure on paper, refusal log populated, CREATIVE.md outlined.*

**Phase 5 — Add Gemini and Falcon-Arabic** *(~1 hr, optional)*
Add Gemini as a third frontier provider. Add Falcon-Arabic via Ollama (the residency-aware Arabic-native option a KSA production deployment would want). Re-run the bench with all 5 providers. The data picks the production default. *Done = 5-row bench, winner chosen by numbers.*

**Phase 6 — Write the architecture doc** *(~1 hr)*
`ARCHITECTURE.md`: system diagram, component table, three decision records (embedding choice, provider strategy, normalization + conservative allowlist), Arabic-specific risks (diglossia, code-switching, hallucinated policy, RTL bugs), one paragraph on what production-in-GCC needs (Saudi PDPL, data residency, agent escalation liability — cite the Air Canada chatbot case), and a worked trace through the Khaleeji code-switched question. ADR 2 leans on the fact-count breakdowns from the structured judge, and the Arabic-keyword service router gets explicit billing as an Arabic-depth signal. *Done = a reviewer who reads only this doc can predict the system's behavior on edge cases.* (Pre-staged content in `planning/DELIVERABLES_DRAFT.md`.)

**Phase 7 — Write the AI journal** *(~30 min)*
Curate the working log into `AI_JOURNAL.md`: three prompts worth showing, one Arabic-specific mistake the agent made that we caught, one thing we let the agent do unsupervised with guardrails, honest reflection on where AI helped and where it hurt. The refusal log gives concrete material to draw from. *Done = vibe-coding fluency demonstrated.*

**Phase 8 — Write the README + final polish** *(~30 min)*
Written last, from what actually shipped. One-sentence what, one-command setup, the three demo questions, pointers to architecture and bench. CREATIVE.md headlines the red-team harness AND mentions the three path-not-taken-at-scale items as one-paragraph "what production looks like beyond take-home scope." If time remains: Hijri-date module + Arabic-Indic numeral normalization as bonus creative items. *Done = reviewer reads README in 2 minutes and knows what to do.*

**Phase 9 — Smoke test and submit** *(~15 min)*
Clone the repo to a fresh directory, follow the README, confirm the three demo questions work, write the 150-word submission note (most proud of, would revisit, LLM provider). Submit.

## What we drop if time gets tight (in order)

1. Hijri-date module
2. Arabic-Indic numeral normalization
3. Falcon-Arabic (heaviest to install — document as "explored but deferred")
4. Gemini as a benchmarked provider (keep it as judge though)
5. Optional reranker
6. The smaller-Arabic-embedder experiment
7. Refusal-tone sub-metric
8. Third frontier provider in the bench (Claude + OpenAI + Mock is the floor)

The four production-RAG additions (chunk metadata, router, structured judge, refusal log) are baked into never-cut Phase 1/2/3/4 core — they're surgical, not optional.

**Never cut:** Phase 1, Phase 2 register + router + multi-view retrieval, Phase 3 bench with ≥2 providers + structured judge, Phase 4 red-team + behavior metric + refusal log, Phase 6 architecture doc, Phase 7 journal, Phase 8 README, Phase 9 smoke test + submission note.

## What the reviewer sees

Clone repo → 2-minute README → one command → three answered questions (formal Arabic / Khaleeji dialect / refused out-of-scope) all in the right register with citations → architecture doc that lets them predict behavior on questions they invent → `bench/results.md` showing real provider comparison numbers AND fact-level breakdowns ("provider X averaged 3.2/4 matched gold facts, 0.4 hallucinated per question") → `bench/refusal-log.jsonl` showing exactly what the system declined and why → AI journal showing how we worked with the agent honestly → CREATIVE.md headlining the red-team harness plus three "what production looks like at scale" sections. Under 10 minutes total per the brief's expectation.

Authorization phrase: **`Start Phase 1`**.

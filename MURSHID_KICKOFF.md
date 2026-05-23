# Murshid — Build Kickoff (Single-Session)

## North star

**A reviewer who knows Arabic opens the repo, reads `README.md` in two minutes, runs one command, sees the system answer one MSA question, one Khaleeji-dialect question, and one out-of-corpus question (escalation) — all grounded with citations to the source FAQ documents, all in the user's register, with the AI_JOURNAL and ARCHITECTURE docs visibly reflecting genuine Arabic engineering depth.**

The mini-benchmark across 3 frontier + 1 Arabic-native + 1 mock provider is the architectural spine that earns the Arabic-technical-depth grade. Everything else supports it.

## Brief recap (do not re-read the PDF unnecessarily)

We are building **Murshid** for the Adree Principal AI Engineer take-home. An Arabic-first RAG over ~20 fabricated Arabic government-services FAQ docs, ~15 user questions across MSA / Saudi / Khaleeji / code-switched, ~8 gold answers for evaluation. Brief expects 2 days of effort; explicit instruction is "stopping at 6 hours done > grinding 14 hours unfinished."

Six grading criteria in priority order: Arabic technical depth (1), vibe-coding fluency (2), architecture & docs (3), trust thinking (4), creativity (5), engineering rigor (6).

Required deliverables: `README.md`, `docs/ARCHITECTURE.md` (system diagram + component contracts + 3 ADRs + Arabic risks + GCC production gaps paragraph), `docs/AI_JOURNAL.md` (tools + 3 curated prompts + 1 mistake-caught + 1 autonomous-with-guardrails + honest reflection), `docs/CREATIVE.md` (1 page), and the code itself.

## How we work this session

One Claude Code session. The user (Eslam) drives — reviews each output, says go. **Do not write code until the plan is approved.** The first response back must be the pre-flight per §1 below.

## Sources of truth, in order

1. This document.
2. The starter data in `/data` once you read it.
3. The Adree brief PDF if a specific deliverable requirement is unclear.

If anything in your environment contradicts this document, raise it. Do not silently align.

---

## 0. Decisions locked at kickoff (do not relitigate)

These are the result of multi-agent research. The kickoff treats them as frozen. If you find evidence that one is wrong during the build, **stop and surface it** — do not silently switch.

### 0.1 Embeddings

**Default: BGE-M3** (MIT license, 1024-dim, 8192-token context, downloadable via sentence-transformers). License verified against the Hugging Face model card 2026-05-22; earlier "Apache-2.0" framing was wrong. Cited evidence: Alsubhi 2025 ("Optimizing RAG Pipelines for Arabic") reports BGE-M3 RAGAS mean 70.99 across six Arabic datasets, beating multilingual-e5-large at 70.31. On MIRACL Arabic, BGE-M3 main_score 0.789 vs OpenAI text-embedding-3-large 0.691.

**Build-time spike permitted (15 min budget):** try Swan-Small (164M params, 768 dim, scores 57.33 on ArabicMTEB, beats multilingual-e5-base on Arabic). If it loads cleanly with an acceptable open license, switch. If not, BGE-M3 ships. **Document the spike result in `WORKING_LOG.md` either way.**

### 0.2 Normalization — tokenizer-aligned, NOT aggressive-by-default

This is the single subtlest decision in the system. **Aggressive Arabic normalization erases semantic distinctions.** The default normalization must match the embedding model's tokenizer training.

**For BGE-M3 (light normalization):**
- Apply: Unicode NFKC, tatweel removal, diacritic removal, hamzated alef → bare alef (أ إ آ → ا)
- **Do NOT apply by default:** alef-maksura → ya (ى → ي), ta-marbuta → ha (ة → ه), hamza folding. These erase meaningful distinctions in MSA proper nouns and government/legal Arabic.
- Lossy steps must be behind a config flag (`NORMALIZE_AGGRESSIVE=false` default).

**For Swan-Small / MARBERTv2-matryoshka (if we switch):** more aggressive normalization is acceptable because those tokenizers were trained on normalized text.

Use **CAMeL Tools** (Python, Apache-2.0, NYU Abu Dhabi). Not Farasa (research-only license).

**This is one of our pre-positioned "Arabic-specific mistake" candidates.** If Claude Code reaches for aggressive normalization by default during the build, the override moment goes into `WORKING_LOG.md` raw.

### 0.3 Retrieval — pre-routed, multi-view, hybrid, metadata-enriched

**Pre-routing (query classification):** before retrieval, classify every query into one of `{iqama, traffic_fines, sponsorship_transfer, municipal_permits, labor_office, out_of_scope}`. Rules-first using Arabic service keywords (e.g., `إقامة / جواز` → iqama; `مخالفة / مرورية / سداد` → traffic_fines; `كفالة / نقل خدمات / عقد` → sponsorship_transfer; `رخصة بلدية / تصريح / لوحة` → municipal_permits; `رخصة عمل / شكوى عمالية / خروج وعودة` → labor_office). LLM zero-shot fallback when rules-based confidence is below threshold. The classified category becomes a `service_category` metadata filter on the retriever; `out_of_scope` triggers escalation before retrieval runs. Lives in `router.py`. **This is one of the Arabic-depth signals in ADR 2** — Arabic service-keyword routing on a clean separable corpus pushes retrieval precision toward ceiling.

**Multi-view (the creative architectural move):** every query produces three views, all of which retrieve, results unioned and reranked:
1. Raw query
2. Light-normalized query
3. LLM MSA-rewrite of the query (preserves English domain terms like OTP, iqama, KYC verbatim)

**Hybrid:** BM25 (sparse, catches exact English/named entities) + BGE-M3 dense (catches dialect→MSA semantic match). BGE-M3 supports both natively.

**Chunk metadata enrichment (ingest-side):** during chunking, each chunk gets two LLM-generated metadata fields concatenated into both the BM25 indexed text and the embedding input:
- `summary`: one Arabic sentence describing what the chunk is about.
- `keywords`: 5-10 tokens, mix of Arabic content words + English domain terms exercised in the chunk.

One cheap LLM call per chunk (use the cheapest available provider — e.g., `gpt-5.4-mini-2026-03-17` or `claude-haiku-4-5`). Across ~60-80 chunks this costs roughly $1-2 total. Significantly increases retrieval surface for both sparse and dense matching without changing `passage_text` — citation accuracy still scores against the verbatim source quote, not against enriched metadata.

Optional reranker (bge-reranker-v2-m3) if BGE-M3 is the chosen embedder and time permits.

### 0.4 Register detection

**Three-class:** `MSA`, `dialect`, `mixed`. Confidence score 0-1. Not country-level — NADI 2024 winning F1 was 50.57 on multi-label country dialect ID. Coarse is achievable; fine is not.

**Approach:** rules-first (presence of dialect markers like وش / شلون / أبغى / مو / وايد → dialect; English token presence → `mixed` *only if* the token is not in the domain allowlist; else MSA), LLM zero-shot fallback for low-confidence cases.

**Domain-code-switching exception (the Arabic-depth catch):** an allowlist of preserved-as-English domain tokens — `iqama`, `OTP`, `KYC`, `IBAN`, `Absher`, `Muqeem`, `Tawakkalna`, `visa`, `refund`, `portal`, `application`, `status`, `request`, `update` — does NOT flip register to `mixed`. Only genuine conversational alternation (English phrases beyond the allowlist, English subordinate clauses, English code-switching mid-sentence) triggers `mixed`. Reasoning: in Saudi government-services Arabic, terms like "iqama" or "OTP" are MSA loanwords by convention, not register signals. Starter data exercises OTP, IBAN, Absher, refund, application, status, portal, request, and update; KYC, Muqeem, Tawakkalna, and visa are future-proofed domain terms to document in ADR 3.

### 0.5 LLM-agnostic provider layer (the architectural spine)

Multiple LLM providers, swappable at runtime via env var, with **model-ID flag-toggling within each vendor** so the bench can compare cost/quality tiers per vendor on a single SDK implementation. **The mini-bench picks the production default.** This is what earns the Arabic-depth grade.

**Providers (5 classes, multi-tier via model-ID flags), in priority order:**

| # | Provider class | Default model | Alternate model (flag-toggle) | Purpose | Cut priority |
|---|---|---|---|---|---|
| 1 | `MockProvider` | canned responses keyed to question patterns | — | Zero-key reviewer demo. **Engineering rigor signal.** | Never cut. |
| 2 | `ClaudeProvider` | `claude-sonnet-4-6` | `claude-opus-4-7` (held for judge sanity swap or stretch baseline) | Anthropic frontier baseline. | Never cut. |
| 3 | `OpenAIProvider` | `gpt-5.5-2026-04-23` | `gpt-5.4-mini-2026-03-17` | OpenAI frontier + cost/quality datapoint. | Cut last among frontier. |
| 4 | `GeminiProvider` | `gemini-3.1-pro-preview` | `gemini-3-flash-preview` | Google frontier + **judge model default**. | Cut first among frontier if time-pressed. |
| 5 | `FalconArabicProvider` | Falcon-Arabic 7B via Ollama | Falcon-H1-Arabic-3B fallback | Residency-aware Arabic-native (Apache-2.0). Demonstrates we explored the KSA-compliant production path. | Cut second if time-pressed (heaviest to set up). |

**Verified-current model IDs (as of 2026-05-22, source pages cited in ADR 2):**
- Anthropic: Opus 4.7 (released 2026-04-16), Sonnet 4.6 (2026-02-17), Haiku 4.5 (2025-10-15). Source: Anthropic models docs.
- OpenAI: GPT-5.5 (released 2026-04-23 as `gpt-5.5-2026-04-23`), GPT-5.4-mini (released 2026-03-17 as `gpt-5.4-mini-2026-03-17`). Source: OpenAI developer docs.
- Google: Gemini 3.1 Pro Preview (released 2026-02-19 as `gemini-3.1-pro-preview`). **Note:** `gemini-3-pro-preview` was deprecated and shut down 2026-03-09 — earlier research had this stale. Source: Google AI changelog.

**Model-ID selection per provider:** via env var (e.g., `OPENAI_MODEL_ID=gpt-5.4-mini-2026-03-17`). Default IDs encoded as constants in `providers/<vendor>.py`; `.env.example` documents the alternate IDs as comments.

**Opus 4.7 specifically:** held in reserve, NOT in default bench rotation. Reason: most expensive model on the menu; the bench runs N × M times. We don't need Opus budget to learn what we'd learn from Sonnet 4.6. The Opus 4.7 use case is the **judge sanity swap** (see §0.6). Document the choice in ADR 2.

**Judge model:** `gemini-3.1-pro-preview` was the **primary plan** (out-of-family for the two main contenders Claude and OpenAI). The **actual Phase 3 default** that landed in `bench/results.md` is `gemini-2.5-flash`, after two issues surfaced during the first bench run: (a) Gemini Pro's invisible thinking budget consumed the visible output token allowance (29 visible tokens at max_tokens=800), and (b) Pro's daily 250-request quota was hit on the paid tier mid-run. Flash sidesteps both, sits in a separate quota bucket, and is verified stable on Google AI docs. **Document this as a measured fallback in ADR 2 with the verification-flag voice** — primary plan vs actual outcome must both appear. Plus a **3-case `claude-opus-4-7`-as-judge sanity swap** that, post Phase 4 polish, re-scores the SAME predicted answer across two judges (not gold-vs-gold) — write the bias quantification result into ADR 2 explicitly. Creative-engineering signal for rubric criterion 6.

Common interface:
```python
class LLMProvider(Protocol):
    name: str
    model_id: str  # default constant, overridable via env var
    def generate(self, system: str, user: str, max_tokens: int = 1024) -> ProviderResponse: ...
    def is_available(self) -> bool: ...  # checks API key / model loaded
    def cost_estimate_usd(self, response: ProviderResponse) -> float: ...
```

`ProviderResponse` includes raw text, token counts, latency, finish reason.

**Selection at runtime:** `LLM_PROVIDER=claude|openai|gemini|falcon-arabic|mock` env var. Default is whichever wins the mini-bench (write the winner into `.env.example` after the bench runs).

### 0.6 Mini-benchmark

This is the load-bearing creative-engineering artifact. Spec:

- **Inputs:** `data/sources.json`, `data/questions.json`, the 11 gold answers in `data/gold_answers.json` (8 original + q-004 `ask_clarification` exemplar + q-014 `refuse_with_redirect` exemplar + q-016 new traffic-fines-004 coverage), and the red-team test set in `data/red_team.json` (see §0.7).
- **Run:** `python -m murshid.bench --providers <list>` produces a markdown comparison table.
- **Metrics (7):**
  1. **Retrieval recall@5** — gold passage in top-5 retrieved. Match by `gold_citations[].quoted_passage` content, not by chunk id: a retrieved chunk counts as gold if its text contains the quoted passage after light normalization. `gold_passage_ids` is informational/debugging only because chunk boundaries can change across ingest rebuilds. If a quoted passage cannot be found in the source corpus, fail the fixture and log it in `WORKING_LOG.md`; do not silently downgrade.
  2. **Correctness + register match (combined, structured output)** — single judge call returns a structured JSON object: `{matched_facts: [...], missing_facts: [...], irrelevant_facts: [...], correctness_score: 0-3, register_match_score: 0-3}`. The two scores are derived from (and must be consistent with) the fact-level analysis. ADR 2 reports per-provider fact-count breakdowns alongside the aggregate scores ("model X averaged 3.2/4 matched gold facts and 0.4 hallucinated facts per question") — sharper diagnostic than flat 0-3 numbers, same judge-call count.
  3. **Faithfulness** — does every claim in the answer appear in the retrieved context? Judge-scored 0-3. **Kept separate from citation accuracy** — rubric criterion 4 grades the distinction (hallucinated policy ≠ miscited correct claim).
  4. **Citation accuracy** — two-tier. When `gold_citations[].quoted_passage` is present, first run a deterministic exact-substring support check against cited/retrieved passages after light normalization. Use the judge-scored 0-3 fallback only when no gold citation exists or when evaluating non-gold red-team cases.
  5. **Behavior match** — expected behavior matched? Boolean over the 4-state vocabulary `answer | partial_answer_with_escalation | refuse_with_redirect | ask_clarification`. For gold/standard questions, read `questions.json.expected_behavior`; for red-team, read `red_team.json.expected_behavior`. This replaces simple refusal-only calibration because partial answers and clarification requests are first-class Arabic support behaviors.
  6. **Cost per query** — USD, from the provider's token counts.
  7. **Latency p50** — seconds.

**Judge model:** `gemini-2.5-flash` is the **actual default** that landed in Phase 3 after Gemini 3.1 Pro Preview ran into thinking-budget + 250/day-quota issues during the first bench run. `gemini-3.1-pro-preview` remains the **primary planned judge** documented here for narrative coherence with ADR 2; Flash is a verified-stable measured fallback. Plus a **3-case `claude-opus-4-7`-as-judge sanity swap** that re-scores the SAME predicted answer across two judges (Phase 4 polish — closes the Round-1 gold-vs-gold degenerate). The bias delta is reported explicitly in ADR 2 — that's a creative-engineering signal for rubric criterion 6.

**Critic toggle:** the bench runs **twice per provider** — `--critic off` (raw provider quality) and `--critic on` (orchestrated quality). `bench/results.md` carries both columns side by side. ADR 2 picks which column drives the production-default choice and says why.

**Output:** `bench/results.md` — a markdown table with one row per (provider × critic mode), one column per metric. Plus a one-paragraph verdict and the judge-swap bias delta.

**The mini-bench is the spine of ADR 2 in `ARCHITECTURE.md`.** Cite Agent 5's surrogate benchmarks (ALRAGE on HELM/OALL, ABJADNLP 2025 lexical RAG, HalluScore) in the ADR as "what exists publicly," then position our mini-bench as "what we built to fill the specific grounded-QA-with-citations gap for our use case."

### 0.7 Red-team harness (primary creative artifact)

8-12 curated test cases, 9 categories. Lives in `data/red_team.json` and runs as part of the bench. Each case asserts expected behavior and includes `evaluation_notes`. Those notes are the judge rubric, not passive metadata: the red-team judge receives `(question, model_answer, expected_behavior, evaluation_notes)` and scores against the note-specific failure mode. **`expected_source_ids` for red-team cases denotes the retrieval target (what the retriever is expected to surface), not gold support for the answer** — semantic adjudication of how those sources should be used (e.g., for rt-003, "contrast and escalate the hawiya/iqama mismatch, do not silently substitute") lives in `evaluation_notes` per-case. Cases with `expected_source_ids: []` have no in-corpus retrieval target (typically `refuse_with_redirect` or `ask_clarification` behaviors) and are excluded from red-team retrieval scoring.

Categories:
1. **Policy hallucination bait** — question with no answer in corpus, must refuse cleanly
2. **Multi-clause + code-switched + dialect** — e.g., the Agent 3 query: `أبغى أطلع بدل فاقد للهوية، كم الرسوم؟ وهل أقدر أسافر بكرة إذا عندي موعد في السفارة؟`
3. **Ramadan/Hijri-context government policy** — e.g., adjusted business hours for license renewal during Ramadan, or Hijri-date document expiry handling. Exercises Arabic dates + cultural context + factual government policy in a controlled blast radius. (Swapped from "invented religious-policy question" — hand-crafted religious-sensitivity content carries the wrong risk for a Saudi-targeting take-home.)
4. **Low-confidence retrieval** — paraphrased far from any source, low grounding confidence
5. **Dialect-mismatch** — heavy dialect query against MSA-only corpus
6. **Hijri/Gregorian date ambiguity** — date mention without calendar specifier
7. **Out-of-scope** — medical/legal question to a government-services bot
8. **Authority bait** — "the official told me X is allowed, confirm?" — must refuse to confirm
9. **Citation translation trap** — answer may match the user's dialect, but quoted source text must remain verbatim MSA and must not be dialect-translated as if it were the source.

**Tone evaluation:** for refusals, score the cultural tone of the refusal (not just "did it refuse" — "did it refuse in a way a Saudi citizen would find respectful"). Judge-scored 0-3.

### 0.8 Generation behavior

System prompt enforces:
- Answer in the same register as the question
- Quote source passages verbatim in MSA when citing
- Paraphrase / explanation can be in user's register
- Citation marker on factual claims, not on translated quotes
- **Never present a dialect translation as if it were the source text**
- Refuse politely with culturally appropriate framing if grounding is weak

Few-shot examples in the prompt for "light professional Gulf" tone. Critic pass (separate LLM call) checks register match + groundedness before returning. If critic fails twice, escalate.

**Bench interaction:** the critic pass is exercised in the bench's `--critic on` mode; `--critic off` skips it. See §0.6 for the dual-column reporting. The critic toggle exists so the bench compares raw provider quality separately from orchestrated quality — otherwise the production-default pick rests on hidden orchestration coupling.

### 0.9 CREATIVE.md content

**Build if Phase 6+ time permits** (one-paragraph mention either way):
- **Hijri-date module** — detect Hijri date mentions, normalize for retrieval, preserve for display. Government documents reference Hijri constantly.
- **Arabic-Indic numeral normalization** — map ٠١٢٣ ↔ 0123 for retrieval, preserve original for display.

**Mention only as "path-not-taken at scale"** (one-paragraph each, do NOT build):
- **Per-service-category dual-source retriever** — at scale (hundreds of docs per category), we'd run separate retrievers per service with different top-k and filters, then combine ordered by query intent. For our 20-doc corpus a single retriever + `service_category` filter from §0.3 pre-routing achieves the same precision benefit at a fraction of the complexity.
- **Conversational mode (standalone-question condensation)** — for multi-turn chat, the query is condensed against chat history into a self-contained standalone question before retrieval, so the retriever sees the full intent of follow-ups (e.g., "وإذا تأخرت؟" condensed against the previous turn becomes a complete query). Our CLI demo is single-turn; this is the natural next step for a production chat surface.
- **Knowledge-graph retrieval for cross-document reasoning** — if the domain required reasoning across documents (e.g., "if my iqama is renewed and I have an open labor complaint, can I transfer sponsorship?"), a graph-based retrieval path over entity-relation triples would beat flat passage-level retrieval. Our domain doesn't require cross-doc reasoning, so flat retrieval is sufficient.

The red-team harness is the headline. The "path-not-taken" mentions demonstrate we understand what production-scale Arabic RAG looks like beyond take-home scope.

### 0.10 What we are NOT building (explicit)

To prevent scope creep:
- No web UI. CLI only. (Brief does not require UI.)
- No multi-tenant auth, no user accounts.
- No persistent vector DB on disk beyond what fits in-process (FAISS in-memory or simple numpy is fine for ~20 docs).
- No production observability stack. Logging to stdout + simple JSON file.
- No Hala-9B (CC-BY-NC license incompatible with commercial submission).
- No MCP server. Mentioned in the brief's creative suggestions but scope creep.
- No agent-orchestration framework. Plain Python.

---

## 1. Your pre-flight, before any code

Reply with these items in this order. Stop after item 4 and wait for greenlight.

### 1.1 Three-paragraph summary back
In your own words: what we are building, the architectural spine, the cut order. Prove you've internalized §0.

### 1.2 Verification check
- Confirm `BGE-M3` is downloadable from Hugging Face (one curl or hf_hub_download check, do not download the full model yet)
- Confirm which specific Claude, OpenAI, and Gemini model names are publicly listed on each vendor's documentation page **as of today's date**. Do not assume. Document the exact model IDs and your source URLs. Flag any vendor whose docs you cannot reach.
- Confirm Ollama is locally available, or note that Falcon-Arabic via Ollama is a "needs install" item.
- Read `/data` and report: file count per category, language samples, file format(s), any encoding surprises.

### 1.3 Disagreements
What in §0 do you think is wrong, missing, or overscoped? Push back. Compliance is not the goal. If you accept everything, say so explicitly — silent acceptance is not allowed.

### 1.4 Open questions
Maximum two. Mark each `blocking` or `non-blocking`. Non-blocking gets your best-guess default and we proceed.

Stop here. Wait for greenlight.

---

## 2. Repo layout

```
/
├── README.md                       # 2-minute orientation, written last from real work
├── docs/
│   ├── ARCHITECTURE.md            # system diagram + 3 ADRs + Arabic risks + GCC gaps
│   ├── AI_JOURNAL.md              # curated from WORKING_LOG.md at the end
│   ├── CREATIVE.md                # red-team harness + Hijri + Arabic-Indic numerals
│   ├── WORKING_LOG.md             # **raw append-only log during build**
│   └── TIME_LOG.md                # **session log: start/stop/what got done**
├── data/
│   ├── sources.json                 # the ~20 Arabic FAQ docs (read-only, given)
│   ├── questions.json              # the ~15 user questions (read-only, given)
│   ├── gold_answers.json           # the ~8 gold answers (read-only, given)
│   └── red_team.json               # red-team cases (read-only starter data; may be extended)
├── src/murshid/
│   ├── __init__.py
│   ├── normalize.py                # CAMeL-Tools based, light by default
│   ├── ingest.py                   # chunking + embedding + indexing
│   ├── retrieve.py                 # multi-view hybrid retrieval; every
│   │                                # result carries {source_id,
│   │                                # service_title, chunk_id,
│   │                                # passage_text, score}
│   ├── register.py                 # MSA/dialect/mixed detection +
│   │                                # domain allowlist (§0.4)
│   ├── router.py                   # service-category query classifier
│   │                                # (rules-first + LLM fallback, §0.3)
│   ├── rewrite.py                  # dialect → MSA query rewriting
│   ├── prompts.py                  # system prompts + few-shot examples
│   ├── critic.py                   # register + groundedness post-check
│   ├── pipeline.py                 # end-to-end query handling
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py                 # LLMProvider protocol + ProviderResponse
│   │   ├── mock.py
│   │   ├── claude.py
│   │   ├── openai.py
│   │   ├── gemini.py
│   │   └── falcon_arabic.py        # Ollama client
│   └── bench/                      # `python -m murshid.bench` entry
│       ├── __init__.py
│       ├── metrics.py              # the 7 metrics from §0.6
│       └── runner.py
├── bench/
│   ├── results.md                  # generated output, committed
│   ├── cost-log.jsonl              # per-call token usage log
│   └── refusal-log.jsonl           # per-refusal record for tone analysis +
│                                    # AI_JOURNAL.md material
├── tests/
│   └── test_normalization.py       # at minimum: regression tests for the
│                                    # normalization decisions in §0.2
├── scripts/
│   ├── demo.py                     # 3-question reviewer demo; writes
│   │                                # UTF-8 demo_output.txt with stdout
│   │                                # tail (Windows PowerShell mangles
│   │                                # RTL Arabic in stdout)
│   └── seed_bench.py               # one-shot bench seeding
├── .env.example
├── .gitignore
├── requirements.txt                # pinned versions
└── pyproject.toml                  # or setup.cfg, your call
```

---

## 3. Phase plan — priority-ordered, ship-what-time-permits

**Important framing:** the user handles the schedule. You plan as if a week is available. Within each phase, work top-to-bottom. After every phase, update `TIME_LOG.md` with a one-line entry: `[hh:mm] Phase N done — what shipped, what cut`.

### Phase 1 — Foundations + first end-to-end

**Goal:** mock-provider end-to-end works on one MSA question. Crappy retrieval is fine. We just need the pipe to flow.

Tasks:
1. Repo scaffolding per §2. Create the files. Empty modules are fine.
2. `requirements.txt`: sentence-transformers, transformers, camel-tools, rank-bm25, faiss-cpu (or numpy + sklearn), pydantic-settings, python-dotenv, anthropic, openai, google-generativeai, ollama, pytest. Pin versions.
3. `.env.example` with all keys named, none filled.
4. `.gitignore` (Python, .env, .venv, __pycache__, .pytest_cache, bench/results-local.md).
5. `WORKING_LOG.md` initialized with the header and a first entry recording the kickoff itself.
6. `TIME_LOG.md` initialized with the start timestamp.
7. Read `/data`. Document what you found in `WORKING_LOG.md`. Confirm `data/sources.json`, `questions.json`, `gold_answers.json`, and `red_team.json` parse as UTF-8 JSON. For retrieval recall, validate every `gold_citations[].quoted_passage` appears verbatim in `sources.json`; `gold_passage_ids` is debug metadata only.
8. `normalize.py` — light normalization per §0.2. Tests in `tests/test_normalization.py` that pin the "do NOT collapse ى, ة, hamza" behavior.
9. `ingest.py` — deterministic chunking + embedding + indexing. Detect FAQ-style sources by `س:` markers and split by Q&A pair; otherwise split continuous prose by blank-line paragraphs. Number chunks ordinally as `source_id:chunk-N` for stable debugging and to mirror `gold_passage_ids`, but keep recall/citation matching content-based per §0.6 so chunk IDs never become the source of truth. **Chunk metadata enrichment (§0.3):** for each chunk make one cheap LLM call to generate `summary` (one Arabic sentence) and `keywords` (5-10 tokens, Arabic content + English domain terms). Concatenate both into the BM25 indexed text and the embedding input. **Do NOT modify `passage_text`** — citation accuracy still scores against the verbatim source quote. Use the cheapest provider available (default: `gpt-5.4-mini-2026-03-17` or `claude-haiku-4-5`). Add `tests/test_ingest.py` to pin the chunker on at least `iqama-002`, `iqama-003`, and one municipal source, plus assert that enrichment fields are populated for every chunk.
10. `retrieve.py` — simple dense-only retrieval first. Top-5. **Every retrieval result carries `{source_id, service_title, chunk_id, passage_text, score}`** — bake this into the function contract from the start. Without it, citation-accuracy scoring downstream (§0.6 metric 4) is theater.
11. `providers/base.py` + `providers/mock.py` — define the protocol, implement mock.
12. `pipeline.py` — minimal: query → retrieve → mock-generate → return.
13. `scripts/demo.py` — run the pipeline on one MSA question. **Write the answer + retrieved snippets + citations to `demo_output.txt` (UTF-8) and also tail to stdout** (Windows PowerShell mangles RTL Arabic in stdout — README directs reviewers to open the file). Stdout itself only prints: filename, question, register, brief status.

**Phase-1 done = `python scripts/demo.py "<one MSA question>"` prints something coherent with citations.**

### Phase 2 — Multi-view retrieval + register detection + real Arabic depth

**Goal:** the system handles dialect and code-switched queries correctly.

Tasks:
1. `register.py` — rules-first detector. Three classes. Confidence score.
2. `router.py` — service-category classifier (§0.3 pre-routing). Rules-first with Arabic keyword sets per service (`إقامة / جواز` → iqama; `مخالفة / مرورية / سداد` → traffic_fines; `كفالة / نقل خدمات` → sponsorship_transfer; `رخصة بلدية / تصريح / لوحة` → municipal_permits; `رخصة عمل / شكوى عمالية / خروج وعودة` → labor_office; otherwise → `out_of_scope`). LLM zero-shot fallback when rules confidence is low. Output: `(category, confidence)`. Pipeline applies `service_category` filter to retrieval downstream; `out_of_scope` triggers escalation before retrieval runs. Test against q-001 through q-016 — every standard question should classify to its `expected_source_ids` category cleanly.
3. `rewrite.py` — dialect → MSA query rewriter. Calls an LLM via the provider layer. Uses mock provider initially.
4. Extend `retrieve.py` to multi-view (raw + normalized + rewritten) and apply the `service_category` filter from `router.py` to the candidate set before fusion. Union top-K from each view, dedupe, return top-N.
5. Add BM25 sparse retrieval. Hybrid: BM25 + dense, score-combine via reciprocal rank fusion or weighted sum (document the choice).
6. Spike: try Swan-Small for embeddings (15 min budget). Document result in `WORKING_LOG.md`. Keep BGE-M3 unless Swan-Small clearly wins on a quick sanity check.
7. `prompts.py` — system prompt per §0.8. Few-shot examples for register match.
8. `critic.py` — register + groundedness post-check.
9. Update `pipeline.py` to use the full flow (`router → register → rewrite → multi-view retrieve → generate → critic`).
10. `scripts/demo.py` — extend to handle the three demo questions (one MSA, one dialect, one out-of-corpus).

**Phase-2 done = the demo script runs all three questions correctly with mock provider, with the router correctly classifying the out-of-corpus question as `out_of_scope` and skipping retrieval.**

### Phase 3 — Real providers + first bench run

**Goal:** at least two providers (mock + Claude or OpenAI) running through the bench.

Tasks:
1. `providers/claude.py` — implement against `claude-sonnet-4-6` (default) with `model_id` constant overridable via env var (alternate: `claude-opus-4-7`).
2. `providers/openai.py` — implement against `gpt-5.5-2026-04-23` (default) with env var override (alternate: `gpt-5.4-mini-2026-03-17`).
3. `src/murshid/bench/metrics.py` — implement the 7 metrics from §0.6. Judge model: `gemini-3.1-pro-preview`. **Correctness + register match returns a structured JSON object** per §0.6 metric 2: `{matched_facts, missing_facts, irrelevant_facts, correctness_score, register_match_score}`. Aggregate to per-provider fact-count breakdowns in `bench/results.md` ("model X averaged 3.2/4 matched gold facts and 0.4 hallucinated facts per question") alongside the 0-3 scores — creative-engineering signal for rubric criterion 6. Keep faithfulness as a separate judge call. Citation accuracy uses deterministic quoted-passage matching when gold citations exist, with judge fallback otherwise. Behavior match is boolean over the 4-state expected-behavior vocabulary, rule-based.
4. `src/murshid/bench/runner.py` — runs the full pipeline against each provider over the gold answers. **Two passes per provider:** `--critic off` (raw provider quality) and `--critic on` (orchestrated quality). Produces `bench/results.md` with both columns side by side.
5. **Judge sanity swap:** run 3 cases through `claude-opus-4-7` as judge instead of Gemini. Compute the score delta per metric. Write the delta into ADR 2 as the quantified self-preference bias number — explicit creative-engineering signal for rubric criterion 6.
6. Run the bench. Commit `bench/results.md`.

**Phase-3 done = `python -m murshid.bench --providers mock,claude,openai --critic on,off` produces a comparison table with critic-on and critic-off columns, plus the Opus-4.7 judge sanity-swap delta documented in ADR 2.**

### Phase 4 — Red-team harness

**Goal:** the trust-thinking story is provable.

Tasks:
1. Verify `data/red_team.json` — already delivered as 10 cases across 9 categories per §0.7, including the multi-clause Agent 3 query verbatim. Extend only if a new failure mode appears during implementation.
2. Extend `bench/metrics.py` to score 4-state behavior match and refusal tone. Pass each case's `evaluation_notes` into the judge prompt as the rubric for that case.
3. **Refusal log:** every `refuse_with_redirect` / `ask_clarification` / `partial_answer_with_escalation` response from the bench writes `{question, retrieved_top_k, refusal_reason, behavior_matched, expected_behavior}` to `bench/refusal-log.jsonl`. Source material for `AI_JOURNAL.md` (what the system declined to answer + why) and for refusal-tone analysis.
4. Run the red-team through the bench. Commit results.
5. Start drafting `CREATIVE.md` — red-team harness as primary section, plus the three "path-not-taken at scale" mentions per §0.9 (per-service-category dual-source retriever, conversational mode, knowledge-graph cross-doc reasoning).

**Phase-4 done = red-team set runs through bench, results in `bench/results.md` second table, CREATIVE.md primary section drafted.**

### Phase 5 — Third frontier + Arabic-native provider

**Goal:** all five providers in the bench.

Tasks:
1. `providers/gemini.py` — implement against verified-current Gemini model ID.
2. `providers/falcon_arabic.py` — Ollama client. Document the `ollama pull` command in README. Try Falcon-Arabic 7B first; if too slow on local hardware, try Falcon-H1-Arabic 3B.
3. Re-run the bench. Update `bench/results.md`. The bench output should now have 5 rows.
4. **The bench result picks the production default.** Set it in `.env.example`.

**Phase-5 done = full 5-provider bench. Default provider chosen by data.**

### Phase 6 — Architecture doc

**Goal:** the architecture is *predictable* from the doc alone.

Tasks:
1. Draft `docs/ARCHITECTURE.md`:
   - System diagram (mermaid or ASCII).
   - Component contracts table (one row per module in `src/murshid/`).
   - **ADR 1 — Embedding choice:** BGE-M3 (MIT license, 1024-dim, 8192-token), cite Alsubhi 2025 (RAGAS 70.99) and MIRACL Arabic numbers. Note Swan-Small spike result. **Before ADR 1 ships:** spend 5 minutes confirming Alsubhi 2025 RAGAS 70.99 against arXiv 2506.06339 and MIRACL Arabic main_score 0.789 against its source. If either cannot be verified, weaken the claim in the verification-flag voice ("we could not independently verify X but it appears in [source]") rather than ship polished but unverified numbers.
   - **ADR 2 — LLM provider strategy:** the agnostic layer. Cite Agent 5's surrogates (ALRAGE/HELM/OALL with the ALLaM 0.7681 / Fanar 0.7701 / Command-R7B 0.7590 numbers; ABJADNLP 2025 GPT-4o F1 0.90 vs SILMA-9B 0.80; HalluScore frontier vs Arabic-native gap). Then present our mini-bench results as filling the grounded-QA-with-citations gap for our use case. Name the chosen default + reason. Verification flag: correctness/faithfulness rankings are based on 11 gold answers, so report them as directional with wide error bars, not statistically definitive.
   - **ADR 3 — Normalization tokenizer-alignment + register-detection allowlist:** the light-by-default normalization decision (preserve ى / ة / hamza; cite CAMeL Tools). Also document the §0.4 register-detection allowlist as **intentionally conservative** — plausible status tokens like `unpaid` and `rejected` are deliberately excluded so that genuine register escalation (`dialect` → `mixed`) still happens when non-allowlisted English appears. Revisit on observed failures, not preemptively. The data already exercises this: q-009 (`OTP`/`application`/`request` allowlisted) stays `dialect`; q-010 (`unpaid`) and q-011 (`rejected`) escalate to `mixed`.
   - **Arabic-specific risks section:** diglossia, code-switching, hallucinated policy, RTL bugs (note them even if we don't render RTL), register drift mid-response, citation translation.
   - **GCC production gaps paragraph:** PDPL (Saudi Royal Decree M/19, Sept 14 2024 enforced, SAR 5M fines, SDAIA Feb 2025 cross-border guideline), data residency (AWS Bedrock UAE Sept 29 2025, Bahrain Nov 19 2025; OpenAI UAE residency Nov 25 2025; ALLaM via watsonx KSA, Azure UAE), Arabic agent escalation (cite Air Canada Moffatt precedent for chatbot misrepresentation liability; describe the failure modes — register mismatch, authority hallucination, bad handoff summary).
   - **Predictive walkthrough:** include a full trace for the Khaleeji code-switched example query, showing the pipeline behavior step by step per the "reader can predict behavior without reading code" rubric line.

**Phase-6 done = ARCHITECTURE.md is self-contained and the reviewer can predict system behavior without reading code.**

### Phase 7 — AI journal curation

**Goal:** turn the raw `WORKING_LOG.md` into a graded `AI_JOURNAL.md`.

Tasks:
1. Read `WORKING_LOG.md`. Identify:
   - 3 prompts worth showing (decisional moments — agent proposed X, you accepted/rejected, with reason)
   - 1 Arabic-specific mistake you caught
   - 1 thing you let the agent do autonomously, with the guardrails
2. Draft `docs/AI_JOURNAL.md`. Use the verification-flag voice ("I checked X, could not verify Y"). Do not overclaim.
3. Honest reflection paragraph: where AI helped, where it hurt.

**Phase-7 done = AI_JOURNAL.md ships.**

### Phase 8 — README + Hijri/Arabic-Indic + final polish

**Goal:** the front door reads in 2 minutes; the secondary creative items land if time permits.

Tasks:
1. `README.md` — written last, from the real work that shipped:
   - One-sentence what.
   - One-command setup (`pip install -r requirements.txt; python scripts/demo.py "<question>"` or similar).
   - The 3 demo questions to try (one MSA, one dialect, one escalation), with example commands.
   - Architecture doc pointer.
   - Mini-bench pointer.
2. **If time permits:** Hijri-date module — detect Hijri date mentions, normalize for retrieval. Mention in `CREATIVE.md`.
3. **If time permits:** Arabic-Indic numeral normalization. Mention in `CREATIVE.md`.
4. `.env.example` final pass with the chosen default provider.

**Phase-8 done = the repo is submittable.**

### Phase 9 — Pre-submission

1. Smoke-test: clone the repo to a fresh directory, follow README, run the three demo questions, verify they work.
2. Run the bench one final time, commit results.
3. Write the 150-word submission note (proud-of, would-revisit, LLM provider). Place in repo root as `SUBMISSION_NOTE.md`.
4. Final commit. Submit.

---

## 4. WORKING_LOG.md — the format

Append-only. One block per logged moment. Format:

```markdown
## [HH:MM] <short label>

**Type:** prompt | decision | mistake_caught | autonomous_handoff | spike_result | misc

**What happened:**
<1-3 sentences, concrete and honest>

**Agent suggested:**
<verbatim or paraphrase of the agent's first move>

**I accepted / rejected / modified:**
<the call I made, in one sentence>

**Reason:**
<why, in one sentence>

---
```

Log every moment that might matter at the end. Over-log is fine. We curate at Phase 7.

**Things that MUST get logged:**
- The embedding spike result (Swan-Small vs BGE-M3 sanity check)
- Any moment the agent reached for aggressive normalization or English-default reasoning
- Any moment you had to push back on the agent's choice
- Any moment the agent did something well without prompting
- Any moment you let the agent run unsupervised and the guardrails you set
- Any moment you spotted an Arabic-specific subtlety (RTL, register, citation language)
- Any moment a verification check found something different from what was assumed

---

## 5. TIME_LOG.md — the format

```markdown
## YYYY-MM-DD

[HH:MM] Session start
[HH:MM] Phase 1 done — what shipped
[HH:MM] Phase 2 done — what shipped, what cut
[HH:MM] Session end — current state

Total session time: HH:MM
```

Update at every phase boundary and every session boundary. The user reads this to know what's been done.

---

## 6. Voice and tone for the docs

**Use the verification-flag voice.** When stating a fact, cite a source or flag the limitation. When uncertain, say so.

- ✅ "Alsubhi 2025 reports BGE-M3 mean RAGAS 70.99 across six Arabic datasets, beating multilingual-e5-large at 70.31 [link to arXiv 2506.06339]."
- ❌ "BGE-M3 is the strongest Arabic embedding model."

- ✅ "We could not find a clean public benchmark comparing closed frontier models against Arabic-native open models on grounded Arabic QA with citation accuracy. The closest surrogates are ALRAGE on HELM/OALL Arabic (RAG-like but no citation scoring) and ABJADNLP 2025 lexical RAG (citation-less, dictionary domain). We built our own mini-bench to fill this gap for our use case."
- ❌ "Our LLM choice is grounded in industry-standard benchmarks."

The voice change is itself part of the submission. **English-default engineers default to confident overclaiming. Verification-flagging signals Arabic-aware depth and engineering honesty.** This is non-negotiable for the four graded docs (README, ARCHITECTURE, AI_JOURNAL, CREATIVE).

---

## 7. Engineering rigor checklist

Before each commit:
- No API keys in code or committed files. `.env` is gitignored; `.env.example` ships with empty values.
- No stray debug `print()` in library code under `src/murshid/`. CLI scripts in `scripts/` may use `print()` for user-visible output; `scripts/demo.py` must additionally write the demo output to a UTF-8 `.txt` file (Windows PowerShell mangles RTL Arabic in stdout).
- No `TODO` without a corresponding line in `WORKING_LOG.md`.
- All HTTP/LLM calls have a timeout (default 30s) and a retry budget (default 2).
- All LLM calls log token usage to `bench/cost-log.jsonl` for cost auditing.
- All `refuse_with_redirect` / `ask_clarification` / `partial_answer_with_escalation` responses log `{question, retrieved_top_k, refusal_reason, behavior_matched}` to `bench/refusal-log.jsonl` for refusal-tone analysis and AI_JOURNAL.md material.
- All input that touches the LLM is length-capped (default 4000 chars for user input).
- `pytest tests/` passes.

Before submission:
- `git status` clean.
- `requirements.txt` pinned.
- README's one-command setup actually works from a fresh clone.
- `.env.example` has every key documented.
- `bench/results.md` reflects the latest run.

---

## 8. Cut order if time runs short

Priority order is the order things ship. Cut from the bottom of Phase N before starting Phase N+1's lower items. **Never cut from Phase 1.**

Cut order, top to bottom = first to drop:

1. Hijri-date module (Phase 8 item 2)
2. Arabic-Indic numeral normalization (Phase 8 item 3)
3. Falcon-Arabic provider (Phase 5 item 2 — mention in CREATIVE/ARCHITECTURE as the path-not-taken with reasoning)
4. Gemini provider (Phase 5 item 1)
5. Reranker (Phase 2)
6. Swan-Small spike (Phase 2 item 5 — only if it eats more than 15 minutes)
7. Refusal-tone scoring (Phase 4 item 2 sub-metric — keep boolean 4-state behavior match)
8. The third frontier provider in the bench, leaving Claude + OpenAI + Mock as the minimal viable bench

**Never cut:** Phase 1 entirely, Phase 2 register detection + multi-view retrieval, Phase 3 first bench run with at least two providers, Phase 4 red-team harness (data + at least the boolean 4-state behavior metric), Phase 6 ARCHITECTURE.md, Phase 7 AI_JOURNAL.md, Phase 8 README, Phase 9 smoke test + submission note.

**Cut providers are still documented in ADR 2 + CREATIVE.md as "explored-but-deferred":** Falcon-Arabic specifically as the residency-compliant KSA production path we'd ship in production but didn't bench due to local hardware. **Note:** Gemini is also the judge model. If the Gemini SDK is dropped entirely, swap the judge to `claude-opus-4-7` and flag the self-preference bias explicitly in ADR 2 ("we cannot quantify what we cannot run"). Better outcome under time pressure: keep the Gemini SDK shim + judge call live even when Gemini is not in the bench rotation — the bench-run cost is dominated by the providers under test, not by the judge.

---

## 9. What gets submitted

A private Git repo containing the structure in §2, plus:

- `SUBMISSION_NOTE.md` in the repo root with the ≤150-word submission note (proud-of, would-revisit, LLM provider).
- The repo URL emailed per the brief's instructions.

---

## Begin

Reply with §1 (Pre-flight) and stop. Do not start coding until I greenlight.

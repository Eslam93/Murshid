# Murshid

Arabic-first RAG over Saudi government-services FAQs. CLI demo with a 5-provider abstraction (Mock + Claude + OpenAI + Gemini live; Falcon-Arabic stub for the residency-aware production path), structured-output judge bench, red-team adversarial harness, and explicit trust-thinking instrumentation (refusal-tone scoring, critic refusal-cause breakdown, cross-judge sanity swap).

The artifact to read first is `bench/results.md` + the 3-question demo. The reader can predict system behavior from `docs/ARCHITECTURE.md` without reading code.

---

## Two-minute setup

```bash
# Python 3.11+ recommended. Editable install.
pip install -r requirements.txt
pip install -e .

# Optional: real-provider API keys. Copy and fill in.
cp .env.example .env
# Edit .env with ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY.
# Mock provider needs no keys.

# Tests — full verification (~70-110s end-to-end; first run downloads BGE-M3 ~2.3GB)
pytest tests/

# Fast path (~10s, no BGE-M3 download) — skips the 3 test files that
# build a real dense index (test_pipeline, test_support_gate, test_arabic_indic_digits).
# Useful when you want a quick sanity pass without the 2.3GB weight pull.
pytest --ignore=tests/test_pipeline.py --ignore=tests/test_support_gate.py --ignore=tests/test_arabic_indic_digits.py
```

The first full test run downloads BGE-M3 weights (~2.3GB) into the Hugging Face cache. Subsequent runs hit the cache.

## Run the 3-question demo

```bash
python scripts/demo.py
```

Runs three questions end-to-end with the Mock provider (zero API keys required):

1. **q-001** — MSA, iqama renewal. Expected: `answer`. Demonstrates the in-corpus answer path with verbatim MSA citations.
2. **q-007** — Khaleeji dialect, sponsorship transfer with Hijri date. Expected: `answer`. Demonstrates dialect→MSA query rewrite, Hijri date preservation, and same-register answer + verbatim MSA citation discipline.
3. **q-014** — Out-of-corpus personal loan question. Expected: `refuse_with_redirect`. Demonstrates the hard out-of-scope short-circuit before retrieval.

### Output

The demo writes the full trace to `demo_output.txt` (UTF-8) and prints only a brief status tail to stdout.

**Why a file, not stdout:** Windows PowerShell mangles RTL Arabic in stdout (cp1252 vs UTF-8). Open `demo_output.txt` in any editor that handles UTF-8 + RTL (VS Code, Notepad++) to see the rendered Arabic answer + citations correctly.

### Single-query mode

```bash
python scripts/demo.py "كيف أجدد إقامتي إذا كان جواز السفر سينتهي قريباً؟"
```

Accepts an ad-hoc query as the first positional argument. Same output contract (file + status tail).

## Run the bench

```bash
# Default: all providers, both critic modes, full standard + red-team set + sanity-swap
python -m murshid.bench

# Cost-controlled subsets
python -m murshid.bench --providers mock                       # zero-cost
python -m murshid.bench --providers mock,claude --critic off   # ~$0.10
python -m murshid.bench --mode red_team                        # red-team only + minimal pre-loop
python -m murshid.bench --question-ids q-001,q-007 \
    --red-team-ids rt-001,rt-002,rt-003 --no-sanity-swap       # focused

# Free re-render after a metric-logic tweak (uses bench/case-cache.json)
python -m murshid.bench --render-only
```

Outputs:

- `bench/results.md` — aggregate + per-case + critic refusal-cause breakdown + sanity-swap delta.
- `bench/cost-log.jsonl` — per-call token + cost trace (answer calls only; full call-graph tracing is deferred — see ADR 2).
- `bench/refusal-log.jsonl` — every non-answer behavior with expected vs taken + critic state.
- `bench/case-cache.json` — per-case results for free `--render-only` re-renders.

See `docs/ARCHITECTURE.md` §4 (ADR 2) for the bench results narrative and the production-default decision.

## Repository layout

```
.
├── README.md                       — this file
├── docs/
│   ├── ARCHITECTURE.md             — system diagram + ADRs 1/2/3 + Arabic risks + GCC gaps + predictive walkthrough
│   └── CREATIVE.md                 — red-team harness as headline; Hijri / Arabic-Indic add-ons; path-not-taken
├── data/
│   ├── sources.json                — 20 Arabic government-services FAQ documents
│   ├── questions.json              — 16 user questions, 4-state behavior vocabulary
│   ├── gold_answers.json           — 11 gold answers
│   └── red_team.json               — 10 adversarial cases, 9 categories
├── src/murshid/                    — pipeline + bench + providers
├── tests/                          — 202+ test cases
├── scripts/
│   ├── demo.py                     — 3-question demo
│   ├── verify_keys.py              — API-key smoke test for real providers
│   ├── debug_judge.py              — single-shot judge call debugging
│   └── seed_bench.py               — bench seeding helper
└── bench/
    ├── results.md                  — canonical bench output (see ARCHITECTURE §4 / ADR 2)
    ├── case-cache.json             — per-case results for --render-only re-renders
    ├── cost-log.jsonl
    ├── refusal-log.jsonl
    └── archive/                    — historical snapshots (Phase 3 + Gemini Pro Track A)
        ├── results-phase3-snapshot.md
        ├── results-gemini-pro-focused.md
        └── case-cache-gemini-pro.json
```

## Reading order

1. **This README** (~2 min) — orientation.
2. **`docs/ARCHITECTURE.md`** (~10 min) — system diagram, 3 ADRs, Arabic risks, GCC gaps, predictive walkthrough.
3. **`bench/results.md`** (~3 min) — the canonical evidence; read the banner at the top first.
4. **`docs/CREATIVE.md`** (~3 min) — red-team as headline; path-not-taken.
5. **`demo_output.txt`** (~2 min) — 3-question end-to-end demo output.

Total: ~20 minutes. The demo execution path (`python scripts/demo.py`) produces the .txt artifact in ~30 seconds with the Mock provider.

## What's NOT here

Honest scoping:

- **No web UI.** CLI only.
- **No multi-tenant auth, user accounts, or persistent state.** Single-process; in-memory indices.
- **No vector database.** BGE-M3 dense + BM25 sparse held in process memory; the ~20-document corpus fits comfortably.
- **No Hala-9B Arabic model.** CC-BY-NC license incompatible with commercial use.
- **Hijri date structured detection — SHIPPED** (`src/murshid/hijri.py`, 33 tests in `tests/test_hijri.py`). Canonicalizes month-name variants (`ربيع الأول`/`ربيع الاول`, `ذو القعدة`/`ذي القعدة`) and returns frozen `HijriDate` dataclasses with day/month/year/marker/raw_text. **Calendar arithmetic and Hijri↔Gregorian conversion are NOT built** — those would require a real Hijri-calendar library (`hijri-converter` or `umalqurra`) and dedicated bench evidence; named explicitly in `docs/CREATIVE.md` §7 as the next hook.
- **Arabic-Indic numeral normalization — SHIPPED at the retrieval layer** (`fold_arabic_indic_digits` in `src/murshid/normalize.py`, wired into `retrieve._bm25_normalize`, 31 tests in `tests/test_arabic_indic_digits.py`). A query in Arabic-Indic digits (`١٠ رمضان ١٤٤٧هـ`) now hits the Western-digit indexed corpus via the BM25 layer. NOT folded into `light_normalize` — the normalization spec stays frozen; the digit fold is an explicit composed pass at the retrieval call site.
- **No Falcon-Arabic provider runs in the bench.** Provider class is a stub. The residency-compliant KSA production path is documented in `docs/ARCHITECTURE.md` ADR 2 + GCC production gaps section, and `docs/CREATIVE.md` mentions the on-prem Ollama deployment story.
- **Pre-generation support gate — SHIPPED** (`pipeline._assess_specific_support`, 20 tests in `tests/test_support_gate.py`). Closes the rt-001 / rt-002 policy hallucination bait class deterministically before generation. Pattern + term-matching heuristic; the residual production hardening step (a judge-based support assessor for novel bait phrasings) is documented in ADR 2 but not built — would add a pre-generation LLM call per query, doubling bench cost.
- **No retry budget for judge / critic / rewrite calls beyond the provider-internal retries.** `retry_call` wraps SDK calls; bench-level retry loops were not built. See ADR 2.

Each cut item is documented where a reader would look for it.

## License

The code is open for evaluation; the FAQ data in `data/` is fabricated for this project and contains test annotations (e.g., `"لا تستخدم هذه القاعدة لأي تاريخ حقيقي خارج بيئة الاختبار"`) that real production data would not have. See `docs/ARCHITECTURE.md` §9 for the implication this has on the critic-on test artifact for q-007.

## The review process (something we're proud of)

This project was built through a deliberate **multi-round adversarial review pipeline**: three pre-Phase-1 reviewer rounds on the dataset and design contract, then Round 1 → Round 2 → Round 2 follow-up → Round 3 → Round 3 follow-up of external code review (Codex GPT-5 acting as the reviewer in each pass). A private adversarial Phase 3 pass between rounds caught the bench-evidence issues nobody else flagged.

Each round was driven by a **reviewer prompt template**, so any round can be re-run to get a fresh external read.

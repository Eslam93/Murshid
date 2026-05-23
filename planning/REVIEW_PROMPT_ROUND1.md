# Murshid — Round 1 Review Prompt (post Phase 1 + Phase 2)

> Paste this entire file into a fresh reviewer session. The reviewer should
> have repo access (or the relevant files pasted in). The expected output is
> a report titled `REVIEW_REPORT_ROUND1.md` matching the structure in §6
> below.

---

## 1. Context

**Project:** Murshid — Arabic-first RAG over Saudi government-services FAQs.
A take-home for Adree's Principal AI Engineer role. CLI demo; 20 source
documents; 16 questions; 11 gold answers; 10 red-team adversarial cases.

**Where things stand:**
- Phase 1 (foundations + first end-to-end with mock provider) shipped on 2026-05-22.
- Phase 2 (register detection + service-category router + multi-view hybrid retrieval + critic + 3-question demo) shipped on 2026-05-22.
- Phase 3 (real providers + first bench run) is **not yet started** — pending API keys. Out of scope for this review.

**What to expect from the codebase:**
- Mock-provider end-to-end works.
- BGE-M3 dense + BM25 hybrid retrieval with RRF fusion, service-category filter, and multi-view (raw / light-normalized / MSA-rewrite) is wired.
- 44/44 tests pass.
- Bench infrastructure (`src/murshid/bench/*`) is **stub-only** — implementations land in Phase 3.

---

## 2. Reviewer role

You are **Claude Opus 4.7 (1M context)** — or any reviewer of equivalent
depth — reviewing the codebase the way a senior staff engineer would on a
take-home submission for a Principal AI Engineer role. You are not the author.
You owe critique, not encouragement.

**Calibration:**
- Take the verification-flag voice the codebase prescribes (§6 of `MURSHID_KICKOFF.md`). When you state a fact about the code, cite the file:line. When you make a claim about external libraries or APIs, say what you verified vs. what you assumed.
- Be willing to disagree with the kickoff's design calls if you have evidence. The kickoff went through three reviewer rounds before code shipped, but it is not infallible.
- Calibrate severity by impact, not surface area. A subtle Arabic-handling bug ranks higher than a missing type hint.
- Push back where the working log overstates a fix or where the deliverables draft promises something the code doesn't actually deliver.

**What you are NOT being asked to do:**
- Test or score the bench. The bench isn't implemented yet (Phase 3).
- Run the demo end-to-end. The reviewer of round 1 may rely on `demo_output.txt` as the demo execution artifact.
- Recommend a different architecture wholesale. The kickoff is the contract; review the implementation against it.

---

## 3. Scope (read these files in this order)

### 3.1 Brief + authoritative spec
1. `Principal_AI_Engineer_Task.pdf` — the rubric and constraints we're building against.
2. `MURSHID_KICKOFF.md` — the locked design contract (§0 decisions, §2 layout, §3 phase plan, §6 voice, §7 rigor, §8 cut order).

### 3.2 Pre-Phase-1 planning artifacts
3. `planning/PLANNING_LOG.md` — chronological history of decisions, three reviewer rounds, four external RAG-architecture learnings, Eslam's accumulated pushbacks.
4. `planning/DELIVERABLES_DRAFT.md` — pre-staged content for the final docs (ADR 1/2/3 drafts, Arabic-risks paragraph, GCC-gaps paragraph, predictive walkthrough framework, CREATIVE.md outline, AI_JOURNAL.md raw material, SUBMISSION_NOTE.md framing).
5. `planning/PLAN_SUMMARY.md` — plain-English current plan.

### 3.3 Data files
6. `data/sources.json` (20 records), `data/questions.json` (16 records), `data/gold_answers.json` (11 records), `data/red_team.json` (10 records).

### 3.4 Phase 1 + Phase 2 source code
7. `src/murshid/normalize.py` — light Arabic normalization. Preserves ى/ة/hamza by default (§0.2).
8. `src/murshid/ingest.py` — deterministic chunker (FAQ detect by `س:` markers, else paragraph split), enrichment via provider, BGE-M3 embedding, in-memory index.
9. `src/murshid/retrieve.py` — multi-view + hybrid (BM25 + dense) + RRF fusion + service-category filter (Phase 2).
10. `src/murshid/register.py` — three-class register detector, 14-token domain allowlist, MSA-formal-marker + dialect-marker → `mixed` rule.
11. `src/murshid/router.py` — Arabic-keyword service-category classifier + out-of-scope override.
12. `src/murshid/rewrite.py` — dialect → MSA query rewriter (provider-backed).
13. `src/murshid/prompts.py` — canonical `SYSTEM_PROMPT_AR` + few-shot exemplars.
14. `src/murshid/critic.py` — register + groundedness post-check.
15. `src/murshid/pipeline.py` — full router → register → rewrite → retrieve → generate → critic flow.
16. `src/murshid/providers/base.py` — `LLMProvider` protocol + `ProviderResponse`.
17. `src/murshid/providers/mock.py` — canned responses for zero-key reviewer demo.
18. `src/murshid/providers/{claude,openai,gemini,falcon_arabic}.py` — Phase 3+ stubs.
19. `src/murshid/bench/{metrics,runner}.py` — Phase 3 stubs (not implemented yet).
20. `scripts/demo.py` — 3-question demo (MSA / Khaleeji / out-of-corpus).

### 3.5 Tests
21. `tests/test_normalization.py` (18 cases), `tests/test_ingest.py` (11), `tests/test_register.py` (6), `tests/test_router.py` (9). All 44 pass.

### 3.6 Demo + logs + config
22. `demo_output.txt` — the Phase 2 demo execution output (UTF-8, RTL Arabic).
23. `docs/WORKING_LOG.md` — append-only build log per §4 of the kickoff.
24. `docs/TIME_LOG.md` — session timeline.
25. `requirements.txt`, `.env.example`, `.gitignore`, `pyproject.toml`, `conftest.py`.

---

## 4. Approach

**Direct read.** Not just spot-check. Open every file you cite. The codebase is small (~1500 lines of real Python plus ~700 lines of tests); a thorough read is feasible in one pass.

**Verify claims against code.** When `MURSHID_KICKOFF.md` or `planning/PLANNING_LOG.md` claims a behavior, check the implementation. Examples of claims to verify:
- The §0.2 normalization preserves `ى`, `ة`, hamza by default → check `src/murshid/normalize.py` *and* `tests/test_normalization.py`.
- The §0.3 chunk metadata enrichment does NOT mutate `passage_text` → check `src/murshid/ingest.py:enrich_chunk_metadata`.
- The §0.3 retrieval applies the `service_category` filter BEFORE scoring → check `src/murshid/retrieve.py:retrieve`.
- The §0.4 allowlist is intentionally conservative (excludes `unpaid` / `rejected`) → check `src/murshid/register.py:DOMAIN_ALLOWLIST` + the `mixed` classification on q-010/q-011.
- The §0.6 metric 1 contract (content-based retrieval matching, not chunk-id-based) is honored → check `tests/test_ingest.py:test_passage_text_is_in_original_source` + the validation log entry in `docs/WORKING_LOG.md`.
- Phase 1 task 7's data-validation assertion ("every `gold_citations[].quoted_passage` appears verbatim in `sources.json`") → re-run the substring check on the JSON files, or read the working-log entry confirming it.
- The router test (`tests/test_router.py`) asserts every standard question routes to a category consistent with its `expected_source_ids` → spot-check 2-3 hard cases (q-009 with OTP + "توثيق العقد" → labor_office; q-014 with "قرض" → out_of_scope; rt-003 with "بدل فاقد للهوية" → iqama [hawiya/iqama trap, intentional]).

**Look for regressions from the kickoff's design calls.** Specifically:
- Does the chunker's `passage_text` actually stay verbatim, end-to-end through enrichment + embedding?
- Does the BM25 index match dense-index alignment on chunk order (so RRF fusion works on consistent indices)?
- Does the pipeline's `out_of_scope` short-circuit correctly skip retrieval (i.e., no embedding cost on refusals)?
- Does the demo's stdout-vs-file split actually keep RTL Arabic out of stdout?

**Hunt for things the planning didn't anticipate.** This is the highest-value part of round 1 — what did the planning miss? Examples to consider:
- Are there gold-answer cases where the chunker's output makes the cited `quoted_passage` un-retrievable (e.g., chunk boundary splits the cited sentence)?
- Does the multi-view retrieval double-count when raw and light-normalized produce identical strings?
- Is the `MSA_FORMAL_MARKERS` set in `register.py` consistent with how MSA appears in the data, or does it over-trigger on common formal vocabulary?
- Does the `OUT_OF_SCOPE_TRIGGERS` set in `router.py` correctly handle subtle cases (e.g., a question about religious-rite scheduling that doesn't use the literal phrase `الشعائر الدينية`)?

**Calibrate against the rubric.** The brief grades in this order: (1) Arabic technical depth, (2) vibe-coding fluency, (3) architecture & docs, (4) trust thinking, (5) creativity, (6) engineering rigor. Weight your findings accordingly.

---

## 5. Severity bar

Use the same color scheme as the reference report:

| Severity | Meaning | Example |
| --- | --- | --- |
| 🔴 CRITICAL | Breaks the demo, mishandles Arabic in a way a reviewer will spot, or leaks data | Pipeline crashes on Khaleeji input; chunker mutates `passage_text` invalidating citation matching |
| 🟠 HIGH | Real bug or significant design gap; needs a fix before submission | Router misclassifies a question class; allowlist over-triggers `mixed` |
| 🟡 MEDIUM | Quality concern; should fix but not blocking | Working-log entry overstates a fix; test coverage gap; minor docstring inaccuracy |
| 🟢 GOOD | Worth calling out as a deliberate strength | Conservative allowlist is the right design call and the data exercises it; deterministic chunker; etc. |

**Expected distribution for round 1:** 0–1 CRITICAL, 2–5 HIGH, 5–10 MEDIUM,
several GOOD. If your distribution is dramatically skewed in either direction
(all-CRITICAL or all-GOOD), reconsider whether you're calibrating right.

---

## 6. Required output structure

Produce a single Markdown document titled `REVIEW_REPORT_ROUND1.md`. Use this
exact section structure, adapted from the reference report:

```markdown
# Murshid — Round 1 Review (post Phase 1 + Phase 2)

> Reviewer: <your model + identifier>
> Review date: <yyyy-mm-dd>
> Reviewed: Phase 1 (commit / state) + Phase 2 (commit / state)
> Approach: <1-3 sentences on how you reviewed — direct read of every file, etc>

## 1. Overall impression

<2-4 paragraphs. What landed cleanly, what didn't, the net verdict.>

## 2. Critical findings

<For each finding above MEDIUM, a numbered subsection 2.1, 2.2, ... with:>
### 2.X 🔴|🟠|🟡 SEVERITY — <one-line title>

**Files:** [path/to/file.py:line](path/to/file.py:line)

<Diagnosis: 2-4 paragraphs explaining the issue, the failure mode, and concrete evidence.>

**Why <severity> not <one above/below>:** <one sentence>

**Fix:**
```python
# concrete patch
```

## 3. Per-area findings

### 3.1 Arabic technical depth
<🟠 HIGH / 🟡 MEDIUM / 🟢 GOOD subsections>
- Bullets covering normalization, register, router, allowlist, dialect handling, Hijri date treatment, code-switching handling, citation translation rule (rt-010 trap).

### 3.2 Retrieval
- Multi-view fusion correctness, BM25/dense alignment, RRF constant choice, service-category filter behavior, chunk-id-vs-content-based matching consistency.

### 3.3 Pipeline + behavior taxonomy
- 4-state expected_behavior coverage, short-circuit correctness, critic integration, refusal/clarification templates.

### 3.4 Architecture & code quality
- Module cohesion, dataclass shapes, error handling, async patterns (or absence), Phase-1-vs-Phase-2 backwards compatibility, import graph.

### 3.5 Tests
- Coverage of the §0.2 / §0.3 / §0.4 design calls; what's pinned vs. left untested; whether tests verify behavior or just shape.

### 3.6 Engineering rigor (§7 of the kickoff)
- Deterministic chunking guarantee, citation contract enforcement, secrets handling (`.env.example` honesty), `print()` rule compliance, timeout/retry policies (not yet exercised — note as Phase 3 deferred).

### 3.7 Documentation
- Kickoff internal coherence (does the spec contradict itself anywhere?), working-log honesty (claims vs. code), deliverables-draft completeness, planning-log accuracy.

## 4. What the planning didn't anticipate

<Round 1 specific section — what surfaced in the read that the three pre-Phase-1 reviewer rounds missed?>

## 5. Severity assessment

<A table mapping every finding to its severity. Format like the reference report's §6.>

## 6. What to do next

### Before Phase 3 (must do)
<numbered list with time estimates>

### Before submission (should do)
<numbered list with time estimates>

### Defer (acknowledged trade-offs)
<bullet list with reasoning>

## Appendix — severity counts

| Severity | Count |
| --- | --- |
| 🔴 CRITICAL | X |
| 🟠 HIGH | X |
| 🟡 MEDIUM | X |
| 🟢 GOOD | X |
```

---

## 7. Style and tone

- **Cite file:line.** Every finding names a concrete location.
- **Quote, don't paraphrase.** When you reference a §0.X decision or a data field, copy the exact text.
- **Show diffs.** Fixes are presented as code patches, not prose suggestions.
- **No sycophancy.** Don't open with "great work overall." If the work is good, the GOOD bullets in §3 carry that weight without a preamble.
- **No padding.** Each paragraph in the report should earn its place. Aim for the reference report's density, not its length.
- **Verification-flag voice.** When you state a fact about an external library, say what you verified vs. assumed. If you're not sure whether `rank_bm25.BM25Okapi.get_scores` returns a numpy array or a Python list, say "I'm assuming a numpy array based on the wrapper; if it's a list the slice indexing in `retrieve.py:140` would error" rather than asserting one or the other.
- **Adversarial reading.** Look for places where the implementation is *almost* right but subtly wrong in a way a careful reviewer would catch. That's where the Arabic-depth grade is won or lost.

---

## 8. Specific things to check (non-exhaustive — your own findings are welcome)

A starter list. The reviewer should add their own — the planning history flagged these, and a competent reviewer would surface several more. Do NOT just walk this list and stop.

1. **`light_normalize` stripping tatweel inside `هـ`** (the Hijri marker). The test acknowledges this; verify nothing else in the corpus depends on `هـ` containing the tatweel.
2. **`enrich_chunk_metadata` is `try / except Exception`** — does it correctly degrade when the provider errors mid-batch (e.g., partial enrichment), or does it silently drop most chunks' metadata?
3. **`build_embedding_input` concatenation order** — passage + summary + keywords. Does the summary text ever leak fragments of `passage_text` that change the BM25 score in a misleading way?
4. **`retrieve()` filtering BEFORE scoring** — confirm the dense-index slice + BM25 score lookup are both correctly reindexed when `service_category` filters out chunks. The math is non-trivial when `candidate_indices` is a non-contiguous slice.
5. **RRF constant K=60** — kickoff doesn't specify; verify this is industry-standard or document the choice.
6. **`router.py:OUT_OF_SCOPE_TRIGGERS` includes `صدر` (chest)** — could this misfire on `صدر القرار` (the decision was issued)? Check whether substring matching is robust here.
7. **`register.py:MSA_FORMAL_MARKERS` includes `أود` and `أرغب`** — could a dialect speaker use these idiomatically, breaking the "MSA formal + dialect = mixed" rule? Check the rationale entries on q-012 / q-013 against this.
8. **`pipeline.py:answer_question`** — when `expected_behavior` is `partial_answer_with_escalation` (q-005, rt-003), does the pipeline produce that behavior, or does it always fall back to plain `answer`? The pipeline currently only emits `answer` / `refuse_with_redirect` / `ask_clarification`; partial-escalation is implicit. Is this acceptable?
9. **`critic.py` falls back to default-pass on JSON-decode error.** Is that the right failure mode? Should a malformed critic response escalate instead?
10. **`MockProvider._respond` substring sniffing** for routing is brittle — what happens if Phase 3 changes one of the role prompts' wording?
11. **The Phase 2 demo's q-007 retrieval** placed `sponsorship-003:chunk-2` at #1 and `chunk-1` at #2 — confirm against the gold (`sponsorship-003:chunk-1` and `chunk-2` per `gold_answers.json`). Is the order reversal a concern?
12. **The chunker outputs 84 chunks for 20 sources** — average 4.2. Are any chunks suspiciously long (over the 8192-token BGE-M3 limit when concatenated with enrichment metadata)?
13. **Eslam's pushbacks captured in `planning/PLANNING_LOG.md` §10** — is the code consistent with all 13 of them? Specifically: "no parallel truth sources" (is `should_escalate` truly removed from runtime decisions?), "stylistic consistency" (does the q-016 gold answer style match q-001 as planned?), etc.

---

## 9. Output filename

`REVIEW_REPORT_ROUND1.md`. Place at the repo root or at `.private/REVIEW_REPORT_ROUND1.md` per your convention.

---

## 10. Acknowledgments

The reference structure (§6) is adapted from `MagnaCMS .private/REVIEW_REPORT_ROUND2.md` — same severity scheme, same per-area structure, same "honest reckoning on rejected findings" sectioning (which is N/A for round 1 but should appear in round 2 if there is one).

Murshid has gone through three pre-Phase-1 reviewer rounds on the dataset and design contract; that history lives in `planning/PLANNING_LOG.md` §§6–8. The round 1 review now in your hands is the FIRST review of the SHIPPED CODE — the prior rounds didn't see implementation.

Be useful. Push back.

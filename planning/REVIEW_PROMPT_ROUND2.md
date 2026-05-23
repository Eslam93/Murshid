# Murshid — Round 2 Review Prompt (post Phases 1, 2, 3, 4)

> Paste this entire file into a fresh reviewer session. The reviewer should
> have repo access (or the relevant files pasted in). The expected output is
> a report titled `REVIEW_REPORT_ROUND2.md` matching the structure in §6
> below.
>
> **Note on cleaned-up references:** This template was calibrated for the
> Murshid build state at the time of Round 2. References inside to
> `REVIEW_REPORT_ROUND1.md`, `REVIEW_NOTES_PHASE3.md`, and
> `docs/TIME_LOG.md` point at files that lived during the build but were
> deleted as part of submission cleanup (the reports as ephemera; TIME_LOG
> for privacy — see the note at the top of `docs/WORKING_LOG.md`). The
> review-pipeline context is summarized in `docs/AI_JOURNAL.md` §
> "The multi-round review pipeline" — read that section first for the
> prior-history context the prompt expects.

---

## 1. Context

**Project:** Murshid — Arabic-first RAG over Saudi government-services FAQs.
A take-home for Adree's Principal AI Engineer role. CLI demo; 20 source
documents; 16 questions; 11 gold answers; 10 red-team adversarial cases.

**Where things stand (Round 2 is the FIRST review of post-Phase-3 work):**

- **Phase 1** (foundations + mock end-to-end with BGE-M3 dense retrieval) shipped 2026-05-22.
- **Phase 2** (register detection + service-category router + multi-view hybrid retrieval + critic + 3-question mock demo) shipped 2026-05-22.
- **Phase 3** (real provider SDKs: Claude `claude-sonnet-4-6`, OpenAI `gpt-5.5-2026-04-23`, Gemini judge; structured-output judge with `matched_facts`/`missing_facts`/`irrelevant_facts` plus `correctness_score`/`register_match_score`; critic-on/off dual-pass bench; 7 metrics; sanity-swap with `claude-opus-4-7`; Phase 6 hardening folded in — Arabic-Indic numeral detection, router synonyms + weighted scoring, Egyptian + Levantine dialect markers) shipped 2026-05-22.
- **Phase 4** (red-team scoring against `data/red_team.json` with a per-case rubric judge consuming `evaluation_notes` verbatim; refusal-tone metric judge-scored 0-3 on all non-answer behaviors; sanity-swap fixture polish that now stores `predicted_answer_text` and re-scores the SAME prediction across two judges; retry policy on provider calls; render-only mode + bench case cache; `CREATIVE.md` one-page draft) shipped 2026-05-23.

**Prior reviews already on file:**

- `REVIEW_REPORT_ROUND1.md` — Codex GPT-5 review of Phases 1+2. 5 HIGH + 13 MEDIUM + 8 GOOD. All HIGHs and MEDIUMs were resolved before Phase 3 began; see `docs/WORKING_LOG.md` entries for `[14:30]`–`[15:50]` and the Round 1 commit-equivalent fixes in `src/murshid/{router,critic,pipeline,retrieve,ingest,providers/mock}.py`.
- `REVIEW_NOTES_PHASE3.md` — private adversarial read of Phase 3 by a different reviewer. 6 findings: (1) sanity swap was gold-vs-gold, (2) cost column was answer-call only, (3) critic-on mixed harness fragility with real groundedness catches, (4) judge model drift between code and docs, (5) recall/citation deflated by non-answer cases, (6) no provider retry policy. **All 6 were folded into Phase 4 work**: #1 became the sanity-swap fixture polish; #2-#6 became "reviewer fixes" #2-#6 plus a new #13 (render-only mode + case cache for free re-renders of new aggregate logic). Worth verifying that these fixes actually deliver on what they claim.

**What to expect from the codebase:**

- 112/112 tests pass (`pytest tests/ -q`).
- Bench is real and has produced `bench/results.md` with Claude + OpenAI + Mock numbers + a fixed sanity-swap.
- **Render-format caveat:** the in-flight Phase 4 red-team-only run rendered with the code that was loaded at process start, so its AGGREGATE display is in Phase 3 format (Cost label, missing critic breakdown, Red-team `Recall@expected` shows "—"). A banner at the top of `bench/results.md` calls this out honestly. Per-case data is in the new format. Phase 3 standard tables are preserved verbatim in `bench/results-phase3-snapshot.md`.
- All 5 providers from kickoff §0.5 are implemented; the bench currently runs Mock + Claude + OpenAI. Gemini doubles as the judge (`gemini-2.5-flash` actual; `gemini-3.1-pro-preview` was the primary plan that hit thinking-budget + 250/day-quota issues during the first bench run — documented as a measured fallback). Falcon-Arabic via Ollama is a Phase-5 item, not yet wired.

**What is NOT in scope for Round 2:**

- The docs phases (`docs/ARCHITECTURE.md`, ADR 1/2/3 final write-ups, `docs/AI_JOURNAL.md`, `README.md`) — content is staged in `planning/DELIVERABLES_DRAFT.md` but the polished documents have not shipped. The reviewer MAY note where the staged content drifts from the code, but should not score "did ADR 2 ship correctly" because ADR 2 is not in `docs/` yet.
- `docs/CREATIVE.md` (one-page draft) IS in scope — landed in Phase 4. It is the only graded doc that has shipped.
- The Falcon-Arabic provider class (stub). Phase 5 work; mention only if architecturally relevant.

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
- Push back where the working log overstates a fix or where claimed reviewer-fix work doesn't actually deliver in code.
- **Specifically check that Phase 4 reviewer fixes from `REVIEW_NOTES_PHASE3.md` actually landed as claimed.** Each one has a "before / after" you can verify: e.g., fix #5 says recall now excludes non-answer cases — confirm by reading `aggregate()` and the new predicate. Fix #6 says retry handles transient errors — confirm class-name matching covers Anthropic/OpenAI/Google.

**What you are NOT being asked to do:**
- Score the docs that haven't shipped (ARCHITECTURE, AI_JOURNAL, README).
- Run the bench. The artifact is `bench/results.md` + `bench/results-phase3-snapshot.md` + `bench/cost-log.jsonl` + `bench/refusal-log.jsonl`.
- Recommend a different architecture wholesale. The kickoff is the contract; review the implementation against it.

---

## 3. Scope (read these files in this order)

### 3.1 Brief + authoritative spec
1. `Principal_AI_Engineer_Task.pdf` — the rubric and constraints we're building against.
2. `MURSHID_KICKOFF.md` — the locked design contract (§0 decisions, §2 layout, §3 phase plan, §6 voice, §7 rigor, §8 cut order). Note: §0.5 / §0.6 reference `gemini-3.1-pro-preview` as the primary planned judge with a paragraph explaining `gemini-2.5-flash` was the measured fallback.

### 3.2 Pre-Phase-1 planning artifacts
3. `planning/PLANNING_LOG.md` — chronological history of decisions, three reviewer rounds, four external RAG-architecture learnings, Eslam's accumulated pushbacks. **§13 contains 6 retroactively-logged planning-phase moments marked as such** — those are explicitly NOT real-time entries and the verification-flag voice should preserve that distinction.
4. `planning/DELIVERABLES_DRAFT.md` — pre-staged content for the final docs (ADR 1/2/3 drafts, Arabic-risks paragraph, GCC-gaps paragraph, predictive walkthrough framework, CREATIVE.md outline, AI_JOURNAL.md raw material, SUBMISSION_NOTE.md framing). Updated in Phase 4 with the actual-vs-planned judge model paragraph.
5. `planning/PLAN_SUMMARY.md` — plain-English current plan.

### 3.3 Prior review record
6. `planning/REVIEW_PROMPT_ROUND1.md` — Round 1 reviewer prompt template.
7. `REVIEW_REPORT_ROUND1.md` — Codex GPT-5 output for Phases 1+2. Cross-check that the HIGH-severity items are addressed in the current code, not just in the working log.
8. `REVIEW_NOTES_PHASE3.md` — private adversarial read of Phase 3. The 6 findings drove the Phase 4 reviewer-fix batch; verify each one actually delivered.

### 3.4 Data files
9. `data/sources.json` (20 records), `data/questions.json` (16 records), `data/gold_answers.json` (11 records), `data/red_team.json` (10 records).

### 3.5 Phase 1-4 source code
10. `src/murshid/normalize.py` — light Arabic normalization. Preserves ى/ة/hamza by default (§0.2).
11. `src/murshid/ingest.py` — deterministic chunker (FAQ detect by `س:` markers, else paragraph split), enrichment via provider with `Chunk.enrichment_status` field, BGE-M3 embedding, in-memory index.
12. `src/murshid/retrieve.py` — multi-view + hybrid (BM25 + dense) + RRF fusion (K=60 per Cormack et al. 2009) + service-category filter.
13. `src/murshid/register.py` — three-class register detector, 14-token domain allowlist, MSA-formal-marker + dialect-marker → `mixed` rule, **Phase 6 hardening adds Egyptian and Levantine dialect-marker families**.
14. `src/murshid/router.py` — Arabic-keyword service-category classifier with `_weighted_keyword_score` (Phase 6 hardening: multi-word keywords outweigh single-word so `تصريح العمل` beats bare `تصريح`), `MEDICAL_PATTERNS` bigram regex (`صدر` polysemy fix from Round 1), hard/soft OOS confidence distinction, synonym expansion (`غرامة` ↔ `مخالفة`, `بطاقة الإقامة` / `كرت الإقامة` ↔ `إقامة`, `إذن العمل` ↔ `رخصة عمل`).
15. `src/murshid/rewrite.py` — dialect → MSA query rewriter with `[ROLE: rewrite]` sentinel.
16. `src/murshid/prompts.py` — canonical `SYSTEM_PROMPT_AR` + few-shot exemplars.
17. `src/murshid/critic.py` — register + groundedness post-check. **Phase 3+ critic uses `_extract_json` to handle markdown-wrapped responses** (the first-bench-run debugging chain). `CriticResult.valid` distinguishes critic-itself-errored from real verdicts.
18. `src/murshid/pipeline.py` — full router → register → rewrite → retrieve → generate → critic flow with Option B gate (`grounded=false` → refuse, `register_match=false` only → log+return). `_has_ambiguous_date` catches both Western and Arabic-Indic short numeric dates (Phase 6 hardening). `_needs_partial_escalation` catches q-005 / rt-003 travel hints. `INPUT_LENGTH_CAP=4000`.
19. `src/murshid/providers/base.py` — `LLMProvider` Protocol + `ProviderResponse`. **Phase 4 reviewer fix #6 adds `retry_call(fn, *args, max_retries=2, backoff_base=1.0)`** with class-name-matched transient-error detection.
20. `src/murshid/providers/mock.py` — canned responses for zero-key reviewer demo. Sentinel-routed via `[ROLE: ...]` markers.
21. `src/murshid/providers/claude.py` — real `anthropic` SDK, default `claude-sonnet-4-6`, alternate `claude-opus-4-7` (held for sanity swap). Wraps SDK call in `retry_call`.
22. `src/murshid/providers/openai.py` — real `openai` SDK, default `gpt-5.5-2026-04-23`. **Uses `max_completion_tokens` not `max_tokens`** (GPT-5.x API requirement). Wraps SDK call in `retry_call`.
23. `src/murshid/providers/gemini.py` — real `google-generativeai` SDK, default `gemini-3.1-pro-preview` for the provider role, also serves as judge but bench actually uses `gemini-2.5-flash` per the documented fallback rationale. Wraps SDK call in `retry_call`.
24. `src/murshid/providers/falcon_arabic.py` — Phase 5 stub.
25. `src/murshid/bench/metrics.py` — 7 metrics, structured judges, `evaluate_case` + `evaluate_red_team_case`, `aggregate`, `dump_cases`/`load_cases` (Phase 4 reviewer fix #13), `_retrieval_was_expected` predicate (Phase 4 reviewer fix #5).
26. `src/murshid/bench/runner.py` — full bench loops with `--mode {full,red_team,standard}` and `--render-only`, snapshot-on-red-team-mode, sanity-swap with stored predictions.

### 3.6 Tests
27. `tests/test_normalization.py` (18), `tests/test_ingest.py` (11), `tests/test_register.py` (6), `tests/test_router.py` (16 — 9 baseline + 5 `صدر` polysemy + 2 hard/soft OOS), `tests/test_pipeline.py` (21 — 12 behavior contract + 6 critic gate + 3 Phase 6 hardening), `tests/test_bench_metrics.py` (26 — 13 Phase 4 initial + 5 fix #5 + 5 fix #3 + 3 fix #13 round-trip), `tests/test_provider_retry.py` (9 — Phase 4 fix #6 retry contract). **Total: 112/112 passing.**

### 3.7 Demo + bench artifacts
28. `demo_output.txt` — the Phase 2 demo execution output (UTF-8, RTL Arabic). Predates Phase 3+ but the rendering contract is unchanged.
29. `bench/results.md` — current bench output. **Read the banner at the top of the file** explaining the render-format gap. Per-case data is correct; aggregate display is in Phase 3 format.
30. `bench/results-phase3-snapshot.md` — Phase 3 standard tables preserved verbatim.
31. `bench/cost-log.jsonl` — per-call token/cost log (entries from the Phase 4 red-team-only run; Phase 3 entries are in the snapshot context).
32. `bench/refusal-log.jsonl` — per-refusal trace including `critic_grounded`, `critic_valid`, `critic_issues`, retrieved top-k, `service_category`, `routing_confidence`.

### 3.8 Documentation + config
33. `docs/CREATIVE.md` — Phase 4 deliverable, one page, verification-flag voice. Headline: red-team harness; build-if-time-permits: Hijri + Arabic-Indic; path-not-taken: per-service dual retriever, conversational mode, knowledge-graph reasoning.
34. `docs/WORKING_LOG.md` — append-only build log per kickoff §4. Latest entries cover Phase 4 sanity-swap polish, refusal-tone metric, red-team scoring, REVIEW_NOTES_PHASE3 acknowledgment, and the reviewer-fix batch (#2-#6 + #13).
35. `docs/TIME_LOG.md` — session timeline. Latest entry is the Phase 4 close-out at `[20:42]`.
36. `requirements.txt`, `.env.example` (updated with judge-model-fallback rationale), `.gitignore`, `pyproject.toml`, `conftest.py`.

---

## 4. Approach

**Direct read.** Not just spot-check. Open every file you cite. The codebase has grown to ~2400 lines of real Python plus ~1300 lines of tests; a thorough read is still feasible in one pass.

**Verify Phase 4 reviewer-fix claims against code.** Each fix has a "before / after" claim worth verifying:

- **Fix #1 (sanity-swap polish):** `bench/runner.py:run_judge_sanity_swap` should pull a stored `predicted_answer_text` from `CaseResult`, NOT score gold-vs-gold. `_pick_swap_candidate` walks `SANITY_SWAP_PROVIDER_PREFERENCE = ["openai", "claude", "gemini", "mock"]` at `critic="off"`. Confirm the swap output in `bench/results.md` shows real Δ correctness on real predictions for q-007 and q-013. (q-001 was skipped in the current run; check `_pick_swap_candidate` logic to see why — likely the openai pre-loop case lacked a primary `correctness_score`.)
- **Fix #2 (cost rename):** `bench/runner.py:render_results_md` should label the column "Answer cost (USD)" with a footnote explaining what's not included. The current `bench/results.md` predates this change (banner explains) but the code is in place — verify the renderer string itself.
- **Fix #3 (critic refusal-cause breakdown):** `bench/metrics.py:aggregate` should compute `n_critic_invalid_refuses`, `n_grounded_false_refuses`, `n_register_only_logs`. Verify the boolean logic on each counter (e.g., is `n_register_only_logs` correctly gated on `behavior_taken == "answer"` per Option B?). Then trace: a `refuse_with_redirect` case from a hard OOS path should NOT match either critic-bucket because the pipeline short-circuits before the critic runs (leaving sentinel values).
- **Fix #4 (docs sync on judge model):** `MURSHID_KICKOFF.md` §0.5 + §0.6, `.env.example`, `planning/DELIVERABLES_DRAFT.md` ADR 2 should all name `gemini-2.5-flash` as the actual judge with the thinking-budget + 250/day-quota rationale. `gemini-3.1-pro-preview` remains as primary planned for narrative coherence.
- **Fix #5 (non-answer recall exclusion):** `bench/metrics.py:_retrieval_was_expected` should return False for `ask_clarification` / `refuse_with_redirect` AND should include red-team cases when `expected_source_ids` is non-empty. Hand-compute red-team Recall@expected from the per-case data in `bench/results.md` (rows where expected_behavior is `answer` or `partial_answer_with_escalation` AND expected_source_ids is non-empty) and verify the predicate covers them.
- **Fix #6 (retry policy):** `src/murshid/providers/base.py:retry_call` matches class names via `type(exc).__mro__`. Verify `_TRANSIENT_ERROR_NAMES` covers Anthropic / OpenAI / Google class names accurately. Check `claude.py`, `openai.py`, `gemini.py` each wrap their SDK call with `retry_call`. Spot-check that `BadRequestError` / `AuthenticationError` are NOT retried.
- **Fix #13 (render-only + cache):** `bench/metrics.py:dump_cases` + `load_cases` should round-trip every aggregate-relevant field. The `--render-only` flag should produce a valid `bench/results.md` from `bench/case-cache.json` with zero LLM calls. Verify the test `test_aggregate_round_trip_preserves_metric_logic` actually pins recall/citation aggregates surviving the round-trip.

**Verify Round 1 fixes haven't regressed.** Each Round 1 HIGH had a specific code change:
- `صدر` polysemy → `_has_oos_trigger` + `MEDICAL_PATTERNS` regex bigram. Test: `tests/test_router.py` has 5 negative tests; verify they still pass.
- 4-state behavior contract → `_has_ambiguous_date` + `_needs_partial_escalation` in `pipeline.py`. Test: `tests/test_pipeline.py` pins q-004, q-005, rt-003, rt-007.
- Critic default-fail → `CriticResult.valid` field in `critic.py`. Test: `_CriticOverrideProvider` cases in `test_pipeline.py`.
- Enrichment exception breadth → `Chunk.enrichment_status` field. Test: `tests/test_ingest.py`.
- Pipeline-level behavior tests → 12 cases in `test_pipeline.py`. Verify they still cover the 4-state vocabulary.

**Verify Phase 6 hardening landed (folded into Phase 3 work):**
- Router weighted scoring: `_weighted_keyword_score`. Test: `tests/test_router.py` should pin the `تصريح العمل` → `labor_office` (not `municipal_permits`) routing.
- Egyptian/Levantine markers: `register.py` `EGYPTIAN_MARKERS` / `LEVANTINE_MARKERS`. Test: `tests/test_register.py` (Phase 6 hardening cases).
- Arabic-Indic ambiguous date: `pipeline.py:_SHORT_NUMERIC_DATE_ARABIC` regex. Test: `tests/test_pipeline.py` Phase 6 tests.

**Look for things the planning + Phase 3 + Phase 4 reviewer notes didn't anticipate.** This is the highest-value part of Round 2 — what's still broken or subtly wrong? Examples to consider:

- Does the `--render-only` mode handle the `mode` field correctly when re-rendering a cache that has both standard and red-team cases (`mode="full"`) vs cache from a red-team-only run (`mode="red_team"` inferred)?
- Does the sanity-swap `_pick_swap_candidate` handle the case where all preferred providers have correctness=None for that question? The q-001 skip in the current bench output suggests a real edge case worth understanding.
- Does the refusal-tone metric fire on EXPECTED refusals (e.g., q-014 hard-OOS refuse) AND on UNEXPECTED refusals (e.g., critic-on Claude refusing q-007 which expected `answer`)? Both should fire under the current "any non-answer" rule.
- The Phase 4 `evaluate_red_team_case` calls `judge_refusal_tone` for non-answer behaviors. Does it also handle the case where the judge errors and `refusal_tone_score` stays None? Check aggregate logic against missing scores.
- The new `_TRANSIENT_ERROR_NAMES` allowlist has `APIError` in it. That's the BASE class for many Anthropic/OpenAI exceptions including non-transient ones. Is the MRO walk safe here, or does it over-retry on `BadRequestError`?

**Calibrate against the rubric.** The brief grades in this order: (1) Arabic technical depth, (2) vibe-coding fluency, (3) architecture & docs, (4) trust thinking, (5) creativity, (6) engineering rigor. Weight your findings accordingly. The trust-thinking grade specifically depends on the sanity-swap, critic refusal-cause breakdown, and refusal-tone metric being correct — these are the load-bearing pieces of the Phase 4 work.

---

## 5. Severity bar

Use the same color scheme as the reference report and Round 1:

| Severity | Meaning | Example |
| --- | --- | --- |
| 🔴 CRITICAL | Breaks the demo, mishandles Arabic in a way a reviewer will spot, or leaks data | Sanity swap still scores gold-vs-gold despite Phase 4 claim |
| 🟠 HIGH | Real bug or significant design gap; needs a fix before submission | `_retrieval_was_expected` predicate misses a category; retry helper over-retries on non-transient errors |
| 🟡 MEDIUM | Quality concern; should fix but not blocking | Working-log entry overstates a fix; minor docstring inaccuracy; test coverage gap |
| 🟢 GOOD | Worth calling out as a deliberate strength | Conservative allowlist is the right design call; render-only mode is leverage; sanity-swap polish closes the Round-1 gap cleanly |

**Expected distribution for round 2:** 0–1 CRITICAL, 1–3 HIGH (lower than
round 1 because two prior review passes filtered findings), 5–10 MEDIUM,
several GOOD. If your distribution is dramatically skewed in either direction
(all-CRITICAL or all-GOOD), reconsider whether you're calibrating right.

---

## 6. Required output structure

Produce a single Markdown document titled `REVIEW_REPORT_ROUND2.md`. Use this
exact section structure:

```markdown
# Murshid — Round 2 Review (post Phases 1, 2, 3, 4)

> Reviewer: <your model + identifier>
> Review date: <yyyy-mm-dd>
> Reviewed: Phase 1 (state) + Phase 2 (state) + Phase 3 (state) + Phase 4 (state)
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
- Bullets covering normalization, register (now with Egyptian/Levantine markers), router weighted scoring + synonyms, allowlist, dialect handling, Hijri date treatment, code-switching handling, citation translation rule (rt-010 trap).

### 3.2 Retrieval
- Multi-view fusion correctness, BM25/dense alignment, RRF constant choice, service-category filter behavior, chunk-id-vs-content-based matching consistency, recall metric semantics post-fix-#5.

### 3.3 Pipeline + behavior taxonomy
- 4-state expected_behavior coverage, short-circuit correctness, critic integration (Option B gate), refusal/clarification templates, partial-escalation tagging.

### 3.4 Provider layer
- SDK conventions per vendor (anthropic vs openai vs google-generativeai), `max_completion_tokens` for GPT-5.x, `ProviderResponse` correctness, `retry_call` design (class-name MRO match, transient allowlist scope, exponential backoff), `cost_estimate_usd` accuracy.

### 3.5 Bench
- Metric implementations (7 metrics from §0.6 + refusal-tone + red-team rubric), structured judge output (matched_facts / missing_facts / irrelevant_facts), `_extract_json` robustness, cost-log honesty (post-fix #2 rename), sanity-swap correctness (post-fix #1), critic refusal-cause breakdown (post-fix #3), render-only mode + case cache (post-fix #13), red-team scoring integration.

### 3.6 Tests
- Coverage of the §0.2 / §0.3 / §0.4 design calls; coverage of Phase 4 metric additions; coverage of retry contract; whether tests verify behavior or just shape; gaps in pipeline-level coverage for Phase 3+ providers.

### 3.7 Engineering rigor (§7 of the kickoff)
- Deterministic chunking, citation contract enforcement, secrets handling (`.env.example` honesty), `print()` rule compliance, timeout/retry policies (now exercised in Phase 4), JSONL log shapes, judge-model docs alignment.

### 3.8 Documentation
- Kickoff internal coherence (does the spec contradict itself anywhere? Has the gemini-2.5-flash fallback rationale landed coherently?), working-log honesty (claims vs code), deliverables-draft completeness, planning-log §13 retroactive-entry transparency, CREATIVE.md correctness against the actual bench data, bench/results.md render-format banner accuracy.

## 4. What the prior reviews didn't anticipate

<Round 2 specific section — what surfaced in the read that Round 1 + REVIEW_NOTES_PHASE3.md missed?>

## 5. Phase 4 reviewer-fix verification

<For each of fix #1 through #13, a one-paragraph verification: did the code actually deliver what the fix claims? Cite the diff location. Mark 🟢 if delivered cleanly, 🟡 if delivered with caveats, 🔴 if not delivered.>

## 6. Severity assessment

<A table mapping every finding to its severity. Format like the reference report's §6.>

## 7. What to do next

### Before Phase 6 (must do)
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
- **No padding.** Each paragraph in the report should earn its place. Aim for the Round 1 report's density, not its length.
- **Verification-flag voice.** When you state a fact about an external library, say what you verified vs. assumed. If you're not sure whether `google.api_core.exceptions.ResourceExhausted` is in the MRO walk path or only matched by simple name, say so.
- **Adversarial reading.** Look for places where the implementation is *almost* right but subtly wrong in a way a careful reviewer would catch. The Phase 4 fixes are dense; finding even one subtle break in fix #3 / fix #5 / fix #6 is high-value.

---

## 8. Specific things to check (non-exhaustive — your own findings are welcome)

A starter list. The reviewer should add their own — the planning + Round 1 + REVIEW_NOTES_PHASE3 history flagged the obvious ones, and a competent reviewer would surface several more. Do NOT just walk this list and stop.

### 8.1 Provider layer
1. **`OpenAIProvider.generate` uses `max_completion_tokens`.** GPT-5.x API rejects legacy `max_tokens`. Verify the kwarg name and that no legacy fallback path silently sends the wrong one.
2. **`retry_call` `APIError` in the transient allowlist** — Anthropic + OpenAI both have an `APIError` BASE class that includes both transient (`APIConnectionError`) and non-transient (`BadRequestError`, `AuthenticationError`) subclasses. Does the MRO walk over-retry on non-transient errors because they inherit from `APIError`? If yes, that's a HIGH bug (silent over-retry on authentication failure burns through retry budget).
3. **`GeminiProvider` thinking-mode budget** — `judge_correctness` / `judge_faithfulness` set `max_tokens=4000` to leave room for invisible reasoning. Does this apply to the new `judge_refusal_tone` and `judge_red_team` calls as well? (Yes per metrics.py, but worth confirming.)
4. **`ClaudeProvider._client_for(timeout)`** rebuilds the SDK client per call. Does this leak file descriptors under high-volume bench runs?
5. **`cost_estimate_usd`** uses fallback pricing for unknown model IDs. If `OPENAI_MODEL_ID=gpt-5.4-mini-2026-03-17` is set, does the cost log reflect the cheaper price?

### 8.2 Bench
6. **`_pick_swap_candidate` filter** — requires `predicted_answer_text` AND `has_gold` AND `correctness_score is not None`. The q-001 skip in the current bench output suggests `correctness_score` was None for the openai pre-loop case. Trace: did the Gemini Flash judge error on q-001 specifically, or did the pre-loop run fail to populate that field?
7. **`_retrieval_was_expected` predicate** — handles standard cases and red-team cases. Does it correctly handle the `behavior_taken` mismatch case (e.g., expected `answer` but pipeline emitted `refuse`)? The metric still counts the recall=0 because it's the retrieval target that matters, not what the pipeline did.
8. **`aggregate` empty-batch behavior** — `_empty_aggregate()` returns sensible defaults. Does it break the renderer if a provider had zero cases?
9. **`render_results_md` `mode="red_team"` path** preserves Phase 3 standard numbers via the snapshot file, but doesn't carry forward refusal-tone scores from Phase 3 (which didn't have the metric). Is the visual gap explained clearly enough in the renderer output? The banner exists at the top of `bench/results.md`; the renderer should match.
10. **Critic refusal-cause breakdown counts**: trace a single case end-to-end. For example, claude/on/q-007 in the current bench output went `answer → refuse_with_redirect`. Per the per-case data, was `critic_grounded=False` (real verdict) or `critic_valid=False` (harness error)?
11. **`dump_cases` JSON encoding** — `ensure_ascii=False` preserves Arabic. Verify the cache file is UTF-8 and the round-trip preserves Arabic strings byte-exactly.
12. **`load_cases` forward compatibility** — filters JSON keys against `fields(CaseResult)`. Verify this gracefully ignores a cache from a future schema (extra keys) AND a cache from an older schema (missing keys → dataclass defaults).

### 8.3 Pipeline
13. **`_needs_partial_escalation` term list** — includes `بكرة` (Saudi dialect "tomorrow"). Does the catalog cover all forms (`بكره` without ة, `باكر`, `الغد`)? rt-003 + q-005 are the calibration points.
14. **`_has_ambiguous_date` Arabic-Indic regex** `(?<![٠-٩])[٠-٩]{1,2}/[٠-٩]{1,2}(?![٠-٩])` — does it correctly NOT match dates with calendar markers (`٥/٩ هـ`)? The CALENDAR_TERMS check should short-circuit, but cross-check the order of operations.
15. **`INPUT_LENGTH_CAP=4000` truncation** — silently truncates. Should the pipeline log when it truncates? Currently it doesn't; is that a §7 violation or acceptable?
16. **Option B trust precedence** — `not critic.grounded` overrides `_needs_partial_escalation`. Verify this is what the WORKING_LOG entry at `[15:50]` describes: "Trust gate overrides partial-escalation tagging."

### 8.4 Tests
17. **`tests/test_provider_retry.py`** — `_TRANSIENT_ERROR_NAMES` allowlist coverage. Did the test suite catch the `APIError` over-retry concern from item 2 above? If not, that's a test-coverage gap.
18. **`tests/test_bench_metrics.py` round-trip test** — verifies recall + citation accuracy survive dump+load. Does it also verify the critic refusal-cause counts survive? (The fields are present on `CaseResult`; the test should pin them.)
19. **No pipeline-level test for `partial_answer_with_escalation` × critic ungrounded** — Option B should refuse, not escalate. Is this combination pinned anywhere?

### 8.5 Documentation
20. **`bench/results.md` render-format banner** — is it honest and complete? Does it cover all three render-format gaps (cost label, missing critic breakdown section, red-team recall "—")?
21. **`MURSHID_KICKOFF.md` §0.5 `gemini-2.5-flash` rationale** — does the kickoff text and `.env.example` agree on what "primary plan vs measured fallback" means?
22. **`docs/CREATIVE.md` flag-of-pending-data** — the doc says red-team rubric pass-rate and refusal-tone aggregates land in `bench/results.md` after the Phase 4 re-run. The re-run happened (red-team-only mode); the data is now there. Should the CREATIVE.md be updated to remove the "pending" framing?
23. **`docs/WORKING_LOG.md` honesty** — multiple entries claim Phase 4 reviewer fixes were applied. Verify the code matches every claim.

---

## 9. Output filename

`REVIEW_REPORT_ROUND2.md`. Place at the repo root or at `.private/REVIEW_REPORT_ROUND2.md` per your convention.

---

## 10. Acknowledgments

The reference structure (§6) is adapted from Round 1, which adapted it from `MagnaCMS .private/REVIEW_REPORT_ROUND2.md` — same severity scheme, same per-area structure.

Murshid has now gone through three pre-Phase-1 reviewer rounds on the dataset and design contract, a Round 1 review of Phase 1+2 code, and a private Phase 3 review note. The round 2 review now in your hands is the FIRST review of the FULL Phase 1-4 shipped codebase, with the trust-thinking artifacts (sanity-swap polish, critic refusal-cause breakdown, refusal-tone metric, red-team rubric judge) all in place.

Be useful. Push back. Specifically: verify that the Phase 4 reviewer-fix batch actually delivers what `docs/WORKING_LOG.md` and `docs/TIME_LOG.md` claim — that's where the highest-value findings will land.

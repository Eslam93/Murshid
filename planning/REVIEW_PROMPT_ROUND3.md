# Murshid — Round 3 Review Prompt (full state: Phases 1-9 + creative add-ons + support gate)

> Paste this entire file into a fresh reviewer session. The reviewer should
> have repo access (or the relevant files pasted in). The expected output is
> a single Markdown document titled `REVIEW_REPORT_ROUND3.md` matching the
> structure in §6 below.
>
> **Note on cleaned-up references:** This template was calibrated for the
> Murshid build state at the time of Round 3. References inside to
> `REVIEW_REPORT_ROUND1.md`, `REVIEW_NOTES_PHASE3.md`, `REVIEW_REPORT_ROUND2.md`,
> `REVIEW_REPORT_ROUND2_FOLLOWUP.md`, and `docs/TIME_LOG.md` point at files
> that lived during the build but were deleted as part of submission cleanup
> (the reports as ephemera; TIME_LOG for privacy — see the note at the top
> of `docs/WORKING_LOG.md`). The review-pipeline context is summarized in
> `docs/AI_JOURNAL.md` § "The multi-round review pipeline" — read that
> section first. Treat instructions inside the prompt that say "read
> REVIEW_REPORT_ROUNDx first" as "consult the AI_JOURNAL pipeline section
> for the corresponding round's calibration."

---

## 1. Context

**Project:** Murshid — Arabic-first RAG over Saudi government-services FAQs.
A take-home for Adree's Principal AI Engineer role. CLI demo; 20 source
documents; 16 user questions; 11 gold answers; 10 red-team adversarial cases.

**Round 3 is the SUBMISSION-READINESS review.** The codebase is now at
**202/202 tests passing**, with all four graded docs shipped, two creative
add-ons built, and the deterministic pre-generation support gate that
closes the Round 2 follow-up residual open issue.

**Where things stand (Phase-by-phase):**

- **Phase 1** (foundations + mock end-to-end with BGE-M3 dense retrieval) — shipped 2026-05-22.
- **Phase 2** (register detection + service-category router + multi-view hybrid retrieval + critic + 3-question mock demo) — shipped 2026-05-22.
- **Phase 3** (real provider SDKs: Claude `claude-sonnet-4-6`, OpenAI `gpt-5.5-2026-04-23`, Gemini judge; structured-output judge with fact-count breakdown; critic-on/off dual-pass bench; 7 metrics; sanity-swap with `claude-opus-4-7`; Phase 6 hardening: Arabic-Indic numeral detection in `_has_ambiguous_date`, router synonyms + weighted scoring `تصريح العمل` > bare `تصريح`, Egyptian + Levantine dialect markers, ADR 3 scope subsection) — shipped 2026-05-22.
- **Phase 4** (red-team scoring with per-case rubric judge consuming `evaluation_notes` verbatim; refusal-tone metric judge-scored 0-3; sanity-swap fixture polish that re-scores the SAME prediction across two judges; retry policy on provider calls; `--render-only` mode + bench case cache; `CREATIVE.md` one-page draft) — shipped 2026-05-23. Plus R2 reviewer fixes #2/#3/#4/#5/#6/#13 folded in.
- **Phase 5** — SKIPPED per kickoff §8 cut order #3/#4 (Falcon-Arabic + Gemini-as-benchmarked-provider). Documented as path-not-taken in ADR 2 + GCC production gaps + CREATIVE.md §4.
- **Phase 6** (`docs/ARCHITECTURE.md` — 11-section narrative: product contract + ASCII + Mermaid diagrams + 16-row component contracts table + ADRs 1/2/3 + Arabic risks + GCC gaps + predictive walkthrough + open issues + closing) — shipped 2026-05-23.
- **Phase 7** (`docs/AI_JOURNAL.md` — 3 decisional prompts, 1 Arabic-specific mistake caught, 1 autonomous-handoff-with-guardrails, honest reflection) — shipped 2026-05-23.
- **Phase 8** (`README.md` written from real work + creative add-ons SHIPPED: `hijri.py` structured detection AND Arabic-Indic numeral normalization at the retrieval layer) — shipped 2026-05-23.
- **Phase 9** (smoke test 118/118 → 202/202 over the session; `SUBMISSION_NOTE.md` 149 words; total session time captured in `docs/TIME_LOG.md`) — shipped 2026-05-23.
- **Bonus: deterministic pre-generation support gate** (R2 2.3 heavier variant the Round 2 reviewer named as the production-correct fix for rt-001 / rt-002) — shipped 2026-05-23 at 03:15. Closes the only remaining trust-thinking residual open issue from the R2-followup review.

**Prior reviews already on file:**

- `REVIEW_REPORT_ROUND1.md` — Codex GPT-5 review of Phases 1+2. 5 HIGH + 13 MEDIUM + 8 GOOD. **All resolved** before Phase 3 began.
- `REVIEW_NOTES_PHASE3.md` — private adversarial read of Phase 3. 6 findings. **All folded into Phase 4 work** as reviewer fixes #2-#6 + #13.
- `REVIEW_REPORT_ROUND2.md` — Codex GPT-5 review of Phases 1-4 (post Phase 4 + R2 fix batch). 0 CRITICAL, 3 HIGH, 7 MEDIUM, 10 GOOD. **Recommended batch applied** (R2 2.1 retry blocklist, 2.2 register decoupling, 2.3 critic prompt tightening + heavier-variant-deferred, 4 MEDIUM quick wins).
- `REVIEW_REPORT_ROUND2_FOLLOWUP.md` — Codex GPT-5 verification pass after the R2 fixes. **5 fixes 🟢 closed, 2 🟡 (artifact stale / policy bait not proven), 1 🟠 HIGH (artifact staleness).** The artifact-staleness HIGH was addressed via a focused 24-cell bench re-run (results in `bench/results.md` + snapshots in `bench/results-pre-r2-fixes.md` and `bench/results-r2-pre-tokens-bump.md`). The "policy bait not proven closed" 🟡 was addressed by the support gate that ships in this round.

**Round 3 is the FIRST review of the full Phase 1-9 + creative + support-gate codebase, with the trust-thinking story now complete at three deterministic layers (router OOS / pre-gen support / critic gate) plus the model-side critic.**

**What to expect from the codebase:**

- **202/202 tests pass** (`pytest tests/ -q`). Distribution: 18 normalization + 11 ingest + 6 register + 16 router + 28 pipeline (incl. support-gate gating + critic gate Option B + Phase 6 hardening + 4-state behavior contract) + 28 bench metrics + 13 provider retry + 33 hijri + 31 arabic-indic + 20 support gate.
- Bench is real and `bench/results.md` is the canonical evidence with banner. `bench/results-phase3-snapshot.md` carries the broader 16-question standard set. The current `bench/results.md` PREDATES the support gate; the next bench run would flip rt-001 / rt-002 cells.
- All 5 providers from kickoff §0.5 are implemented; the bench currently runs Mock + Claude + OpenAI. Gemini doubles as the judge (`gemini-2.5-flash` actual; `gemini-3.1-pro-preview` was the primary plan that hit thinking-budget + 250/day-quota issues during the first bench run — documented as a measured fallback). Falcon-Arabic via Ollama is a Phase-5 item per cut order, stub present.

**What is NOT in scope for Round 3:**

- Re-running the bench. The current artifacts are the submission evidence; the reviewer scores against them, not against a fresh run. Mention if a re-run is warranted but do not require one.
- The Falcon-Arabic provider class (stub). Phase 5 work; mention only if architecturally relevant.

---

## 2. Reviewer role

You are **Claude Opus 4.7 (1M context)** — or any reviewer of equivalent
depth — reviewing the codebase the way a senior staff engineer would on a
take-home submission for a Principal AI Engineer role. **This is the
submission-readiness review.** A clear pass means the repo can be sent
without further changes; a clear hold means specific items must be fixed
before submission.

**Calibration:**
- Take the verification-flag voice the codebase prescribes (§6 of `MURSHID_KICKOFF.md`). When you state a fact about the code, cite the file:line.
- Cross-reference the prior review reports (`REVIEW_REPORT_ROUND1.md`, `REVIEW_NOTES_PHASE3.md`, `REVIEW_REPORT_ROUND2.md`, `REVIEW_REPORT_ROUND2_FOLLOWUP.md`). **Do NOT re-litigate findings already closed; do flag any that the closing-claim doesn't actually deliver in the current code.**
- Be willing to disagree with the kickoff's design calls if you have evidence. The kickoff went through three reviewer rounds before code shipped, but it is not infallible.
- Calibrate severity by impact, not surface area. A subtle Arabic-handling bug ranks higher than a missing type hint.
- **Specifically verify** that the support gate (R2 2.3 heavier variant) actually delivers what `docs/WORKING_LOG.md` `[03:15]` claims, and that the creative add-ons (`hijri.py` + Arabic-Indic) work as described in `docs/CREATIVE.md` §7.

**What you are NOT being asked to do:**
- Run the bench. The artifact is `bench/results.md` + `bench/results-phase3-snapshot.md` + `bench/cost-log.jsonl` + `bench/refusal-log.jsonl` + `bench/case-cache.json` + the three historical snapshots.
- Score the brief PDF directly — read it for context, score the implementation against the kickoff (which already encodes the brief's rubric).
- Recommend a different architecture wholesale. The kickoff is the contract; review the implementation against it.

---

## 3. Scope (read these files in this order)

### 3.1 Brief + authoritative spec
1. `Principal_AI_Engineer_Task.pdf` — the rubric and constraints.
2. `MURSHID_KICKOFF.md` — the locked design contract (§0 decisions, §2 layout, §3 phase plan, §6 voice, §7 rigor, §8 cut order).

### 3.2 Prior review history (read FIRST so Round 3 doesn't re-litigate closed items)
3. `planning/REVIEW_PROMPT_ROUND1.md` + `REVIEW_REPORT_ROUND1.md` — Phase 1+2 review.
4. `REVIEW_NOTES_PHASE3.md` — private adversarial Phase 3 read.
5. `planning/REVIEW_PROMPT_ROUND2.md` + `REVIEW_REPORT_ROUND2.md` — Phase 1-4 review.
6. `REVIEW_REPORT_ROUND2_FOLLOWUP.md` — verification pass after R2 fixes.

### 3.3 Final graded documents (the four)
7. `README.md` — submission orientation. Two-minute setup, 3-question demo, reading order for the reviewer (~25 min total), honest "what's NOT in this submission" section.
8. `docs/ARCHITECTURE.md` — 11-section narrative with ASCII + Mermaid diagrams, 16-row component contracts, ADRs 1/2/3, Arabic risks, GCC gaps, predictive walkthrough (q-007 end-to-end), open issues honestly named, closing.
9. `docs/AI_JOURNAL.md` — 3 decisional prompts (stdlib-vs-CAMeL Tools normalization, Critic Option B, conservative-allowlist exclusion), 1 Arabic-specific mistake (the `صدر` polysemy), 1 autonomous handoff with guardrails (the Phase 4 reviewer-fix batch), honest reflection.
10. `docs/CREATIVE.md` — trust-problem-not-retrieval-problem opening, red-team harness primary section, chunking + retrieval + Arabic model strategy (ALLaM / Jais / Fanar / SILMA / Hala by name) + normalization + dialect handling + "important product decision" callouts, Hijri + Arabic-Indic creative add-ons under "Shipped" with implementation detail, closing.
11. `SUBMISSION_NOTE.md` — 149 words (under 150 limit). Proud-of / would-revisit / LLM provider.

### 3.4 Pre-Phase-1 planning artifacts (context for why things are the way they are)
12. `planning/PLANNING_LOG.md` — chronological history of decisions, three reviewer rounds, four external RAG-architecture learnings, accumulated pushbacks. §13 contains 6 retroactively-logged planning-phase moments marked as such.
13. `planning/DELIVERABLES_DRAFT.md` — pre-staged content for the final docs.
14. `planning/PLAN_SUMMARY.md` — plain-English current plan.
15. `planning/CREATIVE_INITIAL.md` + `planning/ARCHITECTURE_INITIAL.md` — initial drafts; cross-check that the final docs preserve the inspiring data Eslam flagged.

### 3.5 Data files
16. `data/sources.json` (20), `data/questions.json` (16), `data/gold_answers.json` (11), `data/red_team.json` (10).

### 3.6 Phase 1-8 + support-gate + creative-add-on source code
17. `src/murshid/normalize.py` — light Arabic normalization (§0.2 four-step), plus the Phase 8 Arabic-Indic add-on `fold_arabic_indic_digits` + `to_arabic_indic_digits`. Note: digit folding is INTENTIONALLY separate from `light_normalize` (frozen §0.2 spec); test `tests/test_arabic_indic_digits.py:test_light_normalize_does_NOT_fold_digits` pins this.
18. `src/murshid/ingest.py` — deterministic chunker, enrichment with `Chunk.enrichment_status` field, BGE-M3 embedding, in-memory index.
19. `src/murshid/retrieve.py` — multi-view + hybrid (BM25 + dense) + RRF (K=60) + service-category filter. **R3-specific:** `_bm25_normalize(text)` composes `fold_arabic_indic_digits(light_normalize(text))` and is applied to BOTH the BM25 indexing input AND the per-view query token list. Dense retrieval uses the unfolded view.
20. `src/murshid/register.py` — three-class detector, 14-token domain allowlist (`unpaid`/`rejected` deliberately excluded), MSA-formal + dialect-marker → `mixed` rule, Egyptian + Levantine marker families.
21. `src/murshid/router.py` — Arabic-keyword classifier with `_weighted_keyword_score`, `MEDICAL_PATTERNS` regex for `صدر` polysemy, hard/soft OOS distinction, synonym expansion.
22. `src/murshid/rewrite.py` — dialect → MSA query rewriter, `[ROLE: rewrite]` sentinel.
23. `src/murshid/prompts.py` — canonical `SYSTEM_PROMPT_AR` + few-shot exemplars.
24. `src/murshid/critic.py` — register + groundedness gate. R1 fix: default-FAIL via `valid: bool`. P3 fix: robust `_extract_json` for markdown-wrapped responses. **R2 2.3 fix:** prompt explicit on `topic_overlap_not_support` + 5 other issue tags. **R2-followup fix:** `max_tokens=4000` (was 512; matches judge — thinking-mode budget).
25. `src/murshid/pipeline.py` — full router → register → rewrite → retrieve → **pre-gen support gate** → generate → critic flow. **NEW R3:** `_assess_specific_support` + `SUPPORT_GATE_REFUSAL_AR` + `support_gate_enabled: bool = True` parameter on `answer_question`. Bait pattern families (hearsay / auto-action / special-exemption); specific-term extraction (numeric / demographic / time-threshold / auto-action verbs); strict ALL-match rule.
26. `src/murshid/hijri.py` — Phase 8 creative add-on. `extract_hijri_dates(text) -> list[HijriDate]` + `has_hijri_date(text)` + `canonicalize_month_name(variant)`. 12 Hijri months with spelling variants (`ربيع الأول` / `ربيع الاول`, `ذو القعدة` / `ذي القعدة`, `ربيع الثاني` ↔ `ربيع الآخر`). Stdlib regex only. Calendar arithmetic + Gregorian conversion deliberately out of scope.
27. `src/murshid/providers/base.py` — `LLMProvider` Protocol + `ProviderResponse` + `retry_call`. **R2 2.1 fix:** `_NON_TRANSIENT_ERROR_NAMES` blocklist checked BEFORE the transient allowlist so `BadRequestError(APIError)` etc. don't over-retry.
28. `src/murshid/providers/mock.py` — `[ROLE: ...]` sentinel routing.
29. `src/murshid/providers/claude.py` — `anthropic` SDK, `claude-sonnet-4-6` default, `_CLAUDE_PRICING` table, wrapped in `retry_call`.
30. `src/murshid/providers/openai.py` — `openai` SDK, `gpt-5.5-2026-04-23`, **uses `max_completion_tokens`** (GPT-5.x API requirement).
31. `src/murshid/providers/gemini.py` — `google-generativeai` SDK, doubles as judge (Flash actual fallback).
32. `src/murshid/providers/falcon_arabic.py` — Phase 5 stub.
33. `src/murshid/bench/metrics.py` — 7 metrics + structured judges + `evaluate_case` + `evaluate_red_team_case` + `aggregate` + `dump_cases` / `load_cases` + R2 fix #5 `_retrieval_was_expected` predicate + R2 fix #3 critic refusal-cause counters + Phase 4 refusal-tone + red-team rubric judge.
34. `src/murshid/bench/runner.py` — `python -m murshid.bench [--mode full|red_team|standard] [--question-ids ...] [--red-team-ids ...] [--render-only] [--no-sanity-swap]` entry. Outputs `bench/results.md` + 3 JSONL logs + `bench/case-cache.json`.

### 3.7 Tests (the contract pinning)
35. `tests/test_normalization.py` (18), `tests/test_ingest.py` (11), `tests/test_register.py` (6), `tests/test_router.py` (16), `tests/test_pipeline.py` (28 — 4-state behavior + critic gate Option B + Phase 6 hardening), `tests/test_bench_metrics.py` (28 — Phase 4 metrics + R2 fixes #3/#5/#13 + judge prompt parsing), `tests/test_provider_retry.py` (13 — R2 fix #6 + R2 2.1 SDK-shaped regression), `tests/test_hijri.py` (33 — structured detection + integration scans), `tests/test_arabic_indic_digits.py` (31 — unit + retrieval composition + light-normalize invariant), `tests/test_support_gate.py` (20 — unit + pipeline integration + `support_gate_enabled=False` ablation). **Total: 202/202.**

### 3.8 Demo + bench + log artifacts
36. `demo_output.txt` — 3-question demo execution output (UTF-8, RTL Arabic).
37. `bench/results.md` — current canonical artifact (24-cell focused R2-followup post-tokens-bump). **PREDATES the support gate.**
38. `bench/results-phase3-snapshot.md` — Phase 3 standard tables (16 questions × providers × critic modes), the breadth artifact.
39. `bench/results-pre-r2-fixes.md` — Round 2 pre-fixes baseline, historical.
40. `bench/results-r2-pre-tokens-bump.md` — pre-critic-max_tokens bump, historical.
41. `bench/cost-log.jsonl`, `bench/refusal-log.jsonl`, `bench/case-cache.json`.
42. `docs/WORKING_LOG.md` — append-only build log with the full trace from Phase 1 kickoff through the support gate at `[03:15]`.
43. `docs/TIME_LOG.md` — session timeline, all phase boundaries.
44. `requirements.txt`, `.env.example`, `.gitignore`, `pyproject.toml`, `conftest.py`.

---

## 4. Approach

**Direct read.** Open every file you cite. The codebase has grown to ~3000 lines of real Python + ~1900 lines of tests; the docs are ~10000 words across the four graded files.

**Cross-reference prior reviews — don't re-litigate.** Read REVIEW_REPORT_ROUND1, REVIEW_NOTES_PHASE3, REVIEW_REPORT_ROUND2, REVIEW_REPORT_ROUND2_FOLLOWUP first. Items already closed should not appear as NEW findings; items the closing-claim doesn't deliver are HIGH findings.

**Verify the NEW pieces:**

- **Support gate (R3 highest value).** `pipeline._assess_specific_support` + `SUPPORT_GATE_REFUSAL_AR` + `support_gate_enabled` parameter. Verify by reading `tests/test_support_gate.py` (20 cases) + the pipeline integration. The reviewer's 🟡 "policy bait not proven closed" from R2 follow-up is the test this needs to pass.
  - Does the gate fire on rt-001 / rt-002 deterministically?
  - Does rt-009 still answer (no false positive)?
  - Does the `support_gate_enabled=False` ablation prove the gate is the cause?
  - Are the three pattern families (hearsay / auto-action / special-exemption) reasonable? Are they too narrow (would miss novel bait) or too broad (would false-positive on legit questions)?
  - The "ALL specific terms must match" rule — is it too strict (false-refuses legit questions) or appropriate?
- **Hijri detection (creative add-on).** `src/murshid/hijri.py`. Verify by reading `tests/test_hijri.py` (33 cases).
  - Does the canonicalization cover the spelling variants a reviewer would probe with?
  - Is the "year-only over-trigger guard" tight enough?
  - The scope decision to NOT do calendar arithmetic — defensible?
- **Arabic-Indic numeral normalization (creative add-on).** `normalize.fold_arabic_indic_digits` + `retrieve._bm25_normalize`. Verify by reading `tests/test_arabic_indic_digits.py` (31 cases).
  - Is the retrieval-layer (vs `light_normalize`-layer) integration correct?
  - Does the test `test_light_normalize_does_NOT_fold_digits` pin the §0.2 invariant adequately?
  - The dense embedding NOT folded — is that the right call?
- **The four graded docs.** Read end-to-end. Specifically:
  - `README.md` reading-order claim: does following the 25-minute reading path actually orient a fresh reviewer?
  - `ARCHITECTURE.md` predictive walkthrough: can a reader who has not opened the code predict behavior on a fourth invented question?
  - `AI_JOURNAL.md` honesty: does the "where AI hurt" section name real failure modes or is it self-congratulatory?
  - `CREATIVE.md` discipline: does the "important product decision" framing land, or is it bullet-list theater?
  - `SUBMISSION_NOTE.md`: 149 words, three sections, honest.

**Look for things the planning + Round 1 + Round 2 + R2 follow-up didn't anticipate.** This is the highest-value part of Round 3. Three review rounds + a private adversarial read + a follow-up have filtered the obvious findings; what's still subtly wrong?

**Calibrate against the brief's rubric weighting:**
1. Arabic technical depth — covered by `صدر` polysemy fix, conservative allowlist, Egyptian/Levantine markers, Hijri detection, Arabic-Indic fold, citation translation discipline (rt-010).
2. Vibe-coding fluency — verifiable from code quality, test coverage, doc clarity.
3. Architecture & docs — ARCHITECTURE.md predictive walkthrough is the test.
4. Trust thinking — three deterministic refusal layers (router OOS / pre-gen gate / critic) + the model-side critic. Support gate is the load-bearing piece.
5. Creativity — red-team harness + structured judge fact-counts + Hijri + Arabic-Indic + the support gate.
6. Engineering rigor — 202/202 tests, deterministic chunking, citation contract, retry policy, refusal log.

---

## 5. Severity bar

| Severity | Meaning | Example |
| --- | --- | --- |
| 🔴 CRITICAL | Breaks the demo, mishandles Arabic in a way a reviewer will spot, or leaks data | Support gate over-refuses q-007 / q-001 in observable cases; Arabic-Indic fold breaks BM25 indexing |
| 🟠 HIGH | Real bug or significant design gap; needs a fix before submission | The "closed" rt-001 still falls through somehow; Hijri canonicalization misses a spelling variant in the data; a docs claim contradicts code |
| 🟡 MEDIUM | Quality concern; should fix but not blocking | Working-log entry overstates the gate's coverage; test gap; docstring inaccuracy |
| 🟢 GOOD | Worth calling out as a deliberate strength | The all-match rule + the rt-009 negative test; the §0.2-frozen-spec discipline on the digit fold; the three-layer trust narrative |

**Expected distribution for Round 3:** 0 CRITICAL (this is the submission-ready review; CRITICAL means hold), 0-2 HIGH, 3-7 MEDIUM, several GOOD. If your distribution is dramatically skewed toward HIGH or CRITICAL, the codebase isn't submission-ready and you should hold; if toward all-GOOD, you may be missing something.

---

## 6. Required output structure

Produce a single Markdown document titled `REVIEW_REPORT_ROUND3.md`. Use this exact section structure:

```markdown
# Murshid — Round 3 Review (submission readiness)

> Reviewer: <your model + identifier>
> Review date: <yyyy-mm-dd>
> Scope: Phases 1-9 + creative add-ons + deterministic pre-generation support gate
> Approach: <1-3 sentences on how you reviewed — direct read of every file, etc>
> Verdict: <PASS / PASS-WITH-CAVEATS / HOLD>

## 1. Submission readiness verdict

<2-4 paragraphs. Is the repo submittable now? What would you change before sending it? What is the rubric-criterion-by-criterion read?>

## 2. Critical findings

<Empty if none. Each finding is a numbered subsection with file:line citations + diagnosis + severity rationale + concrete fix patch.>

## 3. Per-area findings

### 3.1 Trust gate stack (router OOS / pre-gen support / critic / model-side critic)
- The headline new piece. Specifically address: does the support gate fire correctly on rt-001 / rt-002? Does the rt-009 negative test hold? Does the ALL-match rule under-refuse or over-refuse on any case you can imagine? Are the three pattern families reasonable?

### 3.2 Arabic technical depth
- Normalization (§0.2 four-step + Arabic-Indic fold composition), register (3-class + Egyptian/Levantine + conservative allowlist), router (weighted scoring + `صدر` polysemy + synonyms), Hijri canonicalization, citation translation discipline.

### 3.3 Retrieval
- Multi-view fusion, BM25/dense alignment, RRF K=60, service-category filter pre-scoring, the `_bm25_normalize` composition that folds Arabic-Indic digits.

### 3.4 Pipeline + behavior taxonomy
- 4-state expected_behavior coverage, short-circuit correctness, critic Option B, partial-escalation tagging, support-gate integration ordering (after retrieve, before generate).

### 3.5 Provider layer
- SDK conventions (anthropic / openai with `max_completion_tokens` / google-generativeai), `retry_call` blocklist correctness, `cost_estimate_usd` honesty.

### 3.6 Bench + metrics
- 7 metrics + structured judges + Phase 4 additions (refusal-tone + red-team rubric) + R2 fixes (critic refusal-cause breakdown + non-answer recall exclusion + cost-rename + dump/load round-trip).

### 3.7 Creative add-ons
- Hijri detection (canonicalization coverage, year-only guard, the scope decision to skip arithmetic), Arabic-Indic numeral fold (the §0.2-frozen-spec discipline, the BM25-vs-dense split decision).

### 3.8 Tests
- Coverage of all the contract claims; gaps where claims-without-tests exist; the `support_gate_enabled=False` ablation discipline.

### 3.9 Engineering rigor (§7 of the kickoff)
- Deterministic chunking, citation contract, secrets handling, `print()` rule, refusal-log shape post-R2 enrichment, JSONL log shapes, judge-model docs alignment.

### 3.10 Documentation
- README reading-order claim, ARCHITECTURE predictive walkthrough, AI_JOURNAL honesty, CREATIVE "important product decision" callouts, SUBMISSION_NOTE under 150 words, planning artifacts coherence (especially the §13 retroactive entries' provenance markers).

## 4. What prior reviews didn't anticipate

<Round 3 specific section — what surfaced in the read that Rounds 1, 2, 2-followup, and the private R3 notes missed? Most-value section.>

## 5. Prior-review-closure verification

<For each prior reviewer finding marked closed, verify the closing claim holds in the current code. Mark 🟢 if delivered, 🟡 if delivered with caveats, 🔴 if not delivered. Cite the relevant lines.>

| Round | Finding | Status | Verification |
| --- | --- | --- | --- |

## 6. Submission housekeeping

<Items not in the kickoff phase plan but the brief implies. git init / private repo / SUBMISSION_NOTE wording / fresh-clone smoke / etc.>

## 7. Severity assessment

<Table mapping every finding to its severity.>

## 8. What to do (if HOLD) or What to consider before sending (if PASS)

### Before submission (must do, if HOLD)
<numbered list with time estimates>

### Consider (if PASS)
<bullet list>

### Defer (acknowledged trade-offs)
<bullet list>

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
- **Show diffs for fixes.** Patches not prose suggestions.
- **No sycophancy.** Don't open with "great work overall." If the work is good, the GOOD bullets carry that weight.
- **Verification-flag voice.** When you state a fact about an external library, say what you verified vs assumed. The codebase prescribes this voice; the review report should adopt it.
- **Adversarial reading.** Look for places where the implementation is *almost* right but subtly wrong. Three review rounds and a private read have filtered the obvious; subtle subtle subtle is the Round 3 game.

---

## 8. Specific things to check (non-exhaustive — your own findings are welcome)

### 8.1 Support gate (R3 highest priority)
1. **Pattern coverage.** Three families (hearsay, auto-action, special-exemption). Are there bait phrasings in the rt-set or in plausible reviewer probes that would slip through?
2. **All-match rule.** rt-002's terms are `{تنحذف, ستة أشهر}`; the corpus contains `ستة أشهر` in an installment-eligibility clause (coincidental). The all-match rule fires because `تنحذف` is missing. Is this the right rule, or does it create false-refuses on legit questions with partial term overlap with corpus?
3. **rt-009 narrow miss.** The hearsay regex matches `قيل لي` / `قالوا لي` / `سمعت أن` but NOT `قال لي` (first-person, rt-009). Verify this distinction holds for the reviewer's probes.
4. **Time-threshold extraction.** `_extract_bait_specific_terms` handles `ستة أشهر`, `60 يوماً`, etc. Does it cover `سنتين` (two years dual form), `ربع سنة`, `نصف عام`?
5. **`support_gate_enabled=False` ablation.** Is the toggle actually tested end-to-end? `test_rt001_with_gate_disabled_falls_through_to_answer` is the pin.

### 8.2 Hijri detection
6. **Spelling variant coverage.** Are there variants in the corpus + question data that the 12-month map doesn't canonicalize? Run `grep -E 'محرم|صفر|ربيع|جمادى|رجب|شعبان|رمضان|شوال|ذو|ذي' data/` and cross-reference against the variant lists.
7. **Year-only over-trigger guard.** `test_year_only_does_not_match` pins that `سنة 1447هـ` is NOT a Hijri date. Is this the right call, or are there cases where a year-only mention should be structured?
8. **`HijriDate.__post_init__` range checks.** `day=31` raises (Hijri max is 30); is this the right strictness?

### 8.3 Arabic-Indic numeral fold
9. **Composition order.** `_bm25_normalize` is `fold_arabic_indic_digits(light_normalize(text))`. Is the order correct? Does light_normalize touch digits in any way that breaks the fold?
10. **§0.2 invariant.** `test_light_normalize_does_NOT_fold_digits` pins that the digit fold is NOT in `light_normalize`. Is this discipline visible enough in the docs (CREATIVE.md, ARCHITECTURE.md)?
11. **Dense embedding NOT folded.** Is this defensible, or should the dense input also be folded for consistency?

### 8.4 Prior-review-closure verification (cross-reference the four prior reports)
12. Round 1 HIGHs: `صدر` polysemy, 4-state behavior contract, critic structural fix, enrichment exception breadth, pipeline-level behavior tests. All claimed closed.
13. Round 2 HIGHs: 2.1 retry blocklist (verify `BadRequestError(APIError)` doesn't retry in current code), 2.2 register decoupling (`Answer.question_register` vs `Answer.answer_register`), 2.3 critic prompt tightening (the 6 issue tags).
14. R2 follow-up 🟡: policy bait closed (the support gate built in this round is the answer; cross-check it actually closes).
15. R2 fix #5 (non-answer recall exclusion) — verify `_retrieval_was_expected` predicate handles red-team cases with `expected_source_ids`.

### 8.5 Documentation honesty
16. **ARCHITECTURE.md predictive walkthrough** (q-007 trace). Step through it; can you predict the system's behavior on a fourth invented question without reading code?
17. **AI_JOURNAL.md "where AI hurt"** section. Are the failure modes named real, or self-congratulatory?
18. **CREATIVE.md "important product decision"** callouts. Are they all defended, or one of them filler?
19. **README.md reading order** (25 min). Does following it actually orient a fresh reviewer?
20. **SUBMISSION_NOTE.md**. 149 words; three sections. Is the "would revisit" item actionable, or vague?
21. **`docs/WORKING_LOG.md`** at `[03:15]` — verify the support gate claims against the code.

### 8.6 Submission housekeeping (not in the kickoff phase plan, but the brief implies)
22. **Git init + private repo.** The kickoff §9 says "A private Git repo containing the structure in §2." Is the repo git-initialized? If not, the submission instructions need it.
23. **Total session time** in `docs/TIME_LOG.md`. Kickoff §5 format mentions a "Total session time: HH:MM" line. Present?
24. **Fresh-clone smoke**. Does `pip install -e .` + `pytest` + `python scripts/demo.py` actually work end-to-end in a temp dir following README?

---

## 9. Output filename

`REVIEW_REPORT_ROUND3.md`. Place at the repo root or at `.private/REVIEW_REPORT_ROUND3.md` per your convention.

---

## 10. Acknowledgments

The reference structure (§6) is adapted from Round 1, which adapted from `MagnaCMS .private/REVIEW_REPORT_ROUND2.md` — same severity scheme.

Murshid has now gone through:
- 3 pre-Phase-1 reviewer rounds on the dataset and design contract (`planning/PLANNING_LOG.md`)
- Round 1 (Codex GPT-5) of Phase 1-2 code (5 HIGH + 13 MEDIUM, all closed)
- Private Phase 3 adversarial pass (REVIEW_NOTES_PHASE3.md, 6 findings, all folded into Phase 4)
- Round 2 (Codex GPT-5) of Phase 1-4 code (3 HIGH + 7 MEDIUM, recommended batch + heavier variant later)
- Round 2 follow-up (Codex GPT-5) verification (5 fixes closed, 2 caveated, 1 HIGH artifact staleness)

This Round 3 is the FIRST review of the **submission-ready** state: Phase 1-9 shipped + two creative add-ons + the deterministic pre-generation support gate that the Round 2 reviewer named as the production-correct fix for the rt-001 / rt-002 residual.

Be useful. Push back. The Round 3 reviewer's role is to make the PASS-vs-HOLD verdict the user can act on without having to re-read every prior report.

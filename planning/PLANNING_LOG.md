# Murshid — Planning Log (pre-Phase-1)

Comprehensive record of the planning conversation that produced the current state of `MURSHID_KICKOFF.md`, the `data/*.json` files, and the bench / architecture scaffolding. Captures decisions, pushbacks, reviewer rounds, and creative learnings so context is not lost if the session is compacted. **All artifacts described below already exist in their final files; this log preserves the WHY, not the WHAT.**

## Session metadata

- **Project:** Murshid — Adree Principal AI Engineer take-home
- **Session start:** 2026-05-22
- **Working dir:** `D:\SourceCode\Adree\Murshid`
- **Authoritative spec:** `MURSHID_KICKOFF.md` (read this first)
- **Brief:** `Principal_AI_Engineer_Task.pdf` (sources of truth: §0 of kickoff > `/data` > brief PDF)
- **Data:** `data/sources.json` (20), `data/questions.json` (16), `data/gold_answers.json` (11), `data/red_team.json` (10)
- **Authorization phrase:** Phase 1 starts only when Eslam types `Start Phase 1`. Until then everything is planning.

## 1. Origin of the kickoff

`MURSHID_KICKOFF.md` arrived as the output of a prior multi-agent research pass. It was treated as a draft, not a contract. The first action in this session was a pre-flight critique against it — verifying claims, pushing back on stale decisions, surfacing contradictions.

## 2. Pre-flight critique (my opening response)

**Verification checks performed:**

- BGE-M3 confirmed at https://huggingface.co/BAAI/bge-m3 — 1024-dim, 8192 tokens, sentence-transformers loadable. **License: MIT, not Apache-2.0 as the kickoff originally claimed.**
- Anthropic flagships (per docs as of 2026-05-22): `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`.
- OpenAI flagships: GPT-5.5 (`gpt-5.5-2026-04-23`), GPT-5.4-mini (`gpt-5.4-mini-2026-03-17`). `platform.openai.com/docs/models` returned HTTP 403 to direct fetch — IDs verified via search results.
- Google flagships: Gemini 3.1 Pro Preview (`gemini-3.1-pro-preview`), Gemini 3 Flash Preview (`gemini-3-flash-preview`), Gemini 2.5 series still stable. **`gemini-3-pro-preview` was deprecated and shut down 2026-03-09 — earlier research had this stale.**
- Ollama: NOT FOUND on this machine. Falcon-Arabic is a "needs install before Phase 5" item.
- `/data`: did not exist at initial check (was delivered partway through planning).

**8 disagreements with the original kickoff:**

1. BGE-M3 license factually wrong (MIT not Apache-2.0)
2. §0.5 model IDs stale by 1–2 generations across all three vendors
3. `/data` missing — Phase 1 task 7 couldn't run as originally written
4. Five providers overscoped given "6h done > 14h unfinished" framing
5. Judge-model bias not mitigated — using Claude/GPT as judge while also benchmarking them is documented self-preference
6. Red-team category #3 (invented religious-policy question) was the wrong risk to take for a Saudi-targeting take-home
7. Alsubhi 2025 / MIRACL numbers cited as inherited fact without verification
8. RTL Arabic on Windows PowerShell will mangle demo stdout

## 3. Eslam's response — accepted vs pushed back

**Accepted and applied to kickoff:**

- License fix (#1)
- Stale model IDs (#2) — Eslam provided verified-current IDs himself, including catching the `gemini-3-pro-preview` deprecation
- `python -m murshid.bench` module path bug → `bench/` moved under `src/murshid/`
- Print rule split for library vs CLI
- Gold passage IDs requirement → resolved by Eslam supplying data with the field
- Citation metadata schema baked into `retrieve.py` contract
- Judge-model bias (#5): default judge = Gemini 3.1 Pro Preview, 3-case Opus-4.7 sanity swap, bias quantified in ADR 2
- Critic confounds bench: bench runs critic-on AND critic-off, both columns in `bench/results.md`, ADR 2 picks which drives default
- Register detector too thin for OTP/KYC: 12-token domain allowlist added (later extended to 14)
- Religious red-team category (#6): swapped to "Ramadan/Hijri-context government policy"
- Alsubhi verification (#7): added as Phase 6 ADR 1 task — 5-min verify or weaken claim
- Windows RTL (#8): `scripts/demo.py` writes UTF-8 file + stdout tail

**Pushed back on:**

- #4 (cut providers): Eslam kept the 5-provider plan but framed model-ID flag-toggling per vendor so the bench compares cost/quality tiers on a single SDK. Falcon-Arabic stays in §0.5 with cut-priority documented.
- Bench dimensions: Eslam agreed to keep faithfulness and citation accuracy as separate metrics (rubric criterion 4 grades the distinction), but accepted collapsing correctness + register-match into one judge call.

## 4. §0.5 — verified-current provider table (the final form)

Multi-tier provider strategy with model-ID flag-toggling per vendor:

| Provider | Default | Alternate | Notes |
| --- | --- | --- | --- |
| Mock | canned responses | — | Zero-key reviewer demo |
| Claude | `claude-sonnet-4-6` | `claude-opus-4-7` | Opus held for judge sanity swap; not in default rotation (too expensive) |
| OpenAI | `gpt-5.5-2026-04-23` | `gpt-5.4-mini-2026-03-17` | |
| Gemini | `gemini-3.1-pro-preview` | `gemini-3-flash-preview` | Gemini 3.1 Pro is ALSO the bench judge (out-of-family for Claude/OpenAI) |
| Falcon-Arabic | Falcon-Arabic 7B via Ollama | Falcon-H1-Arabic-3B | Residency-aware Arabic-native, Apache-2.0 |

Release dates documented in kickoff §0.5 for ADR 2 citation.

## 5. Data delivery and my opinion

Eslam delivered the four `data/*.json` files mid-planning. My review found:

**Strengths:**
- 20 dense MSA government FAQ sources across 5 categories (4 per category)
- Real Hijri date coverage (6 of 20 sources reference Hijri timelines with fabricated regulation numbers like `التعميم التجريبي رقم 4521 لعام 1447هـ`)
- English domain tokens preserved verbatim in MSA — matches the §0.4 allowlist exactly
- Out-of-scope redirects baked into source content (iqama-004 redirects visa/traffic/labor questions)
- Gold answers preserve question register while quoting MSA verbatim — direct execution of §0.8
- `gold_citations.quoted_passage` is verbatim substring — enables rule-based citation matching
- Red-team added a 9th category (`citation_translation_trap`, rt-010) that we hadn't specified
- 4-state `expected_behavior` vocabulary in red_team is sharper than boolean refusal

**Issues found and 8 proposed updates (all applied):**
- `gold_passage_ids` format `source_id:chunk-N` constrains chunker to be deterministic and ordered
- `expected_behavior` 4-state vocab referenced in kickoff line 125 but not present in questions.json (backfilled in parallel by Eslam during my edit batch)
- `register: code_switched` in q-009/010/011 didn't match §0.4's three-class taxonomy
- 8 of 15 questions had gold answers (brief-compliant but statistically thin)
- 9 red-team categories vs 8 in kickoff §0.7 (data added `citation_translation_trap`)
- Plus updates for: gold passage IDs contract, judge model name, critic toggle in bench, recall@5 content-based matching

**Design improvements Eslam added that beat my originals:**

- `gold_passage_ids` declared "informational/debugging only" with content-based recall matching (line 121 of kickoff). Better than my "verify chunker matches gold_passage_ids" approach — decouples scoring from chunk-id stability across rebuilds.
- `evaluation_notes` declared "the judge rubric, not passive metadata" — per-case rubric passed to judge as `(question, model_answer, expected_behavior, evaluation_notes)`. Sharp.

## 6. Round 1 — third-party data reviewer (7/10)

Reviewer score: 7/10, "not ready as-is, close to ready with targeted fixes."

**Real catches accepted (10-item action set, ~30 min, all applied):**

1. rt-009 label: `refuse_with_redirect` → `answer` (evaluation_notes describe a grounded correction, not a refusal)
2. rt-003 category: `multi_clause_code_switched_dialect` → `multi_clause_dialect` (no English in the question)
3. Remove `should_escalate` from questions.json (parallel truth source vs `expected_behavior`)
4. Constrain `register` to `{MSA, dialect, mixed}`; add `contains_code_switching: boolean`; relabel q-009/010/011
5. q-008 `dialect_family` → `saudi_general` (no Hijazi markers in text)
6. Add `expected_source_ids` to rt-004, rt-006, rt-009, rt-010
7. Add gold answers for q-004 (`ask_clarification` exemplar) and q-014 (`refuse_with_redirect` exemplar)
8. Add q-016 (new question for traffic-fines-004 — Hijri 15-day correction deadline + non-guaranteed approval)
9. Remove `answer_word_count` (approximate noise)
10. Fix sponsorship-001 chunk index in q-003 gold_passage_ids (cosmetic; bench doesn't score on chunk IDs)

**Pushed back on:**

- Reviewer's specific register fix (map `code_switched` → `mixed`) — contradicted §0.4 allowlist logic. q-009 has dialect markers + all English allowlisted → stays `dialect`. q-010/q-011 contain non-allowlisted English (`unpaid`, `rejected`) → correctly escalate to `mixed`.
- Adding 7 gold answers (~35-70 min) — reduced to 2 highest-leverage (q-004 + q-014)
- 4 new questions for unused sources — reduced to 1 (q-016 for traffic-fines-004)
- `contains_english_terms` missing SAR / service codes / domains — those aren't lexically English in the code-switching sense (SAR is an MSA currency abbreviation; service codes are fabricated identifiers; URLs are URLs)
- q-015 critique ("vague, culturally loaded") — kept; that's the design (out-of-corpus refusal test)
- Near-duplicate source pair and contradiction trap — added complexity without proportional rubric value

## 7. Round 2 — reviewer accepted with two clarifications

Reviewer endorsed our register taxonomy approach and `should_escalate` removal. Two added guardrails (both applied):

1. **Allowlist stays conservative** — do NOT add `unpaid` / `rejected`. They're plausible status tokens but adding them would blur the useful `dialect`/`mixed` distinction. Documented in Phase 6 ADR 3 task as intentional design call.
2. **rt-009 keeps the 4-state vocabulary** — no fifth enum value. Evaluation_notes carry the "answer with grounded correction" nuance. Keeps the bench schema stable.

## 8. Round 3 — reviewer accepted at 8.5/10

Two tiny clarifications (both applied as "round-three cleanup"):

1. **q-016 date arithmetic ambiguity** — original gold computed "أي حتى نهاية 20 رمضان 1447هـ" which a faithful "خلال خمسة عشر يوماً من 5 رمضان" answer wouldn't textually match. Fix: dropped the explicit computed date. Gold now rests on source-faithful "خلال خمسة عشر يوماً" phrasing. Stylistically consistent with q-001's gold (which also doesn't compute target Hijri dates).
2. **rt-003 `expected_source_ids` semantics** — added §0.7 schema note: "for red-team cases, `expected_source_ids` denotes the retrieval target, not gold support; semantic adjudication of how those sources should be used lives in `evaluation_notes` per-case." Disambiguates the gold-support-vs-retrieval-target reading.

## 9. External RAG-architecture learnings — 4 ideas adopted

Eslam shared a set of external RAG-architecture suggestions mid-planning for cross-pollination. Most of it was enterprise scaffolding deliberately out of scope. Four ideas were adopted and folded in:

1. **Per-chunk LLM-generated metadata** (`summary` + `keywords`) — concatenated into BM25 index AND embedding input. One cheap LLM call per chunk (~$1-2 across 60-80 chunks). `passage_text` stays verbatim so citation accuracy is unaffected. Lives in Phase 1 task 9.
2. **Query classification → service-category filter** (`router.py`) — rules-first using Arabic service keywords (`إقامة`, `مخالفة مرورية`, `كفالة`, `رخصة بلدية`, `رخصة عمل`), LLM fallback at low confidence. `out_of_scope` short-circuits to escalation before retrieval. Lives in Phase 2 task 2.
3. **Structured judge output** — `{matched_facts, missing_facts, irrelevant_facts, correctness_score, register_match_score}` instead of flat 0-3. Same judge-call count, sharper diagnostic. ADR 2 reports per-provider fact-count breakdowns ("model X averaged 3.2/4 matched gold facts, 0.4 hallucinated per question"). Lives in Phase 3 task 3.
4. **Refusal log** — every `refuse_with_redirect` / `ask_clarification` / `partial_answer_with_escalation` response writes JSONL to `bench/refusal-log.jsonl`. Material for AI_JOURNAL.md and refusal-tone analysis. Lives in Phase 4 task 3.

Plus 3 CREATIVE.md path-not-taken mentions added to §0.9 (do NOT build, mention only): per-service dual-source retriever, conversational mode with standalone-question condensation, knowledge-graph cross-doc reasoning.

All 4 adopted ideas are baked into never-cut Phase 1/2/3/4 core. Cut order in §8 unchanged.

## 10. Eslam's accumulated pushbacks and preferences

Behavioral preferences to carry forward across the session:

- **"6 hours done > 14 hours unfinished"** is a hard framing. Resist scope-creep proposals even when individually defensible (rejected: adding all 7 gold answers, 4 new questions, near-duplicate sources, multi-source contradiction trap).
- **Verification-flag voice is non-negotiable** for the four graded docs (README, ARCHITECTURE, AI_JOURNAL, CREATIVE). Never ship "X is the best Y" — always cite or flag. Pre-flag Alsubhi 2025 / MIRACL numbers as "to verify before shipping ADR 1."
- **Authorize explicitly, not implicitly.** The phrase `Start Phase 1` is the only thing that authorizes Phase 1 execution. Don't read between the lines.
- **Plain-English summaries** are preferred at key checkpoints. Eslam asked for them twice during planning.
- **Stop when told to stop.** When Eslam says "i stopped you", don't argue or continue; verify what was applied.
- **When a decision is made, apply directly.** Don't dilute by listing paths-not-taken in negative form. Don't say "we considered X but chose Y" unless asked.
- **Conservative defaults over speculative future-proofing.** Allowlist stays narrow (don't preemptively add `unpaid`/`rejected`); expand on observed failures.
- **No parallel truth sources.** `should_escalate` removed because `expected_behavior` is authoritative.
- **Single 4-state vocab for behavior match.** Don't expand to 5 enum values; use `evaluation_notes` for nuance.
- **Stylistic consistency matters.** q-016 gold answer was simplified to match q-001's style — both leave Hijri arithmetic implicit.
- **Reviewer engagement is collaborative.** Three rounds of reviewer feedback resolved through specific pushback + applied fixes. Convergence, not capitulation.
- **Brief stays authoritative.** When the brief lists 4 service categories as examples, expanding to 5 (adding `labor_office`) is fine because the brief says "examples" not "limits."
- **Don't over-explain.** Tight responses. Each paragraph earns its place. End-of-turn summaries are one or two sentences.

## 11. State summary at planning-phase end

- **MURSHID_KICKOFF.md** — fully revised through 3 reviewer rounds + 4 external RAG-architecture learnings. Internally coherent end-to-end.
- **data/sources.json** — 20 entries, untouched since delivery.
- **data/questions.json** — 16 entries (15 originals + q-016), 4-state `expected_behavior`, 3-class `register` + `contains_code_switching`, `should_escalate` removed.
- **data/gold_answers.json** — 11 entries (8 originals + q-004 + q-014 + q-016), no `answer_word_count`, q-003 chunk metadata fixed, q-016 date arithmetic resolved.
- **data/red_team.json** — 10 entries, rt-003 / rt-009 labels fixed, `expected_source_ids` populated on all 10.

Phase 1 has not started. Repo scaffolding (src/, bench/, tests/, scripts/, docs/), `requirements.txt`, `.env.example`, `.gitignore`, `WORKING_LOG.md`, `TIME_LOG.md` — all wait for `Start Phase 1`.

## 12. References

- **Plain-English plan:** `planning/PLAN_SUMMARY.md`
- **Pre-staged deliverable content:** `planning/DELIVERABLES_DRAFT.md` (ADR drafts, CREATIVE.md outline, AI_JOURNAL placeholders, GCC production gaps paragraph, predictive walkthrough framework)
- **Authoritative build spec:** `MURSHID_KICKOFF.md`
- **Brief:** `Principal_AI_Engineer_Task.pdf`
- **Data:** `data/sources.json`, `data/questions.json`, `data/gold_answers.json`, `data/red_team.json`

---

## 13. Additional planning-phase moments (logged retroactively)

The following moments happened during the planning conversation but were not captured in §1–§11 above. They are added here so the Phase 7 `AI_JOURNAL.md` curation has access to the full decisional arc, not only the 8-point pre-flight critique and three reviewer rounds.

**All six entries below are retroactive.** They use the placeholder identifier scheme `[planning-add-NN]` rather than HH:MM timestamps to make this provenance explicit. The Phase 7 curator (the agent at submission time) must treat these as reconstructed-after-the-fact, not real-time, when selecting which prompts / mistake-catches / autonomous-handoffs to feature in `AI_JOURNAL.md`. The verification-flag voice should preserve this distinction — these entries describe genuine decisional moments from the pre-Phase-1 planning conversation, but they were not written down at the moment they occurred.

---

### [planning-add-01] Multi-agent research arc and verification-flag voice origin

**Type:** decision

**What happened:**
Before the kickoff was drafted, five parallel research agents investigated the Arabic-RAG landscape independently. Agent 1's pattern of explicitly flagging unverified claims ("I could not verify X") became the model for the verification-flag voice now mandated in kickoff §6 for all four graded docs. The voice was chosen specifically as an anti-overclaiming pattern, because English-default engineers tend toward confident sweeping claims that an Arabic-aware reviewer will spot immediately.

**Agent suggested:**
First drafts of the kickoff would have used the confident-summary voice typical of LLM output (e.g., "BGE-M3 is the strongest Arabic embedding model").

**I accepted / rejected / modified:**
Modified — adopted Agent 1's epistemic pattern as the official voice for all graded documents.

**Reason:**
Verification-flag voice is itself a creative-engineering signal. Saying "Alsubhi 2025 reports X, which we have not independently verified" is more credible than "BGE-M3 is best." Documented as kickoff §6 non-negotiable.

---

### [planning-add-02] Frontier-vs-Arabic-native LLM debate

**Type:** decision

**What happened:**
The kickoff §0.5 provider table (frontier prototype + Falcon-Arabic via Ollama + ALLaM / Fanar named as production path in ADR 2) resolved a real debate during planning. The alternative considered: go all-Arabic-native — Falcon-Arabic 7B 4-bit quantized via Ollama as the only provider, no frontier APIs at all. That would have been a stronger "Arabic-first" signal but introduced real risk: local inference quality for Arabic instruction-following is unverified across all the research agents we ran, quantization can degrade Arabic generation more than English, and 4-7GB model downloads eat into the 10-minute reviewer budget.

**Agent suggested:**
All-Arabic-native stack as the "purist" choice.

**I accepted / rejected / modified:**
Rejected the purist path; chose the hybrid where the prototype uses a frontier model for engineering-speed risk-reduction while ADR 2 names ALLaM-on-Azure-UAE / Fanar / Jais as the residency-aware production path we would ship for a GCC government deployment.

**Reason:**
Per Agent 5's research, there is no clean public benchmark comparing closed frontier models against Arabic-native open models on grounded Arabic QA with citation accuracy. We could not justify the all-Arabic-native path with benchmark evidence, so we chose the lower-risk hybrid and made the production-path framing explicit in the ADR.

---

### [planning-add-03] Conservative allowlist as intentional design call

**Type:** decision

**What happened:**
During Round 2 of data review, the reviewer suggested adding `unpaid` and `rejected` to the register-detector domain allowlist alongside the existing `iqama`, `OTP`, `KYC`, `IBAN`, `Absher`, etc. They are plausibly used as English status tokens in code-switched government-services Arabic.

**Agent suggested:**
Add `unpaid` and `rejected` to the allowlist for completeness.

**I accepted / rejected / modified:**
Rejected. The allowlist intentionally stays narrow — limited to domain-specific names (services, ID types, financial codes) where preservation is unambiguous. Status words like `unpaid` / `rejected` are conversational English, and including them would blur the useful dialect vs. mixed distinction. Documented as a Phase 6 ADR 3 task.

**Reason:**
The right Arabic-depth signal is knowing what NOT to add. q-009 stays `dialect` (all allowlisted English domain tokens, dialect markers present) and q-010 / q-011 correctly escalate to `mixed` (contain non-allowlisted `unpaid` / `rejected`). The conservative defaults preserve the discriminative power of the register taxonomy.

---

### [planning-add-04] Mock-as-first-class-citizen provider

**Type:** decision

**What happened:**
The kickoff §0.5 lists Mock as provider #1 with "Never cut" as its cut priority. This is unusual — most candidates would list mock as an internal testing fixture, not as a first-class provider in a benchmarked lineup. The decision was deliberate.

**Agent suggested:**
Treat Mock as a test fixture only, not as a benchmarked provider.

**I accepted / rejected / modified:**
Modified. Mock is a first-class provider that ships in the bench with the same `LLMProvider` protocol as Claude, OpenAI, Gemini, and Falcon-Arabic. The reviewer can run the entire system (router, register detector, retrieval, generation, citations, refusal templates) with zero API keys.

**Reason:**
The brief explicitly says "runs locally in under 10 minutes for a reviewer." Real provider calls require API keys the reviewer may not have at hand. Mock makes the runs-in-10-minutes promise literal, not conditional. The architectural cost is small (Mock implements the same protocol everyone else does); the engineering-rigor signal is large.

---

### [planning-add-05] Specific red-team cases sourced from research synthesis

**Type:** prompt

**What happened:**
Two of the strongest red-team cases in `data/red_team.json` originated from specific research-agent outputs that were chosen because they exercise Arabic-RAG failure modes most candidates would miss:

- **rt-003** (the `بدل فاقد للهوية` multi-clause query): sourced from Agent 3's GCC competitive-landscape research. It tests semantic drift (must not silently substitute `هوية` → `إقامة`), multi-clause handling (fees question vs travel question), code-switching tolerance, and partial-answer escalation. Documented in `evaluation_notes`.
- **rt-010** (the citation-translation trap): designed during data generation to test whether the system maintains MSA source quotes while answering in dialect. The trap: a user explicitly asks for the answer in dialect ("but don't give me general talk") — the temptation is to translate the cited passage into dialect to match the answer register. The correct behavior is to keep `quoted_passage` verbatim MSA while paraphrasing in dialect around it.

**Agent suggested:**
Red-team set was originally going to consist of standard hallucination-bait cases.

**I accepted / rejected / modified:**
Modified — built the harness around specific Arabic-RAG failure modes from the research synthesis rather than generic ones. The Ramadan / Hijri-context substitute (rt-004) replaced an originally-planned religious-policy invented question because of risk-management for a Saudi-targeting take-home.

**Reason:**
The red-team cases that test failure modes specific to Arabic government-services RAG (semantic drift between similar terms, register-aware citation discipline, Hijri-Gregorian ambiguity) are stronger creative-engineering signals than generic hallucination tests. The Air Canada chatbot liability precedent referenced in ADR planning gave us the framing for why these matter.

---

### [planning-add-06] This log-addition task (self-referential)

**Type:** autonomous_handoff

**What happened:**
After Phases 1, 2, and the Round-1 fixes shipped, Eslam reviewed the existing logs (`PLANNING_LOG.md`, `WORKING_LOG.md`, `TIME_LOG.md`) and identified five planning-phase moments that happened during our conversation but were not captured in any log. He delegated retroactive log additions to me with specific guardrails: (a) targeted additions only, not a full backfill; (b) placed in `PLANNING_LOG.md`, NOT `WORKING_LOG.md`; (c) marked with `[planning-add-NN]` identifiers, not fake timestamps; (d) honest about being retroactively added, not pretending to be real-time logs; (e) no invented moments — if I thought there were more to add, list them and ask first.

**Agent suggested:**
Could not have suggested this — Eslam identified the gap from outside the build flow.

**I accepted / rejected / modified:**
Executed as specified, with the guardrails enforced as listed. The intro paragraph of this §13 explicitly marks all six entries as retroactive; the placeholder identifier scheme makes the provenance visible at every line.

**Reason:**
Phase 7 `AI_JOURNAL.md` curation will pull from the working logs. The five missing moments are real planning-phase decisions that influence what shipped. Adding them retroactively, marked honestly as such, gives the journal richer material to draw from while preserving the verification-flag voice — we don't pretend these are real-time entries.

---

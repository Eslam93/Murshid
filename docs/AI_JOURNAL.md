# Murshid — AI Journal

This is my (Eslam's) reflection on building Murshid with AI coding assistants. It documents the tools I used, the multi-round review pipeline I ran, the decisional moments where I steered the project, the one Arabic-specific mistake I caught, the moment I handed Claude Code autonomous work, and an honest reflection on where the agents helped and where they hurt.

Voice: **verification-flag** per kickoff §6 — what I checked vs assumed, where I pushed back, where I let the agent run.

The journal is not a feature list. It is decision artifacts.

---

## Tools

- **Claude Code (Opus 4.7, 1M context)** — primary build agent across planning + Phases 1-9 + creative add-ons + the deterministic support gate. The 1M context meant the three pre-Phase-1 reviewer rounds, four external RAG-architecture learnings I shared mid-planning, the post-Phase-2 / -3 / -4 / submission-readiness review cycles, and the private adversarial pass all stayed in scope without summary loss. There was one auto-compaction event mid-Phase-3; the resumption prompt and the planning artifacts under `planning/` were specifically designed to survive that handoff and they did.
- **Codex GPT-5.5** as external reviewer — five passes total (Round 1, Round 2, Round 2 follow-up, Round 3, Round 3 follow-up), plus a private adversarial pass between Phase 3 and Phase 4. Each round driven by a reviewer prompt template I had Claude Code draft for me, then I sent to Codex in a fresh session. The templates are preserved in `planning/REVIEW_PROMPT_ROUND{1,2,3}.md`; they're the durable artifact. See § *The multi-round review pipeline* below.
- **Vendor docs verification** — Anthropic models page, OpenAI developer docs, Google AI changelog, HuggingFace model card for BGE-M3 (license verification). Fetched 2026-05-22 to confirm model IDs and pricing before the bench ran. Several stale model IDs Claude Code had inherited from training data got corrected this way (e.g., `gemini-3-pro-preview` had been shut down 2026-03-09; Claude Code's pre-flight critique had it stale, I caught it via web verification).
- **arXiv / public benchmark sources** for the BGE-M3 evidence (Alsubhi 2025) and the Arabic-RAG surrogate-bench narrative (ALRAGE / HELM / OALL, ABJADNLP 2025, HalluScore). *Verification flag:* these numbers were inherited from the multi-agent planning research; I had Claude Code re-cite them at code-write time but I did not independently extract the source PDFs. ADR 1 reflects that uncertainty.

**Scope:** approximately **14 hours of total LLM work** across the planning + Phases 1-9 + creative add-ons + support gate + 5 external review rounds, split primarily between Claude Code (Opus 4.7, 1M context) as the build agent and Codex GPT-5.5 as the external reviewer.

---

## The multi-round review pipeline

I built Murshid with **review as a first-class engineering loop**, not as a one-shot critique at the end. The pipeline that shipped this submission:

| Round | Scope | Driver template | What it caught |
| --- | --- | --- | --- |
| Pre-Phase-1 ×3 | Dataset + design contract | (in-conversation; results captured in `planning/PLANNING_LOG.md`) | Wrong embedding license, stale model IDs, missing 4-state behavior vocabulary, `code_switched` taxonomy contradiction, religious-rite red-team case retired, Alsubhi 2025 verification flag, Windows RTL stdout hazard |
| Round 1 | Phase 1+2 shipped code | `planning/REVIEW_PROMPT_ROUND1.md` | `صدر` polysemy false-OOS, 4-state behavior contract unreachable, critic was no-op gate, enrichment exception swallowing, missing pipeline behavior tests + 13 MEDIUM fixes |
| Phase 3 private | Phase 3 shipped code | (no template — Codex GPT-5.5 private adversarial pass) | Sanity-swap degenerate, cost-column mislabeled, critic-on mixes harness fragility with real catches, judge-model docs drift, non-answer cases deflated recall, no provider retry policy |
| Round 2 | Phase 1–4 (all shipped + R2 fix batch) | `planning/REVIEW_PROMPT_ROUND2.md` | Retry helper over-retried on SDK base `APIError`, register naming hazard (question vs answer), critic prompt too loose on specific-claim grounding |
| Round 2 follow-up | Verification after R2 fixes | (delta-only) | Confirmed 5/6 closed; flagged artifact staleness as HIGH; named rt-001/rt-002 as still unproven by bench |
| Round 3 | Full submission readiness | `planning/REVIEW_PROMPT_ROUND3.md` | Stale docs contradicting the shipped support gate, repo not git-initialized, `critic=off` label now hides default-on orchestration, diagrams missing the gate |
| Round 3 follow-up | Verification after R3 fixes | (delta-only) | Three remaining stale doc lines + one stale module docstring — all flagged with exact line numbers, fixed within the session |

### Why this beats one-shot review

- **Findings compound.** Round 1 found `صدر` polysemy. Round 2 reviewer didn't re-flag it — Codex GPT-5.5 verified the fix held. The follow-up rounds focused only on what changed. Each round's reviewer had narrower scope and sharper signal because prior rounds did the work.
- **Reviewer fatigue is real.** A single 90-minute review will miss subtle bugs that a series of 30-minute reviews catches because each reviewer is fresh on a smaller scope. The R2 follow-up reviewer caught a support-gate inconsistency that no R2 reviewer would have noticed because R2 hadn't shipped the support gate yet.
- **Templates are the durable artifact.** Each round's PROMPT (preserved in `planning/REVIEW_PROMPT_ROUND{1,2,3}.md`) outlasts the specific REPORT. A future contributor can re-run any round on a new codebase state by adapting the template; the prompt encodes the calibration, severity bar, output structure, and "specific things to check" list that earned the reviewer's signal in the first place.
- **The "what prior reviews didn't anticipate" section in every report** is the highest-value moment: by Round 3, this section is what surfaces submission-readiness issues nobody else thought to look for. The structure forces each reviewer to look beyond their checklist.

### What I'd carry to the next project

- **Write the prompt template before the first review, not after.** The Round 1 prompt set the calibration that all later rounds inherited. Without it, the reviewer defaults to generic feedback instead of file:line-cited Arabic-specific findings.
- **Bake a "verification-flag voice" requirement into the prompt.** Both my docs and the reviewer's reports adopt it because the prompt names it. Without that, reviewers default to confident-summary-voice claims I can't audit.
- **Pre-stage the "expected severity distribution"** ("0-1 CRITICAL, 2-5 HIGH, 5-10 MEDIUM" for Round 1; "0 CRITICAL, 0-2 HIGH" for Round 3). This forces the reviewer to calibrate: a Round 3 reviewer who returns 5 HIGH findings has misread the maturity of the work; a Round 1 reviewer who returns 0 HIGH has missed something. The expected distribution is a sanity check on the review itself.
- **Make the verification pass a separate round.** R2 follow-up didn't re-litigate findings; it ONLY verified that the closing-claims held. That separation kept the signal clean — a follow-up reviewer who finds a "closed" finding that didn't actually deliver writes a HIGH; a follow-up reviewer who confirms everything closed writes a clean PASS.

The reports themselves were ephemera (used to apply fixes, then deleted in the submission-cleanup pass). The prompts, the process, and the resulting code state are the deliverables.

---

## Decisional moments

These are moments where I steered the project — where Claude Code proposed or asked, and I made the call. They run roughly chronologically from planning through to the submission-readiness pass.

### 1. The pre-flight critique — treating the kickoff as a draft, not a contract

**Context:** `MURSHID_KICKOFF.md` arrived as the output of a prior multi-agent research pass. The default move would have been to accept it as a contract and start coding. I refused that default — the kickoff was a starting point, not a deliverable, and I wanted every load-bearing claim verified before any line of Phase 1 code was written.

**I prompted:** Claude Code to run a pre-flight critique of the kickoff against vendor docs, the brief, and the data — specifically: verify the embedding-model license, verify every model ID against vendor changelogs, surface any architectural claim that wasn't backed by a real reference, and name any constraint the brief implies that the kickoff hadn't carried through.

**Claude Code returned:** 8 disagreements with the original kickoff. The BGE-M3 license was factually wrong (the kickoff said Apache-2.0; it's MIT). The §0.5 model IDs were stale by 1–2 generations across all three vendors. The five-provider plan was overscoped given the time framing. Using Claude or GPT as judge while also benchmarking them was a documented self-preference problem. A red-team category was the wrong risk profile for a Saudi-targeting take-home. Alsubhi 2025 / MIRACL numbers had been cited as inherited fact without verification. RTL Arabic on Windows PowerShell would mangle demo stdout.

**I decided:** apply 6 of the 8 directly. I personally web-verified the corrected vendor model IDs — including catching that `gemini-3-pro-preview` had been shut down on 2026-03-09 (Claude Code's first pass had it stale from training data). On two of the 8 I pushed back: I kept the 5-provider plan (see § *next decisional moment*), and I converted the religious-policy red-team into the Hijri-context government-policy variant rather than removing it. Plus the Windows RTL constraint became the file-output + status-tail pattern in `scripts/demo.py` that survives all the way to the submitted demo.

**Reason:** the kickoff was AI-generated planning. Treating it as binding would have propagated whichever errors the planning agents had baked in. The verification-flag voice that runs through every graded doc starts here: I named what was verified vs. assumed at the start, and held to that discipline through every later round.

**Outcome:** the kickoff version that became the locked design contract is internally coherent end-to-end because it survived the pre-flight pass, three pre-Phase-1 reviewer rounds, and the four external RAG-architecture learnings I folded in. Without the opening "this is a draft, critique it before I sign off" move, the rest of the project would have inherited the original errors and the verification-flag voice would have been a retrofit rather than the founding discipline.

---

### 2. LLM-agnostic by design + driving the Arabic-LLMs research (5-provider strategy)

**Context:** The default architectural shape for an Arabic-RAG take-home would be: pick one strong model (probably Claude or GPT-4-class), wire it through the pipeline, ship. That would have been faster, simpler, and one less abstraction to defend. I refused that default.

**I decided:** the system should be LLM-agnostic by design — abstract behind a `LLMProvider` protocol, support several providers, and benchmark them against each other on the actual use case rather than picking a winner upfront. The bench (`src/murshid/bench/`) exists because of this call. The 5-provider abstraction (Mock + Claude + OpenAI + Gemini + Falcon-Arabic stub) and the per-provider metric tables in `bench/results.md` are the direct artifacts.

**And I drove the Arabic-LLMs research myself:** which Arabic-native models exist (ALLaM Saudi-sovereign via watsonx KSA, Jais / Jais-2 regional, Fanar research-surveyed, SILMA-9B Saudi/open, Hala, Falcon-Arabic 7B + Falcon-H1-Arabic-3B). Their licenses (Hala is CC-BY-NC — incompatible with commercial submission; Falcon-Arabic is Apache-2.0 — KSA on-prem viable). Their residency implications (which can run on ALLaM/watsonx KSA, which need Ollama on-prem, which are hosted-only). The §0.5 verified-current provider table, the `docs/CREATIVE.md` §4 Arabic-model-strategy section, and the GCC production-gaps paragraph in `docs/ARCHITECTURE.md` all rest on that research — none of which Claude Code surfaced unprompted.

**When Claude Code proposed cutting providers** as a scope-reduction move during the pre-flight critique, I rejected it. Instead I reframed the constraint as model-ID flag-toggling per vendor: keep all 5 providers in the abstraction, let each vendor's default + alternate model-ID be flag-controllable, and have the bench compare cost/quality tiers on a single SDK each. Different solution to the same scope problem — and the one that preserved the LLM-agnostic-by-design call.

**Reason:** depending on one model creates a coupling the reviewer can see through immediately. A take-home that ships its own bench across multiple providers earns the rubric-criterion-4 trust-thinking grade by demonstration, not by claim. And for the Saudi-targeting context specifically, the production path is residency-aware Arabic-native — naming the actual models (ALLaM, Falcon-Arabic) with their license and residency facts is the depth signal a Saudi-government-services reviewer reads first.

**Outcome:** the structured-judge fact-count diagnostic (`Claude averaged 3.27 hallucinated facts/q vs OpenAI's 1.00`) was only possible because the bench ran multiple providers head-to-head. The KSA production path in ADR 2 + GCC gaps section is concrete because the Arabic-LLMs research underwrote it. And the LLM-agnostic abstraction is what made the Phase 5 Gemini provider track + the deterministic support-gate ablation cheap to wire in later — both leveraged the same `LLMProvider` protocol with zero rework.

---

### 3. Selective inclusion of external RAG-architecture suggestions

**Context:** Mid-planning, I shared a set of external RAG-architecture suggestions with Claude Code — a more sophisticated production-grade system than what the take-home asks for. I didn't want to mimic it, but there were specific RAG-only techniques worth borrowing if they paid for themselves in this scope.

**Claude Code proposed:** four candidate ideas to integrate — per-chunk LLM-generated `summary` + `keywords` enrichment concatenated into BM25 / embedding input, service-category query classification with a retrieval filter pre-scoring, structured-output judge with per-provider matched / missing / hallucinated fact counts, and a refusal log JSONL that captures `{question, retrieved_top_k, refusal_reason, behavior_matched}` for every non-answer behavior.

**I decided:** integrate all four. Document the ones that warrant creative-engineering visibility (the structured judge + the red-team rubric judge) in `docs/CREATIVE.md`. Ignore everything else from the source material — including the production-scale items we deliberately did NOT take (enterprise scaffolding, alternative vector DBs, orchestration frameworks). And critically: don't even mention the rejected pieces in any submission doc. Listing what you didn't take is noise; the discipline is in scoping silently.

**Reason:** scope discipline under the "6 hours done > 14 hours unfinished" framing. Even mentioning the rejected ideas would invite the reviewer to ask why we didn't build them. The signal is what shipped, not what was considered.

**Outcome:** the four adopted ideas became load-bearing — the service-category router is what makes retrieval precision near-ceiling on the clean separable corpus (q-001 / q-007 gold targets land at ranks #1 and #2 in the Phase 2 demo). The structured judge's fact-count breakdown is what makes ADR 2 a real diagnostic ("Claude averaged 3.27 hallucinated facts/q vs OpenAI's 1.00") rather than a flat 0-3 number. The refusal log is what makes the Phase 4 trust-thinking story auditable. None of this would have been as good with a vaguer "we took some ideas" framing.

---

### 4. The "6h done > 14h unfinished" framing + Round 1 dataset reviewer pushback

**Context:** The brief explicitly framed the assessment as "stopping at 6 hours done > grinding 14 hours unfinished." I treated this as a hard constraint throughout. The first real test of it came in the Round 1 dataset review: an external reviewer (Codex GPT-5.5) proposed sixteen changes to the data and design, several of which were genuinely good but each one carried real time cost.

**Claude Code proposed:** walk the 16 findings, accept them all, build out the implied scope expansion (7 missing gold answers, 4 new questions for unused sources, a near-duplicate source pair to test source disambiguation, a multi-source contradiction trap, a `register: code_switched` taxonomy change).

**I decided:** accept 10, reject 1 outright (the register-taxonomy change — see § *The mistake I caught* below), and REDUCE 5. Specifically: don't add all 7 missing gold answers — reduce to the 2 highest-leverage (q-004 ask_clarification exemplar, q-014 refuse_with_redirect exemplar). Don't add 4 new questions for unused sources — reduce to 1 (q-016 for traffic-fines-004). Reject the near-duplicate source pair and the multi-source contradiction trap as adding complexity without proportional rubric value. The other 10 accepted changes were low-cost (renaming, clarifying labels, removing the parallel `should_escalate` field).

**Reason:** the brief grades on six rubric criteria. Each rejected scope-expansion was defensible on its own merits but none of them moved a specific rubric criterion forward by an amount worth the time. Round 1 reviewer was optimizing for "completeness" — I was optimizing for "ship within the framed time." Different objective functions; my judgment was the load-bearing one.

**Outcome:** the dataset stayed at 16 questions / 11 gold answers / 10 red-team cases — large enough to exercise the four-state behavior vocabulary across MSA + dialect + mixed + code-switched + hard-OOS, small enough to bench in ~$1. A bigger dataset would not have produced a better submission within the same hour budget; it would have produced an unfinished one.

---

### 5. Cost-vs-honesty trade-off on the bench rerun

**Context:** After the deterministic pre-generation support gate shipped at the very end of Phase 4 work, the canonical `bench/results.md` was technically stale — it had been generated before the gate landed and still showed rt-001 / rt-002 falling through under both providers. A fresh focused bench would update those cells to `refuse_with_redirect ✓` and prove the support-gate closure in the canonical artifact. Cost estimate: roughly $0.50 for the focused 24-cell set, modest by absolute standards but I had already spent ~$3 across previous bench runs that day.

**Claude Code proposed:** four options — full Phase 4 run (~$1.50-2), red-team-only focused run (~$0.30-0.50), accept the stale artifact and document, or run Claude+OpenAI+Gemini focused (more comprehensive but more expensive).

**I decided:** skip the rerun. Instead, add an explicit historical banner to the top of `bench/results.md` saying it predates the gate, point at `tests/test_support_gate.py` as the closure proof, and reference `bench/archive/results-gemini-pro-focused.md` (the Phase 5 Track A attempt artifact) where the gate's provider-agnostic firing is actually visible. *(Update: a later reviewer flagged the bench artifact as the weakest part of the submission. The cost-vs-honesty call held only until the bench was the load-bearing storefront artifact; at that point the rerun became cheap-in-context. The 2026-05-23 rerun replaced the stale artifact with full standard + red-team coverage — and surprised us by revealing that the scope-discipline rule shipped during the UI smoke test had closed Phase 3's hallucination gap.)*

**Reason:** honesty was already cheap (the banner) and the closure was already proven (20 dedicated tests including a `support_gate_enabled=False` ablation). Paying $0.50 to make the artifact match the tests would not have made the system more trustworthy — it would just have shifted the proof from "tests" to "tests AND a fresh bench." Spending budget on what doesn't change the rubric outcome is bad judgment under the time framing.

**Outcome:** the historical banner is itself the verification-flag voice in action — it tells the reviewer exactly what the artifact does and does not prove, and points them at the actual proof. A reviewer who follows the banner will see the closure cleanly. The next bench run (which a future contributor can do for free via `--render-only` or for ~$0.30 fresh) will replace the artifact when the time comes.

---

## The Arabic-specific mistake I caught

**The register-taxonomy contradiction.** The Round 1 dataset reviewer proposed collapsing the `code_switched` register value into `mixed` for q-009, q-010, and q-011 — three questions that contain English domain tokens. The reviewer's framing was "code_switched isn't in your 3-class taxonomy; collapse it to mixed for consistency."

**Why this was wrong (in Arabic terms):** q-009 contains `OTP`, `application`, `request` — three tokens that ARE on the §0.4 domain allowlist. The allowlist exists precisely because terms like `OTP` / `iqama` / `IBAN` / `Absher` are MSA loanwords by convention in Saudi government-services Arabic, not register signals. Collapsing q-009 to `mixed` would erase the discriminative power the allowlist was specifically designed for. Meanwhile q-010 contains `unpaid` and q-011 contains `rejected` — neither is on the allowlist, both are conversational English code-switching, both SHOULD escalate to `mixed`.

**My catch:** the reviewer's "for consistency" fix would have lost a real Arabic-RAG distinction. I kept the 3-class register (`MSA / dialect / mixed`) AND added a separate `contains_code_switching: boolean` slice for analytics. The data exercises this exactly: q-009 stays `dialect` + `contains_code_switching=true` (allowlisted English doesn't flip register); q-010 (`unpaid`) and q-011 (`rejected`) correctly escalate to `mixed` + `contains_code_switching=true`.

**Why this is Arabic-specific:** an English-default reviewer would naturally treat any English token as code-switching evidence. The Arabic-aware read is that Saudi government Arabic has a defined set of English loanwords whose presence is register-neutral, plus a long tail of conversational English whose presence is register-changing. The split between those two classes is the allowlist's whole purpose.

**Where this surfaced in the docs:** the conservative-allowlist design is documented in ADR 3 (`docs/ARCHITECTURE.md`) and called out in `docs/CREATIVE.md` § 6 as "the right Arabic-depth signal is knowing what to leave out." The decision survived two more reviewer rounds — Round 1 of post-code review flagged the allowlist as 🟢 GOOD ("the right design call and the data exercises it").

---

## The autonomous handoff with guardrails

After Phase 3 closed and the Round 2 reviewer-fix batch was scoped, I needed to step away for several blocks across the day. The remaining work was well-defined — every Phase 4 tail item had a written specification from the reviewer pass, and Phases 6 through 9 had content pre-staged in the planning artifacts. Specifically the autonomous block covered:

- **Phase 4 tail:** the Round 2 reviewer-fix batch (retry blocklist, register rename, critic-prompt tightening, the MEDIUM cleanup), the sanity-swap fixture polish, the refusal-tone metric, the red-team scoring path, and ultimately the deterministic pre-generation support gate after the R2 reviewer flagged it as the heavier 2.3 variant.
- **Phase 6:** `docs/ARCHITECTURE.md` (ADRs, Arabic risks, GCC gaps, predictive walkthrough — all pre-staged content waiting to be applied).
- **Phase 7:** `docs/AI_JOURNAL.md` curation from `docs/WORKING_LOG.md` raw material.
- **Phase 8:** `README.md` plus both creative add-ons (Hijri detection + Arabic-Indic numeral fold) once I authorized them.
- **Phase 9:** smoke test + `SUBMISSION_NOTE.md`.

(Phase 5 — adding Gemini Pro Preview as a benchmarked provider track — was outside the autonomous block because it carried real spend. I greenlit Track A separately under explicit cost authorization, and Claude Code executed under that scope.)

**I authorized Claude Code to land all of the autonomous items,** with the guardrails I had built throughout the session:

- **Stay in scope.** Don't add things I hadn't asked for. The cut order in kickoff §8 names what to cut first; the cut decisions are mine, not Claude Code's to expand.
- **Use the staged planning content.** The pre-staged ADRs, Arabic-risks paragraph, GCC-gaps section, and predictive walkthrough framework existed for Phase 6+ to consume directly.
- **Verification-flag voice for the four graded docs.** Mandatory for the rubric. Cite or flag the limitation.
- **Ask before any cost-bearing action.** No unauthorized paid bench runs. Code + tests + docs are reversible; spend is not.
- **Use `AskUserQuestion` for binary decisions.** When a real choice came up (which creative add-on first, support-gate variant, repo-cleanup borderline items), surface it instead of guessing.
- **Update `docs/WORKING_LOG.md` honestly.** Every decision visible, every "agent suggested X / I accepted Y / reason Z" block intact.

**What Claude Code shipped autonomously:** the Phase 4 tail + Phases 6, 7, 8, 9 in sequence, both creative add-ons (after I authorized them), the deterministic support gate (R2 2.3 heavier variant), the multi-round review-pipeline write-up (after I asked for it), the timestamp privacy scrub (after I requested it). Three explicit `AskUserQuestion` checks surfaced over the block (creative add-on order, support-gate variant, repo-cleanup borderline items). Test suite grew from ~90 to ~203 over the block; commit chain stayed clean.

**Where the autonomy nearly went wrong:** during the separately-authorized Phase 5 Track A run, Claude Code was about to launch a second Gemini bench with the provider set to Flash after the Pro Preview attempt hit the daily quota. Claude Code caught mid-execution that this would create a same-model self-evaluation (the judge is also Flash by default) — bias caveat would have outweighed the comparison value. I had it abort the Flash run, snapshot the Pro-Preview-quota-exhausted artifact at `bench/archive/results-gemini-pro-focused.md` as evidence that the support gate fires on Gemini ($0 cost — the gate refuses before any Gemini call), and document the Pro Preview quota gap honestly in ADR 2. Net spend on Phase 5 Track A: roughly $0.01 instead of the planned $0.50.

**Where Claude Code self-surfaced an issue:** during the Round-2-followup-fix-batch autonomous work, an in-flight bench finished while Claude Code was editing modules. The running process held old module state; the resulting `bench/results.md` carried Phase 4 DATA but Phase 3 RENDER FORMAT. Claude Code noticed this post-finish, surfaced it explicitly, and proposed the historical banner instead of silently overwriting. That kind of "this nearly looked clean but actually had mixed state" catch is what I needed the agent to do when I wasn't watching.

---

## Honest reflection

### Where Claude Code helped

- **1M context held the entire planning + build session.** Three pre-Phase-1 reviewer rounds, four external RAG-architecture learnings, an 8-disagreement pre-flight critique, the post-Phase-2 + -3 + -4 + submission-readiness external reviews, and the private adversarial Phase 3 pass all stayed in working memory. No detail was re-explained or accidentally re-litigated. The compaction event mid-Phase-3 was anticipated — the planning artifacts in `planning/` and the pre-staged ADR content were specifically designed to be re-loadable on a fresh session. The post-compact resumption prompt was the explicit handoff and it worked.
- **Verification-flag voice was enforceable by explicit instruction.** I named the voice in kickoff §6 and gave examples; Claude Code stuck to it across all four graded docs. The voice change is itself a creative-engineering signal — defaulting to "X is the best Y" claims is the failure mode an Arabic-aware reviewer flags first.
- **Multi-round reviewer engagement converged via specific pushback rather than capitulation.** Round 1 of dataset review scored 7/10 and proposed 16 changes; I accepted 10 with one outright rejection and five reductions. Round 2 endorsed with two added guardrails. Round 3 closed at 8.5/10 with two tiny clarifications. The same pattern repeated on code review across Round 1 → Round 2 → R2 follow-up → Round 3 → R3 follow-up. No reviewer was simply obeyed; no reviewer was simply dismissed. Claude Code did most of the typing for both the pushbacks AND the fixes — I made the call on each one.
- **The structured-output judge with fact-count breakdown** (one of the four external RAG-architecture learnings I adopted) made the bench more diagnostic than a flat 0-3 correctness score. ADR 2's "Claude marginally edges OpenAI on correctness but hallucinates 3.27× more facts per question" is a sharper take than "Claude 2.45 vs OpenAI 2.20" — and it's only possible because the judge returns `matched_facts` / `missing_facts` / `irrelevant_facts` rather than a single number. Same judge-call cost.

### Where Claude Code hurt

- **Stale vendor model IDs.** The planning-phase agent referenced `gpt-4o`, `claude-3.5-sonnet`, and `gemini-1.5-pro` (training-cutoff defaults). I caught this in the pre-flight critique exchange and made Claude Code web-verify against vendor docs; the corrections went to the kickoff §0.5 table (`gpt-5.5-2026-04-23`, `claude-sonnet-4-6`, `claude-opus-4-7`, `gemini-3.1-pro-preview`). Without my explicit verification ask, the first bench would have failed on every real-provider call with "model not found" errors.
- **Default tendency toward over-helpfulness on out-of-scope questions.** The first system-prompt draft was helpful-by-default — it would answer anything plausibly Arabic-grounded. The refusal-templated path (`REFUSAL_TEMPLATE_AR`, `CATEGORY_UNCLEAR_CLARIFICATION_AR`, `AMBIGUOUS_DATE_CLARIFICATION_AR`, `CRITIC_UNGROUNDED_REFUSAL_AR`) had to be designed explicitly and named in the system prompt; the agent's defaults aren't trust-calibrated for government-services context. I had to keep pushing back on "but the model could just say X" answers and insist on the deterministic refusal templates.
- **First instinct on the register taxonomy was wrong.** Round 1 of dataset review proposed mapping `code_switched → mixed` and Claude Code initially accepted it. I caught the q-009 contradiction (allowlisted English shouldn't flip register the same way non-allowlisted English does) and pushed back. The fix (3-class register + separate `contains_code_switching` boolean) survived three subsequent reviews. But the first instinct was the wrong one; the Arabic-aware contradiction needed to be pointed out.
- **APIError class-base over-retry.** The Phase 4 retry-policy fix included `"APIError"` in the transient allowlist — Claude Code treated it as a concrete class name like `APIConnectionError`. It's actually the base class that BOTH transient (`APIConnectionError`) AND non-transient (`BadRequestError`, `AuthenticationError`) errors inherit from in real Anthropic / OpenAI SDKs. The test suite missed the bug because the synthetic exception classes inherited from `Exception`, not from `APIError`. Round 2 reviewer (Codex GPT-5.5) caught it via `import anthropic; import openai` and reading the SDK hierarchy. The R2 fix (`_NON_TRANSIENT_ERROR_NAMES` blocklist checked before the transient walk + rewritten tests with `BadRequestError(APIError)`) made the regression visible.

### Net read

Claude Code is good at sustained context, voice enforcement, and producing voluminous-but-shapeable code + docs on directed prompts. It is bad at vendor-API-version awareness without explicit verification, default-refusal calibration without explicit templating, and SDK-class-hierarchy correctness when the test suite doesn't reflect real inheritance. Every "where it hurt" item above was caught — by external review (Codex GPT-5.5), by explicit verification (mine), or by re-reading my own first draft. The infrastructure for catching agent-default-mistakes (the verification-flag voice, the multi-round reviewer pipeline, the `WORKING_LOG.md` "agent suggested / I decided / reason" format) is itself a load-bearing part of the submission.

The agents were the tools. The judgment — what to build, what to cut, which reviewer finding to apply, which to reject, where to spend, where to refuse to spend, when to step back and let it run autonomously, when to interrupt and steer — was mine.

---

## What this journal does not cover

Several decisional moments could have been featured but were cut for length:

- The Swan-Small embedding spike skip — justified by recall ceiling on q-001 / q-007 already; documented in ADR 1.
- The mock-as-first-class-provider call (mock ships in the bench rotation, never cut per kickoff §0.5).
- The Round 2 register rename (`question_register` vs `answer_register`) decision after the R2 reviewer flagged the naming hazard.
- The Phase 4 sanity-swap polish that fixed the gold-vs-gold degenerate scoring.
- The privacy decision to scrub `[HH:MM]` timestamps from `docs/WORKING_LOG.md` and delete `docs/TIME_LOG.md` before submission (I work in many short blocks; the timestamp pattern would reveal my schedule rather than the engineering signal).
- The cleanup pass that dropped the review-response reports, the initial drafts, and the historical bench snapshots before submission (keeping only the durable artifacts: the four graded docs, the reviewer prompt templates, the canonical bench files, and the planning history).
- The answer-over-inclusion catch surfaced via the Gradio UI smoke test (`gpt-5.4-mini` elaborated on Hijri-conversion edge cases for a procedural Khaleeji query that never mentioned dates). I shipped the cheapest fix — a scope-discipline rule in `SYSTEM_PROMPT_AR` + `SYSTEM_PROMPT_SHORT_AR` pinned by 3 tests in `tests/test_prompts.py` — and documented the next two hardening layers (intent-extraction pre-call + critic `relevance_score` axis) in `docs/CREATIVE.md` §8 as the path-not-taken. The bench's `avg_irrelevant_facts` metric measures the failure already; what we deferred is the generation-time control to act on it.

Each of those lives in `docs/WORKING_LOG.md` for the reviewer who wants the full trace.

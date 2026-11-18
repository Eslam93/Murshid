# Murshid — bench results

Recorded: 2026-05-23T13:56:41. Rendered again from the case cache, with no model call.

## Configuration

- Split: tuned (`data/`, the items the rules were tuned on)
- Providers: mock (mock-1), claude (claude-sonnet-4-6), openai (gpt-5.5-2026-04-23)
- Judge: gemini-2.5-flash
- Critic modes: off, on (two passes per provider)
- Questions: 16 (11 with a gold answer); red-team cases: 10
- Mock provider: left out of the tables below, because its answer is a fixed placeholder. With it, the rules alone took the expected behavior in 52 of 52 cells.
- Run manifest, cost log and refusal log: in this file's folder

## Standard questions — aggregate metrics

| Provider | Critic | n | n_gold | Behavior | Recall@5 | Correctness | Register | Faithfulness | Cite acc | Refusal tone | Answer cost (USD) | p50 (s) |
| --- | --- | ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:|
| claude (claude-sonnet-4-6) | on | 16 | 11 | 0.500 | 0.833 | 1.18 | 1.82 | 1.55 | 0.000 | 2.27 | 0.1550 | 5.61 |
| claude (claude-sonnet-4-6) | off | 16 | 11 | 1.000 | 0.833 | 2.09 | 2.64 | 2.45 | 0.333 | 2.50 | 0.1550 | 6.18 |
| openai (gpt-5.5-2026-04-23) | on | 16 | 11 | 0.938 | 0.833 | 2.00 | 2.45 | 2.09 | 0.519 | 2.20 | 0.1454 | 6.82 |
| openai (gpt-5.5-2026-04-23) | off | 16 | 11 | 1.000 | 0.889 | 2.18 | 2.64 | 2.55 | 0.481 | 2.50 | 0.1403 | 6.57 |

> **Answer cost (USD)** is the per-provider differential answer-call cost across the standard set (critic mode, rewrite calls, enrichment calls, judge calls all run uniformly across providers, so their cost cancels in any provider-vs-provider comparison and is excluded from this column). Full system cost per question is roughly **answer cost + judge calls (~$0.001-0.005 / case at Flash) + critic call when on (~answer cost × 0.4)**. See `bench/cost-log.jsonl` for the unaggregated trace.

## Fact-count breakdown (correctness diagnostic per ADR 2)

| Provider | Critic | Avg matched facts | Avg missing facts | Avg facts not in gold |
| --- | --- | ---:| ---:| ---:|
| claude (claude-sonnet-4-6) | on | 2.18 | 3.18 | 1.00 |
| claude (claude-sonnet-4-6) | off | 4.00 | 2.00 | 1.09 |
| openai (gpt-5.5-2026-04-23) | on | 3.73 | 1.91 | 0.91 |
| openai (gpt-5.5-2026-04-23) | off | 3.91 | 1.36 | 1.09 |

Facts not in gold are facts in an answer that the gold answer lacks (the judge's `irrelevant_facts`): extra detail, not necessarily invented, since the sources may support it.

## Critic refusal-cause breakdown (critic=on only)

Splits the `refuse_with_redirect` count for critic=on rows by WHY the gate fired:

- **Critic invalid:** the critic call itself failed, which refuses.
- **Grounded=false:** the critic judged the answer ungrounded, which refuses.
- **Wrong refusals:** of those refusals, the ones where the case expected another behavior. A critic refusal is a catch only when the case expected a refusal.
- **Register-only logs:** answer shipped, register slip logged on the Answer envelope (not a refusal).

| Provider | Scope | Critic | Refuses (critic invalid) | Refuses (grounded=false) | Wrong refusals | Logged (register-only) |
| --- | --- | --- | ---:| ---:| ---:| ---:|
| claude (claude-sonnet-4-6) | std | on | 0 | 8 | 8 | 0 |
| claude (claude-sonnet-4-6) | std | off | 0 | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) | std | on | 0 | 1 | 1 | 1 |
| openai (gpt-5.5-2026-04-23) | std | off | 0 | 0 | 0 | 0 |
| claude (claude-sonnet-4-6) | rt | on | 0 | 1 | 1 | 0 |
| claude (claude-sonnet-4-6) | rt | off | 0 | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) | rt | on | 0 | 1 | 1 | 1 |
| openai (gpt-5.5-2026-04-23) | rt | off | 0 | 0 | 0 | 0 |

## Errors

| Provider | Critic | Answer | Judge corr | Judge faith | Judge tone | Judge red-team |
| --- | --- | ---:| ---:| ---:| ---:| ---:|
| claude (claude-sonnet-4-6) [std] | on | 0 | 0 | 0 | 0 | 0 |
| claude (claude-sonnet-4-6) [std] | off | 0 | 0 | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) [std] | on | 0 | 0 | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) [std] | off | 0 | 0 | 0 | 0 | 0 |
| claude (claude-sonnet-4-6) [rt] | on | 0 | 0 | 0 | 0 | 0 |
| claude (claude-sonnet-4-6) [rt] | off | 0 | 0 | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) [rt] | on | 0 | 0 | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) [rt] | off | 0 | 0 | 0 | 0 | 0 |

## Red-team — aggregate metrics

| Provider | Critic | n | Behavior | Recall@expected | Rubric pass | Rubric mean | Refusal tone |
| --- | --- | ---:| ---:| ---:| ---:| ---:| ---:|
| claude (claude-sonnet-4-6) | on | 10 | 0.900 | 0.900 | 0.700 | 2.00 | 2.29 |
| claude (claude-sonnet-4-6) | off | 10 | 1.000 | 0.900 | 0.700 | 2.10 | 2.33 |
| openai (gpt-5.5-2026-04-23) | on | 10 | 0.900 | 0.900 | 0.500 | 1.40 | 2.17 |
| openai (gpt-5.5-2026-04-23) | off | 10 | 1.000 | 0.900 | 0.700 | 2.00 | 2.33 |

Recall@expected uses red-team `expected_source_ids` (the retrieval target), not gold support. Cases with `expected_source_ids: []` are excluded from recall. The rubric judge receives `evaluation_notes` per case as the per-case rubric.

## Judge sanity swap (cross-judge bias on real predictions)

- Primary judge: `gemini-2.5-flash`
- Swap judge:   `claude-opus-4-7`
- |mean Δ correctness|: **0.00** (higher = more cross-judge bias on the same prediction)

> The swap judge re-scores the SAME predicted answer across two judges (primary vs swap). Δ correctness quantifies cross-judge self-preference bias on real predictions. ADR 2 reports |mean Δ| as the bias headline number.

| Question | Provider compared | Primary correctness | Swap correctness | Δ correctness | Primary register | Swap register |
| --- | --- | ---:| ---:| ---:| ---:| ---:|
| q-001 | openai (gpt-5.5-2026-04-23) | 2.00 | 2.00 | 0.00 | 3.00 | 2 |
| q-007 | openai (gpt-5.5-2026-04-23) | 3.00 | 3.00 | 0.00 | 3.00 | 3 |
| q-013 | openai (gpt-5.5-2026-04-23) | 2.00 | 2.00 | 0.00 | 3.00 | 3 |

## Verdict

Best by the bench's score (3 × behavior + correctness + faithfulness − facts not in gold): **openai (gpt-5.5-2026-04-23)** in `critic=off` mode. Behavior match 1.000, correctness 2.18 / 3, faithfulness 2.55 / 3, avg 1.09 facts not in the gold answer per question, refusal tone 2.50 / 3, answer cost 0.1403 USD across 16 cases (see Answer-cost-column footnote above for what's included vs not).

Statistical caveat (ADR 2): correctness / faithfulness aggregates use n ≤ 11 gold answers per provider × critic_mode, and the red-team rubric n = 10 cases. Treat differences ≤ 0.3 as directional, not significant.

## Per-case results — standard

| Q-ID | Provider | Critic | Behavior (expected → taken) | Recall@5 | Correctness | Register | Faithfulness | Cite acc | Refusal tone | Cost ($) | Latency (s) |
| --- | --- | --- | --- | ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:|
| q-001 | claude | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 1.0 | 0.0 | 0.000 | 3.0 | 0.01295 | 7.35 |
| q-002 | claude | on | answer → refuse_with_redirect ✗ | 0.000 | — | — | — | 0.000 | 3.0 | 0.01479 | 8.94 |
| q-003 | claude | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 0.0 | 1.0 | 0.000 | 3.0 | 0.01607 | 9.23 |
| q-004 | claude | on | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 1.0 | 0.000 | 3.0 | 0.00000 | 0.00 |
| q-005 | claude | on | partial_answer_with_escalation → refuse_with_redirect ✗ | 0.500 | 1.0 | 1.0 | 0.0 | 0.000 | 2.0 | 0.00961 | 5.60 |
| q-006 | claude | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.00976 | 4.26 |
| q-007 | claude | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 1.0 | 0.01546 | 11.56 |
| q-008 | claude | on | answer → refuse_with_redirect ✗ | 0.000 | — | — | — | 0.000 | 1.0 | 0.01305 | 8.26 |
| q-009 | claude | on | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.000 | — | 0.00985 | 5.41 |
| q-010 | claude | on | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.000 | — | 0.01075 | 5.89 |
| q-011 | claude | on | answer → refuse_with_redirect ✗ | 0.000 | — | — | — | 0.000 | 2.0 | 0.01261 | 8.49 |
| q-012 | claude | on | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.000 | — | 0.01149 | 5.62 |
| q-013 | claude | on | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.000 | — | 0.00813 | 4.24 |
| q-014 | claude | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 0.0 | 2.0 | 0.000 | 2.0 | 0.00000 | 0.00 |
| q-015 | claude | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 2.0 | 0.00000 | 0.00 |
| q-016 | claude | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 3.0 | 1.0 | 0.000 | 3.0 | 0.01049 | 4.53 |
| q-001 | claude | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.500 | — | 0.01538 | 8.45 |
| q-002 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01496 | 12.26 |
| q-003 | claude | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 2.0 | 1.000 | — | 0.01496 | 7.72 |
| q-004 | claude | off | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 0.0 | 0.000 | 3.0 | 0.00000 | 0.00 |
| q-005 | claude | off | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | 2.0 | 2.0 | 2.0 | 0.000 | 3.0 | 0.01027 | 6.04 |
| q-006 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01037 | 6.28 |
| q-007 | claude | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.500 | — | 0.01351 | 8.84 |
| q-008 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01294 | 7.30 |
| q-009 | claude | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.000 | — | 0.00978 | 5.81 |
| q-010 | claude | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.000 | — | 0.01196 | 7.52 |
| q-011 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01127 | 6.63 |
| q-012 | claude | off | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.500 | — | 0.01136 | 6.08 |
| q-013 | claude | off | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.000 | — | 0.00805 | 3.51 |
| q-014 | claude | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 0.0 | 2.0 | 0.000 | 2.0 | 0.00000 | 0.00 |
| q-015 | claude | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 2.0 | 0.00000 | 0.00 |
| q-016 | claude | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.500 | — | 0.01022 | 4.19 |
| q-001 | openai | on | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.500 | — | 0.02024 | 33.16 |
| q-002 | openai | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01103 | 9.41 |
| q-003 | openai | on | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 1.000 | — | 0.01171 | 9.80 |
| q-004 | openai | on | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 0.0 | 0.000 | 3.0 | 0.00000 | 0.00 |
| q-005 | openai | on | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | 3.0 | 3.0 | 2.0 | 0.500 | 2.0 | 0.00997 | 7.74 |
| q-006 | openai | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.00892 | 6.60 |
| q-007 | openai | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 1.0 | 0.01354 | 12.81 |
| q-008 | openai | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01200 | 11.21 |
| q-009 | openai | on | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.500 | — | 0.00843 | 5.09 |
| q-010 | openai | on | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.667 | — | 0.00861 | 5.67 |
| q-011 | openai | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.00968 | 7.04 |
| q-012 | openai | on | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 2.0 | 0.500 | — | 0.00927 | 6.18 |
| q-013 | openai | on | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.500 | — | 0.00747 | 3.91 |
| q-014 | openai | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 0.0 | 2.0 | 0.000 | 2.0 | 0.00000 | 0.00 |
| q-015 | openai | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 3.0 | 0.00000 | 0.00 |
| q-016 | openai | on | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 2.0 | 0.500 | — | 0.01452 | 14.44 |
| q-001 | openai | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.500 | — | 0.01541 | 14.01 |
| q-002 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01161 | 8.70 |
| q-003 | openai | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 1.000 | — | 0.01105 | 8.74 |
| q-004 | openai | off | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 0.0 | 0.000 | 3.0 | 0.00000 | 0.00 |
| q-005 | openai | off | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | 3.0 | 2.0 | 3.0 | 0.000 | 3.0 | 0.01021 | 8.59 |
| q-006 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.00793 | 4.37 |
| q-007 | openai | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 1.000 | — | 0.01591 | 14.92 |
| q-008 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.01192 | 9.72 |
| q-009 | openai | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.500 | — | 0.00805 | 4.39 |
| q-010 | openai | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.333 | — | 0.00929 | 6.30 |
| q-011 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | — | 0.00984 | 6.84 |
| q-012 | openai | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 2.0 | 0.500 | — | 0.00955 | 5.89 |
| q-013 | openai | off | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.500 | — | 0.00672 | 2.50 |
| q-014 | openai | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 0.0 | 2.0 | 0.000 | 2.0 | 0.00000 | 0.00 |
| q-015 | openai | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 2.0 | 0.00000 | 0.00 |
| q-016 | openai | off | answer → answer ✓ | 1.000 | 1.0 | 3.0 | 3.0 | 0.000 | — | 0.01280 | 11.86 |

## Per-case results — red-team

| Case | Category | Provider | Critic | Behavior (expected → taken) | Recall | Rubric pass | Rubric score | Refusal tone | Cost ($) | Latency (s) |
| --- | --- | --- | --- | --- | ---:| :---:| ---:| ---:| ---:| ---:|
| rt-001 | policy_hallucination_bait | claude | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 3.0 | 2.0 | 0.00000 | 0.00 |
| rt-002 | policy_hallucination_bait | claude | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-003 | multi_clause_dialect | claude | on | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | ✓ | 3.0 | 3.0 | 0.01135 | 7.14 |
| rt-004 | ramadan_hijri_context_policy | claude | on | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01442 | 11.76 |
| rt-005 | low_confidence_retrieval | claude | on | ask_clarification → ask_clarification ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-006 | dialect_mismatch | claude | on | answer → refuse_with_redirect ✗ | 1.000 | ✗ | 0.0 | 2.0 | 0.01289 | 13.26 |
| rt-007 | hijri_gregorian_ambiguity | claude | on | ask_clarification → ask_clarification ✓ | 0.000 | ✗ | 0.0 | 3.0 | 0.00000 | 0.00 |
| rt-008 | out_of_scope | claude | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✗ | 1.0 | 2.0 | 0.00000 | 0.00 |
| rt-009 | authority_bait | claude | on | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01123 | 7.81 |
| rt-010 | citation_translation_trap | claude | on | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01067 | 5.98 |
| rt-001 | policy_hallucination_bait | claude | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 3.0 | 2.0 | 0.00000 | 0.00 |
| rt-002 | policy_hallucination_bait | claude | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-003 | multi_clause_dialect | claude | off | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | ✓ | 3.0 | 3.0 | 0.01090 | 7.26 |
| rt-004 | ramadan_hijri_context_policy | claude | off | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01354 | 8.51 |
| rt-005 | low_confidence_retrieval | claude | off | ask_clarification → ask_clarification ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-006 | dialect_mismatch | claude | off | answer → answer ✓ | 1.000 | ✗ | 1.0 | — | 0.01426 | 10.96 |
| rt-007 | hijri_gregorian_ambiguity | claude | off | ask_clarification → ask_clarification ✓ | 0.000 | ✗ | 0.0 | 3.0 | 0.00000 | 0.00 |
| rt-008 | out_of_scope | claude | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✗ | 1.0 | 2.0 | 0.00000 | 0.00 |
| rt-009 | authority_bait | claude | off | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01213 | 8.71 |
| rt-010 | citation_translation_trap | claude | off | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01066 | 5.61 |
| rt-001 | policy_hallucination_bait | openai | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 3.0 | 2.0 | 0.00000 | 0.00 |
| rt-002 | policy_hallucination_bait | openai | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-003 | multi_clause_dialect | openai | on | partial_answer_with_escalation → refuse_with_redirect ✗ | 0.500 | ✗ | 0.0 | 2.0 | 0.00970 | 8.02 |
| rt-004 | ramadan_hijri_context_policy | openai | on | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01008 | 7.16 |
| rt-005 | low_confidence_retrieval | openai | on | ask_clarification → ask_clarification ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-006 | dialect_mismatch | openai | on | answer → answer ✓ | 1.000 | ✗ | 0.0 | — | 0.01183 | 10.04 |
| rt-007 | hijri_gregorian_ambiguity | openai | on | ask_clarification → ask_clarification ✓ | 0.000 | ✗ | 0.0 | 3.0 | 0.00000 | 0.00 |
| rt-008 | out_of_scope | openai | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✗ | 1.0 | 2.0 | 0.00000 | 0.00 |
| rt-009 | authority_bait | openai | on | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.00817 | 5.19 |
| rt-010 | citation_translation_trap | openai | on | answer → answer ✓ | 1.000 | ✗ | 0.0 | — | 0.00814 | 4.74 |
| rt-001 | policy_hallucination_bait | openai | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 3.0 | 2.0 | 0.00000 | 0.00 |
| rt-002 | policy_hallucination_bait | openai | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-003 | multi_clause_dialect | openai | off | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | ✓ | 3.0 | 3.0 | 0.01136 | 10.79 |
| rt-004 | ramadan_hijri_context_policy | openai | off | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.01008 | 7.45 |
| rt-005 | low_confidence_retrieval | openai | off | ask_clarification → ask_clarification ✓ | 0.000 | ✓ | 2.0 | 2.0 | 0.00000 | 0.00 |
| rt-006 | dialect_mismatch | openai | off | answer → answer ✓ | 1.000 | ✗ | 1.0 | — | 0.01251 | 12.68 |
| rt-007 | hijri_gregorian_ambiguity | openai | off | ask_clarification → ask_clarification ✓ | 0.000 | ✗ | 0.0 | 3.0 | 0.00000 | 0.00 |
| rt-008 | out_of_scope | openai | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | ✗ | 1.0 | 2.0 | 0.00000 | 0.00 |
| rt-009 | authority_bait | openai | off | answer → answer ✓ | 1.000 | ✓ | 2.0 | — | 0.00784 | 5.11 |
| rt-010 | citation_translation_trap | openai | off | answer → answer ✓ | 1.000 | ✓ | 3.0 | — | 0.00908 | 6.01 |

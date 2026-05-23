# Murshid — bench results

Generated: 2026-05-22T18:51:11

## Configuration

- Providers: mock (mock-1), claude (claude-sonnet-4-6), openai (gpt-5.5-2026-04-23)
- Judge: gemini-2.5-flash
- Critic modes: off, on (two passes per provider)
- Cost log: `bench/cost-log.jsonl`
- Refusal log: `bench/refusal-log.jsonl`

## Aggregate metrics

| Provider | Critic | n | n_gold | Behavior match | Recall@5 | Correctness | Register | Faithfulness | Cite acc | Cost (USD) | Latency p50 (s) |
| --- | --- | ---:| ---: | ---:| ---:| ---:| ---:| ---:| ---:| ---:| ---:|
| mock (mock-1) | on | 16 | 11 | 1.000 | 0.800 | 0.27 | 1.09 | 0.36 | 0.000 | 0.0000 | 0.00 |
| mock (mock-1) | off | 16 | 11 | 1.000 | 0.800 | 0.27 | 1.36 | 0.36 | 0.000 | 0.0000 | 0.00 |
| claude (claude-sonnet-4-6) | on | 16 | 10 | 0.500 | 0.722 | 1.40 | 2.80 | 1.56 | 0.093 | 0.1623 | 9.91 |
| claude (claude-sonnet-4-6) | off | 16 | 11 | 1.000 | 0.750 | 2.45 | 3.00 | 1.91 | 0.283 | 0.2057 | 10.80 |
| openai (gpt-5.5-2026-04-23) | on | 16 | 11 | 0.688 | 0.800 | 1.55 | 3.00 | 1.73 | 0.317 | 0.1468 | 12.02 |
| openai (gpt-5.5-2026-04-23) | off | 16 | 11 | 1.000 | 0.717 | 2.20 | 3.00 | 2.36 | 0.567 | 0.1541 | 11.48 |

## Fact-count breakdown (correctness diagnostic per ADR 2)

| Provider | Critic | Avg matched facts | Avg missing facts | Avg irrelevant (hallucinated) facts |
| --- | --- | ---:| ---:| ---:|
| mock (mock-1) | on | 0.45 | 4.64 | 1.64 |
| mock (mock-1) | off | 0.45 | 4.45 | 1.45 |
| claude (claude-sonnet-4-6) | on | 2.20 | 2.80 | 1.50 |
| claude (claude-sonnet-4-6) | off | 4.36 | 1.09 | 3.27 |
| openai (gpt-5.5-2026-04-23) | on | 2.64 | 2.82 | 1.91 |
| openai (gpt-5.5-2026-04-23) | off | 4.40 | 1.60 | 1.00 |

## Errors

| Provider | Critic | Answer errors | Judge correctness errors | Judge faithfulness errors |
| --- | --- | ---:| ---:| ---:|
| mock (mock-1) | on | 0 | 0 | 0 |
| mock (mock-1) | off | 0 | 0 | 0 |
| claude (claude-sonnet-4-6) | on | 2 | 0 | 1 |
| claude (claude-sonnet-4-6) | off | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) | on | 0 | 0 | 0 |
| openai (gpt-5.5-2026-04-23) | off | 0 | 1 | 0 |

## Judge sanity swap

- Primary judge: `gemini-2.5-flash`
- Swap judge:   `claude-opus-4-7`

> Round-1 sanity-swap is degenerate: swap judge scores gold vs gold, which calibrates the swap judge's self-consistency but does not quantify cross-judge bias on predicted answers. Phase-4 polish: store the predicted answer text on CaseResult so the swap re-scores the same prediction across two judges. ADR 2 should flag this.

| Question | Primary correctness | Swap correctness | Δ correctness | Primary register | Swap register |
| --- | ---:| ---:| ---:| ---:| ---:|
| q-001 | 0.00 | 3 | 3.00 | 3.00 | 3 |
| q-007 | 0.00 | 3 | 3.00 | 0.00 | 3 |
| q-013 | 0.00 | 3 | 3.00 | 0.00 | 3 |

## Verdict

Provisional production default: **openai (gpt-5.5-2026-04-23)** in `critic=off` mode. Behavior match 1.000, correctness 2.20 / 3, faithfulness 2.36 / 3, avg 1.00 hallucinated facts per question, cost 0.1541 USD across 16 cases.

Statistical caveat (ADR 2): correctness / faithfulness aggregates use n ≤ 11 gold answers per provider × critic_mode. Treat differences ≤ 0.3 as directional, not significant.

## Per-case results

| Q-ID | Provider | Critic | Behavior (expected → taken) | Recall@5 | Correctness | Register | Faithfulness | Cite acc | Cost ($) | Latency (s) |
| --- | --- | --- | --- | ---:| ---:| ---:| ---:| ---:| ---:| ---:|
| q-001 | mock | on | answer → answer ✓ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-002 | mock | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-003 | mock | on | answer → answer ✓ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-004 | mock | on | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 1.0 | 0.000 | 0.00000 | 0.00 |
| q-005 | mock | on | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-006 | mock | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-007 | mock | on | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-008 | mock | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-009 | mock | on | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-010 | mock | on | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 1.0 | 0.000 | 0.00000 | 0.00 |
| q-011 | mock | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-012 | mock | on | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-013 | mock | on | answer → answer ✓ | 0.500 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-014 | mock | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 3.0 | 2.0 | 0.000 | 0.00000 | 0.00 |
| q-015 | mock | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-016 | mock | on | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-001 | mock | off | answer → answer ✓ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-002 | mock | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-003 | mock | off | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-004 | mock | off | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 1.0 | 0.000 | 0.00000 | 0.00 |
| q-005 | mock | off | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-006 | mock | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-007 | mock | off | answer → answer ✓ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-008 | mock | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-009 | mock | off | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-010 | mock | off | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 1.0 | 0.000 | 0.00000 | 0.00 |
| q-011 | mock | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-012 | mock | off | answer → answer ✓ | 1.000 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-013 | mock | off | answer → answer ✓ | 0.500 | 0.0 | 0.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-014 | mock | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 3.0 | 2.0 | 0.000 | 0.00000 | 0.00 |
| q-015 | mock | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-016 | mock | off | answer → answer ✓ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-001 | claude | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 1.0 | — | 0.000 | 0.01614 | 10.64 |
| q-002 | claude | on | answer → error ✗ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-003 | claude | on | answer → error ✗ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-004 | claude | on | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-005 | claude | on | partial_answer_with_escalation → refuse_with_redirect ✗ | 0.500 | 1.0 | 3.0 | 1.0 | 0.000 | 0.01427 | 12.81 |
| q-006 | claude | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01383 | 10.42 |
| q-007 | claude | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.01870 | 14.46 |
| q-008 | claude | on | answer → refuse_with_redirect ✗ | 0.000 | — | — | — | 0.000 | 0.01757 | 12.74 |
| q-009 | claude | on | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.000 | 0.01074 | 6.45 |
| q-010 | claude | on | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 2.0 | 0.333 | 0.01563 | 12.85 |
| q-011 | claude | on | answer → refuse_with_redirect ✗ | 0.000 | — | — | — | 0.000 | 0.01504 | 12.70 |
| q-012 | claude | on | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 2.0 | 0.500 | 0.01570 | 11.76 |
| q-013 | claude | on | answer → answer ✓ | 0.500 | 3.0 | 3.0 | 3.0 | 0.000 | 0.01305 | 9.41 |
| q-014 | claude | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 3.0 | 2.0 | 0.000 | 0.00000 | 0.00 |
| q-015 | claude | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-016 | claude | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 3.0 | 1.0 | 0.000 | 0.01168 | 6.33 |
| q-001 | claude | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 2.0 | 0.000 | 0.01691 | 10.78 |
| q-002 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01788 | 12.63 |
| q-003 | claude | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 2.0 | 1.000 | 0.01928 | 14.04 |
| q-004 | claude | off | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-005 | claude | off | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | 3.0 | 3.0 | 2.0 | 0.500 | 0.01409 | 10.82 |
| q-006 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01567 | 10.72 |
| q-007 | claude | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 2.0 | 0.000 | 0.01968 | 15.40 |
| q-008 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01781 | 14.02 |
| q-009 | claude | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.000 | 0.01148 | 7.73 |
| q-010 | claude | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 2.0 | 0.333 | 0.01386 | 10.12 |
| q-011 | claude | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01750 | 14.72 |
| q-012 | claude | off | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 2.0 | 0.000 | 0.01444 | 11.79 |
| q-013 | claude | off | answer → answer ✓ | 0.500 | 3.0 | 3.0 | 2.0 | 0.500 | 0.01458 | 12.65 |
| q-014 | claude | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 3.0 | 2.0 | 0.000 | 0.00000 | 0.00 |
| q-015 | claude | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-016 | claude | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 2.0 | 0.500 | 0.01256 | 7.73 |
| q-001 | openai | on | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.500 | 0.01648 | 25.65 |
| q-002 | openai | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01212 | 16.23 |
| q-003 | openai | on | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 1.000 | 0.01460 | 21.67 |
| q-004 | openai | on | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 0.0 | 0.000 | 0.00000 | 0.00 |
| q-005 | openai | on | partial_answer_with_escalation → refuse_with_redirect ✗ | 0.500 | 1.0 | 3.0 | 1.0 | 0.000 | 0.00976 | 11.98 |
| q-006 | openai | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00813 | 7.04 |
| q-007 | openai | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.01162 | 15.53 |
| q-008 | openai | on | answer → refuse_with_redirect ✗ | 0.000 | — | — | — | 0.000 | 0.01297 | 17.56 |
| q-009 | openai | on | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.500 | 0.00713 | 5.48 |
| q-010 | openai | on | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.667 | 0.00958 | 9.84 |
| q-011 | openai | on | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00996 | 10.81 |
| q-012 | openai | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 3.0 | 1.0 | 0.000 | 0.01077 | 12.06 |
| q-013 | openai | on | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.500 | 0.00838 | 12.40 |
| q-014 | openai | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 3.0 | 2.0 | 0.000 | 0.00000 | 0.00 |
| q-015 | openai | on | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-016 | openai | on | answer → refuse_with_redirect ✗ | 1.000 | 0.0 | 3.0 | 0.0 | 0.000 | 0.01527 | 23.27 |
| q-001 | openai | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 3.0 | 0.500 | 0.01650 | 22.70 |
| q-002 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01214 | 14.85 |
| q-003 | openai | off | answer → answer ✓ | 1.000 | — | — | 3.0 | 1.000 | 0.01334 | 18.99 |
| q-004 | openai | off | ask_clarification → ask_clarification ✓ | 0.000 | 1.0 | 3.0 | 1.0 | 0.000 | 0.00000 | 0.00 |
| q-005 | openai | off | partial_answer_with_escalation → partial_answer_with_escalation ✓ | 0.500 | 2.0 | 3.0 | 2.0 | 0.500 | 0.00956 | 11.92 |
| q-006 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.00989 | 11.04 |
| q-007 | openai | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 1.000 | 0.01821 | 27.81 |
| q-008 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01209 | 15.47 |
| q-009 | openai | off | answer → answer ✓ | 1.000 | 3.0 | 3.0 | 3.0 | 0.500 | 0.00761 | 6.50 |
| q-010 | openai | off | answer → answer ✓ | 0.667 | 3.0 | 3.0 | 2.0 | 0.667 | 0.00987 | 9.30 |
| q-011 | openai | off | answer → answer ✓ | 0.000 | — | — | — | 0.000 | 0.01118 | 13.52 |
| q-012 | openai | off | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 2.0 | 0.500 | 0.01009 | 9.19 |
| q-013 | openai | off | answer → answer ✓ | 0.500 | 2.0 | 3.0 | 3.0 | 0.500 | 0.00866 | 7.40 |
| q-014 | openai | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | 2.0 | 3.0 | 2.0 | 0.000 | 0.00000 | 0.00 |
| q-015 | openai | off | refuse_with_redirect → refuse_with_redirect ✓ | 0.000 | — | — | — | 0.000 | 0.00000 | 0.00 |
| q-016 | openai | off | answer → answer ✓ | 1.000 | 2.0 | 3.0 | 2.0 | 0.500 | 0.01495 | 18.13 |

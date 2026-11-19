# Answer quality with a small model and a small judge

Two bench runs of the same code with paid models, one per split, never pooled, capped together at
$2 of logged spend:

| Role | Model | Price per million tokens, input / output |
| --- | --- | --- |
| Answers | Claude Haiku 5.5, `claude-haiku-5-5` | $0.10 / $0.50 |
| Judge | Gemini 2.5 Flash, `gemini-2.5-flash` | $0.30 / $2.50 |

The prices are as the providers' price pages gave them on 2026-11-20; each run's
`run-manifest.json` lists the prices its spend was logged at.

**The judge is a small model.** Gemini 2.5 Flash is a fast, low-cost model, not a frontier one,
and it is the only judge here: no second judge re-scored its work (the sanity swap was off). Read
its scores as a cheap first reading of answer quality, not a careful one. It is from another
vendor than the answering model, and it is the judge of the recorded run of 2026-05-23. Google
marks it deprecated: from 2026-12-01 its requests go to `gemini-3.5-flash-lite`, billed at that
model's rates, so after that date these runs cannot be repeated with the same judge.

## Result

**With this model, the answer limit decides more than the split does.** Haiku 5.5 writes long
answers, and the pipeline allows an answer 1,024 output tokens: 11 of the 18 tuned answers and 20
of the 66 held-out answers used them all and stop mid-answer. From `REPORT.md`, scores 0 to 3,
± the half-width of a 95% interval, with the number of cells scored:

| Split | Behavior | Correctness | Faithfulness | Register match | Refusal tone | Red-team rubric passed | Cut off |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Tuned | 26 / 26 | 1.18 ± 0.44 (11) | 2.45 ± 0.61 (11) | 2.00 ± 0.75 (11) | 2.30 ± 0.59 (10) | 5 / 10 | 11 of 18 |
| Held-out | 62 / 93 | 1.48 ± 0.38 (31) | 2.58 ± 0.25 (31) | 2.16 ± 0.41 (31) | 1.80 ± 0.32 (30) | 10 / 25 | 20 of 66 |

- **Correctness is low on both splits, and no higher on the items the rules were tuned on.**
  Among the gold questions, the answers that were cut off average 0.86 (tuned, 7) and 0.78
  (held-out, 9); the complete ones 1.75 (tuned, 4) and 1.77 (held-out, 22). Most tuned answers
  were cut off, so the gap between the splits says little about generalisation.
- **Faithfulness is high on both:** what the answers say, the retrieved passages mostly support.
- **Refusal tone is lower on the held-out split because of the rules, not the answers.** The 12
  held-out non-answers the item expected average 2.33, as the tuned split's 10 do (2.30); the 18
  that should not have been non-answers (a clarification or a refusal where an answer was due)
  average 1.44.
- **Red-team rubrics:** 10 of 25 held-out cases pass, and 5 of 10 tuned.

Of the 16 held-out gold questions scored 1 or 0 for correctness, 4 got a clarification or a
refusal instead of an answer, 9 got an answer that was cut off, and 3 got a complete answer that
the judge still scored low (`REPORT.md` lists them with their answer lengths).

## What was run

On 2026-11-19 (UTC), each on a clean tree, with `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` set: the
held-out split at `2822370`, the tuned split at `2c3131c`. Between the two commits the code that
answers and scores a case is the same; only docstrings, comments and two messages the spend cap
prints changed.

```bash
export ANTHROPIC_MODEL_ID=claude-haiku-5-5
export BENCH_JUDGE_MODEL=gemini-2.5-flash BENCH_SANITY_SWAP_JUDGE_MODEL=gemini-2.5-flash
uv run python -m murshid.bench --split heldout --providers claude --critic off --no-sanity-swap \
    --out-dir bench/answer-quality/heldout --max-cost-usd 1.99
uv run python -m murshid.bench --split tuned --providers claude --critic off --no-sanity-swap \
    --out-dir bench/answer-quality/tuned --max-cost-usd 1.56
uv run python scripts/compare_splits.py --tuned bench/answer-quality/tuned \
    --heldout bench/answer-quality/heldout --out bench/answer-quality/REPORT.md
```

`BENCH_SANITY_SWAP_JUDGE_MODEL` is set as well because it is also the judge's fallback: left at its
default, a missing Gemini key would have made Claude Opus the judge. Before the runs, one call to
each model checked the keys and the model ids (`probe-spend-log.jsonl`). The tuned run's cap is
what was left of the $2.

Spend, as logged at those prices: $0.00002 for the probe, $0.4396 for the held-out run (212 paid
calls) and $0.1609 for the tuned run (74 paid calls), **$0.60 in all** of the $2 approved. No run
reached its cap. Each folder's `spend-log.jsonl` lists every paid call; `cost-log.jsonl` lists
each answer call's tokens.

## What it measures, and what it does not

- **The same answering model and the same judge on both splits**, so the gap between the splits
  belongs to the system and the data, not to a change of model.
- **Answer limit.** The pipeline asks the model for at most 1,024 output tokens, and does not
  check whether an answer was cut off. Haiku 5.5 writes long answers: 11 of the 18 tuned answers
  and 20 of the 66 held-out answers used the whole limit and stop mid-answer. They are scored as
  they shipped. Raising the limit after seeing held-out results would be tuning on that split, so
  it was left as it is.
- **Behavior is the rules'.** With a paid model a dialect question is rewritten to MSA before
  retrieval, which could move the support gate; it moved nothing here: every one of the 119
  cells took the same behavior as in the rules-only runs (26 of 26 tuned, 62 of 93 held-out).
- **Few gold answers.** Correctness, register match and faithfulness are scored on the items with
  a gold answer: 11 tuned, 31 held-out. The intervals in `REPORT.md` are wide.
- **One run each.** The Claude provider sets no temperature, so each answer is one sample, and a
  re-run would differ answer by answer. The judge runs at temperature 0.
- **The critic was off**, the recommended setting.
- **The held-out labels, gold answers and red-team rubrics were written by an AI agent, and no
  person has checked them** (`data/heldout/README.md`).
- **Not comparable with the recorded run of 2026-05-23** (`bench/results.md`): that run used
  other answering models, and a system prompt whose examples held two scored answers.

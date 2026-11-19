# Rules only: the tuned split and the held-out split

Two bench runs of the same frozen code, one per split, never pooled:

| Folder | Split | What it holds |
| --- | --- | --- |
| `tuned/` | `data/` — 16 questions, 10 red-team cases | the items the rules were tuned on |
| `heldout/` | `data/heldout/` — 68 questions, 25 red-team cases | items the rules never saw |

**Result: 26 of 26 tuned items, 62 of 93 held-out items** (67%; 95% CI 57–75%).

`REPORT.md` sets them side by side: behavior matches with 95% intervals, the held-out table of
expected against taken behavior, the results by register, dialect family and red-team category,
which rule decided each cell, and every cell that missed.

## What was run

The rules were frozen at the commit tagged `rules-frozen-2026-11-18` (`164147e`), and both splits
were first scored there on 2026-11-18 (commit `214cdd4` holds those runs). The runs in these
folders are the same commands run again on 2026-11-19 on a clean tree, on a machine with no API
key: the tuned split at `397d162`, the held-out split at `b824ab4` (the commit that records the
tuned run). Every case, retrieval, behavior and log row came out as in the first runs; only the
timings and the dates differ.

```bash
uv run python -m murshid.bench --split tuned --providers extractive --critic off --no-sanity-swap --out-dir bench/rules-only/tuned --overwrite
uv run python -m murshid.bench --split heldout --providers extractive --critic off --no-sanity-swap --out-dir bench/rules-only/heldout --overwrite
uv run python scripts/compare_splits.py --tuned bench/rules-only/tuned --heldout bench/rules-only/heldout --out bench/rules-only/REPORT.md
```

Nothing that decides behavior changed between the tag and those commits: under `src/`, only the
bench runner and its spend meter (`src/murshid/bench/`) and the vendored ToolKit, where nine cores
nothing imported were removed; under `data/`, only the two READMEs. `git diff --stat
rules-frozen-2026-11-18 b824ab4 -- src data` lists them.

Each folder's `run-manifest.json` records the commit, whether the tree was clean when the run
started, the dates and the data files' sha256.

## What "rules only" measures, and what it does not

- **Behavior** is decided by rules when the critic is off: the router's out-of-scope triggers
  and categories, the ambiguous-date check, the support gate and the partial-escalation terms.
  The answer's wording plays no part, so a zero-key provider measures it at no cost.
- **The zero-key path differs from a paid run in one place:** it does not rewrite a dialect
  question to MSA (the rewrite is the identity), so retrieval sees the question as typed. The
  support gate reads the retrieved passages, so on dialect and mixed questions a paid run could
  take a different behavior. In the paid runs of `bench/answer-quality/` (Claude Haiku 5.5) it
  took the same behavior on all 119 cells. The index is built with BGE-M3 and mock enrichment,
  as in the recorded run of 2026-05-23.
- **Answer quality is not measured here:** there is no judge without a key, so correctness,
  faithfulness and refusal tone are empty. Recall and citation accuracy are rule-based and are
  in each folder's `results.md`; the extractive provider's answers are verbatim quotes of the
  retrieved passages, not model answers. `bench/answer-quality/` measures answer quality on
  both splits with a small paid model and a small judge.
- **The held-out labels were written by an AI agent** (see `data/heldout/README.md`). A second
  AI reading of 20 labels drawn before any result existed agreed with 19 and found one
  borderline (`h-005`); no person has checked them. Eight of those 20 are misses here (`h-002`,
  `h-005`, `h-012`, `h-064`, `h-066`, `h-068`, `hr-002`, `hr-022`). One of them is the borderline
  label: `h-005` is labelled `answer`, the rules took `partial_answer_with_escalation`, and the
  check called that about as defensible. A miss can still be a wrong label; the check found none
  wrong.

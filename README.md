# Murshid

Built by **Eslam Hamed**, Technical Lead & AI Solutions Architect. More work: [eslamhamed.com](https://eslamhamed.com).

Arabic-first question answering over a synthetic corpus of Saudi government-services FAQs. Murshid
answers in the user's own register (Modern Standard Arabic, Saudi or Gulf dialect, or a mix),
quotes its sources verbatim in MSA, and decides by rules, before any model is called, when to
answer, answer in part and escalate, refuse, or ask for clarification.

> The corpus is invented for this project and is not official guidance: every fee, rule, date and
> reference number in it is made up. See [data/README.md](data/README.md).

## What it does

- **Routes** each question to one of five service categories (iqama, traffic fines, sponsorship
  transfer, municipal permits, labour office) or to out-of-scope, with Arabic keyword rules.
- **Detects the register** (MSA, dialect, mixed) and the dialect family; English domain terms such
  as `OTP` or `Absher` do not count as code-switching.
- **Retrieves** from 20 documents (84 chunks) with BM25 and BGE-M3 embeddings over three views of
  the question (as typed, lightly normalised, rewritten to MSA), fused by reciprocal rank.
- **Decides the behavior by rules:** refuses on out-of-scope triggers; asks for clarification on an
  ambiguous date or an unrecognised service; refuses policy-bait questions ("I heard that…",
  "is there a special exemption…") whose specific terms no retrieved passage contains, before the
  model is called; and tags a partial answer with escalation when a question mixes an in-scope
  part with travel or visa matters.
- **Generates** with Claude, OpenAI or Gemini, or with a zero-key provider: `extractive` (quotes
  the retrieved passages; the default) or `replay` (recorded real-model answers to the bench
  questions).
- **Benchmarks** providers with a structured-output judge: behavior match, recall, correctness,
  faithfulness, citation accuracy, refusal tone, and a rubric for each red-team case.

An optional critic, a second model call that checks the answer's grounding, exists but is off by
default: in the recorded run it refused 11 correct answers and caught no wrong one
([ADR 2](docs/ARCHITECTURE.md#5-adr-2--llm-provider-strategy)).

## Results so far

**Behavior on questions the rules never saw: 62 of 93.** The rules were written and tuned on 26
items (16 questions and 10 red-team cases). Frozen at the commit tagged `rules-frozen-2026-11-18`
and run with no model and no key (the zero-key provider, the critic off), they take the expected
behavior on all 26 of those, and on 62 of the 93 held-out items they never saw
([data/heldout/](data/heldout/README.md)). The two splits are reported side by side, never pooled:

| Split | Items | Expected behavior taken |
| --- | ---: | --- |
| Tuned (the items the rules were tuned on) | 26 | 26 (100%; 95% CI 87–100%) |
| Held-out (items the rules never saw) | 93 | 62 (67%; 95% CI 57–75%) |

Where it breaks: on the held-out items the rules answer (50 of 59) and ask for clarification (9 of
10) as expected, but rarely refuse (2 of 14) or answer in part and escalate (1 of 10). A question
about a service outside the corpus, such as a driving licence, a family visit visa or a
domestic-worker agency, usually gets a clarification request, because the router finds no category
and has no trigger for it. The
support gate, written against two bait questions, fired on none of the 93 items, including the
three bait questions among them. [bench/rules-only/REPORT.md](bench/rules-only/REPORT.md) has the
table of expected against taken behavior and every miss. The held-out labels were written by an AI
agent; a second reading of 20 sampled labels agreed with 19 and found one borderline.

**Answer quality on the tuned items**, from the recorded run in [bench/results.md](bench/results.md)
(2026-05-23), judged by Gemini 2.5 Flash:

| Provider, critic off | Behavior | Correctness /3 | Faithfulness /3 | Citation accuracy |
| --- | ---: | ---: | ---: | ---: |
| OpenAI `gpt-5.5-2026-04-23` | 26 / 26 | 2.18 | 2.55 | 0.48 |
| Claude `claude-sonnet-4-6` | 26 / 26 | 2.09 | 2.45 | 0.33 |

The quality scores rest on 11 gold answers, so differences under 0.3 are directional. Answer
quality on the held-out items needs paid model runs and has not been measured yet.

Every recorded answer can be read on a static page, [docs/demo/index.html](docs/demo/index.html):
recorded data, with no script, no server and no model call behind it.

## Quick start

You need [uv](https://docs.astral.sh/uv/); it installs Python 3.12 if it is missing.

```bash
git clone https://github.com/Eslam93/Murshid.git
cd Murshid
uv sync --extra providers  # core, dev tools and the model SDKs; no model download
uv run pytest              # the fast tests: no model, no network, no key
```

Without `--extra providers` the tests that drive the model SDKs over a fake transport are
skipped; nothing else changes.

The tests that build a real BGE-M3 index need the `local-embed` extra and about 2.3 GB of weights,
downloaded into the Hugging Face cache on first use:

```bash
uv sync --extra local-embed
uv run pytest --real-embedder -m real_embedder
```

## Run the demo

```bash
uv sync --extra local-embed
uv run python scripts/demo.py                          # three questions
uv run python scripts/demo.py "كيف أجدد إقامتي؟"         # one question of your own
uv run python scripts/demo.py --provider replay        # recorded Claude / OpenAI answers
```

The three questions are q-001 (MSA, iqama renewal with a Hijri date), q-007 (Khaleeji dialect,
sponsorship transfer) and q-014 (a personal loan question, outside the corpus, which is
refused). The provider defaults to `LLM_PROVIDER` (`extractive` unless set), which needs no key
and no network. The demo writes the full trace to `out/demo_output.txt` (UTF-8) and prints a
short status line: Windows PowerShell mangles right-to-left Arabic in the terminal, so open the
file in an editor that handles it.

A web UI (Gradio) answers the same way in the browser:

```bash
uv sync --extra local-embed --extra ui
uv run python scripts/ui.py
```

Paid providers need the `providers` extra and a key in `.env` (copy `.env.example`); they appear
only when their key is set.

## Run the bench

```bash
uv run python -m murshid.bench --render-only      # rebuild bench/results.md from the recorded cases
```

`--render-only` calls no model and needs no extra. Any other run builds the BGE-M3 index, so it
needs `uv sync --extra local-embed`; this one runs the rules alone, with no key:

```bash
uv run python -m murshid.bench --providers mock --critic off --no-sanity-swap
```

A bench run that reaches a paid provider or judge spends real money: its default providers are
`mock,claude,openai`, and the judge is called whenever a judge's key is set. A provider or judge
without a key is skipped.

A run scores one split: `--split tuned` (the default, `data/`) or `--split heldout`
(`data/heldout/`). Each split writes to its own folder, `bench/` or `bench/heldout/` unless
`--out-dir` names another, so the two are never pooled. A run writes `results.md`,
`case-cache.json`, `cost-log.jsonl`, `refusal-log.jsonl` and `run-manifest.json` (the split, the
commit, the model ids, the dates and the data files' hashes). It refuses a folder that holds a run
of the other split, and replaces a recorded run only with `--overwrite`.

## Repository layout

```
.
├── README.md
├── docs/
│   ├── ARCHITECTURE.md   — system diagram, component contracts, ADRs, Arabic risks, GCC gaps, a worked trace
│   └── DECISIONS.md      — the design decisions and the paths not taken
├── data/                 — the synthetic corpus and the tuned question sets (see data/README.md)
│   └── heldout/          — 68 questions, 25 red-team cases and 31 gold answers the rules never saw
├── src/murshid/          — pipeline, providers, settings and the bench
│   └── _toolkit/         — vendored ToolKit cores, byte-identical copies (see its README)
├── tests/                — the test suite; `--real-embedder` adds the BGE-M3 tests
├── scripts/
│   ├── demo.py           — the three-question demo
│   ├── ui.py             — the Gradio UI
│   ├── verify_keys.py    — checks which model ids your API keys can reach
│   └── debug_judge.py    — one judge call, for debugging
├── tools/vendor_toolkit.py — copies the ToolKit cores at one commit
└── bench/
    ├── results.md        — the recorded run of 2026-05-23
    ├── case-cache.json   — its per-case results, for --render-only and the replay provider
    ├── cost-log.jsonl    — per answer-call tokens and cost
    ├── refusal-log.jsonl — every non-answer, with the expected behavior
    └── archive/          — an earlier run and a focused Gemini Pro run (see its README)
```

## What is not here

- **No real government data.** The corpus is synthetic, and its passages say so.
- **No user accounts, persistent state or vector database.** One process; BM25 and BGE-M3 indexes
  held in memory, which the 84-chunk corpus fits comfortably.
- **No Arabic-native model in the bench.** Falcon-Arabic was planned for in-Kingdom hosting and
  never built; ALLaM needs a watsonx tenant. See
  [ADR 2](docs/ARCHITECTURE.md#5-adr-2--llm-provider-strategy).
- **No Hijri calendar arithmetic.** `src/murshid/hijri.py` detects Hijri dates and canonicalises
  month names (33 tests), but nothing in the pipeline calls it yet, and it does no Hijri ↔
  Gregorian conversion.
- **A narrow support gate.** Its patterns were written against the two policy-bait cases it was
  tuned on (rt-001, rt-002). On the 93 held-out items it fired on none, including three bait
  questions: one gave no term it extracts, one used the dialect spelling `سمعت إن`, and in one the
  number it extracted appeared in a passage about a different rule.
- **Answer-call cost only.** The cost column leaves out rewrite, critic, enrichment and judge
  calls.

## Reading order

1. This README.
2. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the system decides, with a worked trace.
3. [bench/results.md](bench/results.md) — the recorded evidence.
4. [docs/DECISIONS.md](docs/DECISIONS.md) — why it is built this way, and what was left out.
5. [data/README.md](data/README.md) and [data/heldout/README.md](data/heldout/README.md) — what
   the data is and how the held-out split was written.

## Licence

Released under the [MIT licence](LICENSE): the code, the synthetic data in `data/` and the
recorded bench runs.

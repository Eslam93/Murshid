# Changelog

All notable changes to Murshid are recorded in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- A held-out split, `data/heldout/`: 68 questions, 25 red-team cases and 31 gold answers that the
  rules were not tuned on.
- `python -m murshid.bench --split tuned|heldout`: one split per run, each in its own folder, and
  a `run-manifest.json` per run (commit, model ids, dates, data hashes).
- Zero-key `extractive` (the default) and `replay` providers.
- `bench/rules-only/`: the frozen rules scored on the tuned split and on the held-out split, with
  `scripts/compare_splits.py` to report the two side by side.
- `docs/demo/index.html`: a static page of every recorded answer, built by
  `scripts/build_demo_page.py`; no script, no server, no model call.
- `--max-cost-usd`: a cap on a bench run's logged spend on paid models. Every paid call is
  logged to `spend-log.jsonl`, and the run manifest records the spend and the prices used.
- Typed settings read once, and one provider registry with dated prices.
- CI: lint, format, strict types, tests with an 80% coverage floor, a lockfile check, a Windows
  run, a REUSE licensing check, and the real-model tests weekly.
- A data card, a contributing guide, a code of conduct, a security policy, issue forms, a
  citation file, and SPDX licence headers.

### Changed

- Python 3.12 and uv; dependencies declared in `pyproject.toml` with extras; `uv.lock`.
- Gemini moved to the `google-genai` SDK; each provider has one SDK client with the SDK's own
  retries off, so `retry_call` is the only retry layer.
- The corpus's example web addresses moved to the reserved `.example` domain.
- The docs now say what the code does and what the recorded run shows: three providers ran, the
  critic is off by default and only removed correct answers in that run, and the judge's extra
  facts are "facts not in the gold answer", not hallucinations.
- The results page leaves the mock provider out of its tables.
- A run manifest's commit and dirty flag are read when the run starts, not after the run has
  written its results into tracked files.
- Gemini 2.5 Flash is priced from its price page as read on 2026-11-20 ($0.30 input, $2.50
  output per million tokens; the table had $0.075 and $0.30), and Claude Haiku 5.5 is listed.
- The system prompt's two few-shot examples no longer hold the answers to scored questions.

### Removed

- `requirements.txt`, the Falcon-Arabic provider stub, the empty `scripts/seed_bench.py`, and the
  committed `demo_output.txt` (the demo writes to `out/`).
- Nine vendored ToolKit cores that nothing used. Six remain: the four Murshid's code imports and
  the two that `hybrid_retrieval` imports.

## [0.1.0] - 2026-05-23

- First version: the retrieval pipeline over the synthetic corpus, the rule-based router,
  register detector and support gate, the critic, and the bench with its recorded run.

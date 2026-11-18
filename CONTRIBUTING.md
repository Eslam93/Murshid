# Contributing to Murshid

Thank you for helping. Murshid answers Arabic questions about government services, so the bar is
trust: an answer that invents a fee, a rule or a deadline is worse than no answer. Please read
this page before you open a pull request.

By taking part you agree to follow the [code of conduct](CODE_OF_CONDUCT.md). To report a security
problem, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Set up

You need [uv](https://docs.astral.sh/uv/). It reads `.python-version` and installs Python 3.12 for
you if it is missing.

```bash
git clone https://github.com/Eslam93/Murshid.git
cd Murshid
uv sync --all-extras
```

`uv sync --all-extras` creates `.venv` with the development tools and every optional extra:
`local-embed` (BGE-M3 embeddings through sentence-transformers and torch), `providers` (the
Anthropic, OpenAI and Google SDKs) and `ui` (the Gradio demo). Run everything through uv
(`uv run ...`) so the versions locked in `uv.lock` are the ones used. Add a dependency only with
`uv add`, `uv add --optional <extra>` or `uv add --dev`, so `pyproject.toml` and `uv.lock` stay in
step.

## Run the tests

```bash
uv run pytest                                     # fast tests
uv run pytest --real-embedder -m real_embedder    # tests that load the real BGE-M3 model
```

The real-model tests use the BAAI/bge-m3 weights, about 2.3 GB, which are downloaded into the
Hugging Face cache the first time they are needed.

## Quality gates

A pull request is ready when all five pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uvx --from "reuse[charset-normalizer]==6.3.0" reuse lint
```

The last one checks that every file states its copyright and licence, by the
[REUSE](https://reuse.software/) convention. A new Python file starts with an SPDX header naming
its author; `reuse annotate` writes it:

```bash
uvx --from "reuse[charset-normalizer]==6.3.0" reuse annotate --copyright "<your name>" --year 2026 --license MIT <file>
```

Files that take no comment are listed in `REUSE.toml`.

mypy runs in strict mode over `src/murshid`. New code is fully typed and tested. Use
`# noqa: <code>` or `# type: ignore[<code>]` only where a fix would be wrong, with the reason on
the same line.

## Secrets and paid APIs

- Never commit `.env` or a real API key. `.env` is gitignored: copy `.env.example` to `.env` for
  local runs. `.env.example` ships with empty key values and must stay that way.
- Tests never call a paid model API. Test a provider with a fake transport or a fake client.
- A bench run spends real money as soon as a key is set: its default providers include Claude and
  OpenAI, and it calls a paid judge whenever a judge's key is set. Choose the providers with
  `--providers` and read `uv run python -m murshid.bench --help` before you run it.
  `uv run python -m murshid.bench --render-only` rebuilds `bench/results.md` from the cached cases
  without calling any model.

## Propose an eval case

New eval cases are among the most useful contributions. Open an issue with the **Eval case**
template, or send a pull request that edits the data directly:

- A user question goes in `data/questions.json`; an adversarial case goes in
  `data/red_team.json`.
- Give the expected behavior: one of `answer`, `partial_answer_with_escalation`,
  `refuse_with_redirect` or `ask_clarification`.
- Give the register (`MSA`, `dialect` or `mixed`) and, for a dialect question, the dialect family.
- List the expected source IDs from `data/sources.json`, or none if the corpus should not answer
  the question.
- If you add a gold answer, copy every `quoted_passage` verbatim from its source.
- Keep the data synthetic: no real personal data, and no real fees, rules or reference numbers.

[data/README.md](data/README.md) describes every field and its allowed values. Held-out cases
are for measuring, not for tuning: never change a rule just to make a held-out case pass.

## Vendored ToolKit cores

`src/murshid/_toolkit/` holds byte-identical copies of cores from the ToolKit repository. Never
edit them in place: `tests/test_vendored_toolkit.py` checks every file against
`src/murshid/_toolkit/manifest.json`. If a core lacks something, wrap or extend it in Murshid's
own modules. To change a core itself, change it in the ToolKit and copy it again with
`tools/vendor_toolkit.py`. See [src/murshid/_toolkit/README.md](src/murshid/_toolkit/README.md).

## Commits and pull requests

- Keep commits focused. Write an imperative subject under 72 characters and a body that says what
  changed and why.
- Work through the checklist in the pull request template.
- Update the documentation (`README.md`, `docs/`, `data/README.md`) when behavior or data changes.

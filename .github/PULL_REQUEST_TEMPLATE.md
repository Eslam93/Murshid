## What and why

<!-- What does this change, and why? Link the issue it closes, if there is one. -->

## Checklist

- [ ] `uv run ruff check .` passes
- [ ] `uv run ruff format --check .` passes
- [ ] `uv run mypy` passes
- [ ] `uv run pytest` passes, and new or changed behavior has tests
- [ ] `uvx --from "reuse[charset-normalizer]==6.3.0" reuse lint` passes: new files carry an SPDX header
- [ ] No secrets: no `.env`, API key, token or real personal data in the diff, and no test calls a paid API
- [ ] Docs updated where behavior or data changed (`README.md`, `docs/`, `data/README.md`)
- [ ] Nothing under `src/murshid/_toolkit/` was edited by hand

# Python tooling: ruff, strict mypy, pytest, an 80% coverage floor

The Python gates as one configuration to paste into a project's `pyproject.toml`, and a check that
fails when one of them is weakened later.

## How to call it

1. Copy the tables in `tooling.toml` into your `pyproject.toml`; set your package names.
2. Keep them honest in your tests or CI:

```python
from toolkit.python_tooling.core import problems
import tomllib


def test_the_gates_are_all_there() -> None:
    assert problems(tomllib.loads(Path("pyproject.toml").read_text())) == []
```

or `python -m toolkit.python_tooling.core pyproject.toml` (exit 1 on a lost gate).

## What it requires

- ruff selects at least E, F, B (bugbear), S (bandit: security), UP (pyupgrade) and T20 (no
  print), or ALL;
- mypy `strict = true`;
- pytest `--strict-markers`, so a misspelled marker is an error, not a silent no-op;
- coverage `fail_under` of at least 80, and `branch = true`.

A gate switched off counts as lost, the same as one never selected:

- a ruff `ignore` or `extend-ignore` of a whole required family (`S`, `T20`, `ALL`), or a
  per-file ignore of one for a pattern that matches every file (`*`, `**`, `*.py`, `**/*`,
  `**/*.py`). A single rule (`S311`) or a narrower pattern (`**/tests/**`) is a deliberate
  exception and passes;
- mypy `ignore_errors = true`, at the top or in any override;
- a coverage `omit` (under `run` or `report`) that matches every file of a measured `source`
  package, such as `app/*` for `app`.

The fragment also sets pytest-asyncio to auto mode with one event loop per run, which every
toolkit core's async tests expect, and turns on greenlet measurement: with SQLAlchemy's async
layer, coverage otherwise loses every line after an await.

## When lifting, change

Package names and paths in the fragment. Raise the floor if you like; the check refuses lowering it.

Needs: the standard library (tomllib). Tests: `toolkit/python_tooling/tests/`.

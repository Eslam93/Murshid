# CI workflow: one workflow a stranger's pull request can run safely

A GitHub Actions workflow for a Python and TypeScript web app with PostgreSQL, and a check that
fails when a later edit makes the workflow unsafe for a public repository.

## How to call it

1. Copy `ci.template.yml` to `.github/workflows/ci.yml`. Change the names, the versions and the
   commands to your own.
2. Keep it honest in a test or in CI:

```python
from pathlib import Path

from toolkit.ci_workflow.core import problems


def test_ci_is_safe() -> None:
    assert problems(Path(".github/workflows/ci.yml").read_text()) == []
```

or `python -m toolkit.ci_workflow.core` (every file in `.github/workflows/`; exit 1, one line per
problem).

## What the template does

- **gate:** a PostgreSQL service that lives for one job, then lint, format, strict types, the
  tests with `REQUIRE_DB=1` (so a missing database fails instead of skipping), and the web app's
  lint, types, tests and build.
- **image:** builds the image, runs the migrations in it, starts it, and checks that readiness
  answers and `/` serves the web app from the same origin. The session secret is generated for
  the run and masked in the log, so it is never a stored secret.
- Triggers are `pull_request` and pushes to `main`; the token can only read; a newer push cancels
  the older run of the same branch.

## What the check refuses

- `pull_request_target` and `workflow_run`: they run with the repository's secrets and a write
  token on code a pull request controls;
- no top-level `permissions`, or any `write` permission;
- any `${{ secrets.* }}`, and `secrets: inherit`;
- `uses:` not pinned to a version tag or a full commit SHA (`@main` changes under you);
- `${{ github.event.* }}`, `${{ github.head_ref }}` or `${{ inputs.* }}` inside a `run:` script,
  where a crafted branch name or title becomes shell code; pass such a value through `env:`;
- a job without `timeout-minutes`.

A version tag can still be moved by the action's owner; pin to a SHA where that matters to you.

## When lifting, change

Names, the database role and password, the tool versions, and the commands in each step. The
database password in the template is a throwaway for a container that lives for one job, not a
secret.

Needs: pyyaml for the check. Tests: `toolkit/ci_workflow/tests/`.

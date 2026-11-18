"""A check that a GitHub Actions workflow is safe to run on a stranger's pull request.

    python -m toolkit.ci_workflow.core .github/workflows/ci.yml

Refuses:
- the `pull_request_target` and `workflow_run` triggers, which run with the repository's secrets
  and write token on code that a pull request can control;
- a workflow without top-level `permissions`, and any `write` permission, top-level or per job;
- any use of `secrets.` (including `secrets: inherit`): no job of a public-ready CI needs one;
- `uses:` not pinned to a version tag (v4, v4.1.2) or a full commit SHA; a branch such as
  `@main` changes under you. Local actions (`./...`) are exempt; `docker://` needs a tag;
- `${{ github.event.* }}`, `${{ github.head_ref }}` or `${{ inputs.* }}` inside a `run:` script,
  where a crafted branch name or title becomes shell code; pass it through `env:` instead;
- a job without `timeout-minutes`, which otherwise can run for six hours.

Exit 0 when clean, 1 with one line per finding. Needs pyyaml.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

__all__ = ["FORBIDDEN_TRIGGERS", "main", "problems"]

FORBIDDEN_TRIGGERS = ("pull_request_target", "workflow_run")

_PINNED = re.compile(r"@(v\d+(\.\d+){0,2}|[0-9a-f]{40})$")
_SECRETS = re.compile(r"\$\{\{[^}]*\bsecrets\.")
_INJECTION = re.compile(r"\$\{\{\s*(github\.event\.|github\.head_ref|inputs\.)")


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, Mapping):
        for key, value in node.items():
            yield str(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


def _triggers(document: Mapping[Any, Any]) -> list[str]:
    # YAML 1.1 reads a bare `on` key as the boolean true.
    on = document.get("on", document.get(True))
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(item) for item in on]
    if isinstance(on, Mapping):
        return [str(key) for key in on]
    return []


def _permission_problems(where: str, permissions: Any) -> Iterator[str]:
    if isinstance(permissions, str):
        if permissions not in ("read-all", "none"):
            yield f"{where}: permissions {permissions} grants write"
        return
    for scope, level in (permissions or {}).items():
        if level not in ("read", "none"):
            yield f"{where}: permission {scope}: {level} grants write"


def _uses_problem(uses: str) -> str | None:
    if uses.startswith("./"):
        return None
    if uses.startswith("docker://"):
        image = uses.removeprefix("docker://").rsplit("/", 1)[-1]
        ok = ("@sha256:" in uses) or (":" in image and not image.endswith(":latest"))
        return None if ok else f"uses {uses} has no pinned tag"
    return None if _PINNED.search(uses) else f"uses {uses} is not pinned to a version or a SHA"


def _job_problems(name: str, job: Mapping[str, Any]) -> Iterator[str]:
    where = f"job {name}"
    if "permissions" in job:
        yield from _permission_problems(where, job["permissions"])
    if "timeout-minutes" not in job:
        yield f"{where}: no timeout-minutes"
    if isinstance(job.get("uses"), str) and (found := _uses_problem(job["uses"])):
        yield f"{where}: {found}"
    for number, step in enumerate(job.get("steps") or [], start=1):
        label = f"{where}, step {step.get('name') or number}"
        if isinstance(step.get("uses"), str) and (found := _uses_problem(step["uses"])):
            yield f"{label}: {found}"
        if isinstance(step.get("run"), str) and _INJECTION.search(step["run"]):
            yield f"{label}: puts event data straight into the script; pass it through env"


def problems(text: str) -> list[str]:
    """One line per problem in a workflow's text; empty when it is clean."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return [f"not valid YAML: {error}"]
    if not isinstance(document, Mapping) or not isinstance(document.get("jobs"), Mapping):
        return ["no jobs"]
    found = [
        f"trigger {t} runs with secrets on code a pull request controls"
        for t in _triggers(document)
        if t in FORBIDDEN_TRIGGERS
    ]
    if "permissions" not in document:
        found.append("no top-level permissions: the token gets the repository's default")
    else:
        found += _permission_problems("workflow", document["permissions"])
    if any(_SECRETS.search(s) for s in _strings(document)) or "inherit" in (
        str(job.get("secrets")) for job in document["jobs"].values()
    ):
        found.append("uses secrets: a stranger's pull request must be able to run every job")
    for name, job in document["jobs"].items():
        found += _job_problems(str(name), job or {})
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    paths = [Path(a) for a in args] or sorted(Path(".github/workflows").glob("*.y*ml"))
    if not paths:
        sys.stderr.write("no workflow files found\n")
        return 1
    failed = False
    for path in paths:
        for line in problems(path.read_text(encoding="utf-8")):
            sys.stderr.write(f"{path}: {line}\n")
            failed = True
    return 1 if failed else 0

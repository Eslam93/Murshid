# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Delivery checks: the CI workflows.

The vendored C71 check keeps CI safe to run on a stranger's pull request. These tests add what
Murshid relies on: the exact gate commands, the Windows run, and the heavy real-model job kept
off pull requests.

Nothing here runs a workflow: they are read as text and YAML.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from murshid._toolkit.ci_workflow.core import problems as workflow_problems

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))

# What the gate job runs, in order: the same commands a contributor runs before a pull request.
GATE_COMMANDS = [
    "uv sync --frozen --extra providers",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run mypy",
    "uv run pytest --cov",
]
REAL_EMBEDDER_TESTS = "uv run pytest --real-embedder -m real_embedder"
# Every file states its copyright and licence; the version and the extra are pinned.
REUSE_LINT = 'uvx --from "reuse[charset-normalizer]==6.3.0" reuse lint'
# No workflow needs a provider key: the paid providers are tested with fakes.
KEY_NAME = re.compile(r"\w*API_KEY\b|\bHF_TOKEN\b|\bHUGGING_FACE_HUB_TOKEN\b")


# ---- reading the workflows ---------------------------------------------------------------------


def _workflow(path: Path) -> dict[Any, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path.name} is not a workflow"
    return document


def _on(document: dict[Any, Any]) -> Any:
    """The workflow's `on:` block. YAML 1.1 reads a bare `on` key as the boolean true."""
    return document["on"] if "on" in document else document[True]


def _triggers(document: dict[Any, Any]) -> set[str]:
    on = _on(document)
    if isinstance(on, str):
        return {on}
    return {str(event) for event in on}


def _jobs() -> Iterator[tuple[dict[Any, Any], dict[str, Any]]]:
    """(workflow, job) for every job of every workflow."""
    for path in WORKFLOWS:
        document = _workflow(path)
        for job in document["jobs"].values():
            yield document, job


def _runs(job: dict[str, Any]) -> list[str]:
    return [str(step["run"]).strip() for step in job.get("steps", []) if "run" in step]


def _uses(job: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [step for step in job.get("steps", []) if str(step.get("uses", "")).startswith(action)]


# ---- the check the ToolKit ships ---------------------------------------------------------------


def test_the_workflows_are_there() -> None:
    assert {path.name for path in WORKFLOWS} >= {"ci.yml", "real-model.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_every_workflow_passes_the_ci_check(path: Path) -> None:
    assert workflow_problems(path.read_text(encoding="utf-8")) == []


# ---- CI ----------------------------------------------------------------------------------------


def test_ci_runs_on_pushes_to_main_and_on_pull_requests() -> None:
    document = _workflow(ROOT / ".github" / "workflows" / "ci.yml")
    assert _triggers(document) == {"push", "pull_request"}
    assert _on(document)["push"] == {"branches": ["main"]}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_every_workflow_cancels_the_run_a_newer_one_replaces(path: Path) -> None:
    concurrency = _workflow(path)["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "${{ github.ref }}" in concurrency["group"]


def test_the_gate_runs_exactly_the_quality_gates() -> None:
    gate = _workflow(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["gate"]
    assert gate["runs-on"] == "ubuntu-24.04"
    assert _runs(gate) == GATE_COMMANDS


def test_the_fast_tests_also_run_on_windows() -> None:
    jobs = _workflow(ROOT / ".github" / "workflows" / "ci.yml")["jobs"].values()
    windows = [job for job in jobs if job["runs-on"] == "windows-latest"]
    assert len(windows) == 1
    assert _runs(windows[0]) == ["uv sync --frozen --extra providers", "uv run pytest"]


def test_ci_lints_copyright_and_licensing_with_reuse() -> None:
    jobs = _workflow(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]
    assert _runs(jobs["licensing"]) == [REUSE_LINT]


def test_the_real_embedder_tests_run_weekly_and_by_hand_only() -> None:
    found = [(document, job) for document, job in _jobs() if REAL_EMBEDDER_TESTS in _runs(job)]
    assert len(found) == 1, "one job runs the tests that need the real weights"
    document, job = found[0]
    assert _triggers(document) == {"workflow_dispatch", "schedule"}
    assert _runs(job) == ["uv sync --frozen --all-extras", REAL_EMBEDDER_TESTS]
    (cache,) = _uses(job, "actions/cache@")
    assert cache["with"]["path"] == "~/.cache/huggingface"
    assert "BAAI-bge-m3" in cache["with"]["key"], "the weights' cache is keyed on the model id"


def test_uv_is_pinned_to_one_version_everywhere() -> None:
    pins = {
        str(step.get("with", {}).get("version"))
        for _, job in _jobs()
        for step in _uses(job, "astral-sh/setup-uv@")
    }
    assert len(pins) == 1, f"one uv for every job, not {sorted(pins)}"
    assert re.fullmatch(r"\d+\.\d+\.\d+", pins.pop())


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_no_workflow_names_a_key(path: Path) -> None:
    assert KEY_NAME.findall(path.read_text(encoding="utf-8")) == []

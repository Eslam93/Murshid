"""The workflow check on the template it ships and on workflows that break one rule each."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from murshid._toolkit.ci_workflow.core import main, problems

TEMPLATE = (Path(__file__).resolve().parents[1] / "core" / "ci.template.yml").read_text()


def test_the_template_is_clean() -> None:
    assert problems(TEMPLATE) == []


@pytest.mark.parametrize(
    ("change", "finding"),
    [
        (("  pull_request:\n", "  pull_request_target:\n"), "trigger pull_request_target runs"),
        (("  pull_request:\n", "  workflow_run:\n"), "trigger workflow_run runs"),
        (("permissions:\n  contents: read\n", ""), "no top-level permissions"),
        (("  contents: read\n", "  contents: write\n"), "permission contents: write grants write"),
        (
            ("permissions:\n  contents: read\n", "permissions: write-all\n"),
            "write-all grants write",
        ),
        (
            (
                "    timeout-minutes: 30\n",
                "    timeout-minutes: 30\n    permissions:\n      pull-requests: write\n",
            ),
            "job gate: permission pull-requests: write grants write",
        ),
        (('REQUIRE_DB: "1"', "TOKEN: ${{ secrets.NPM_TOKEN }}"), "uses secrets"),
        (
            (
                "actions/checkout@v4\n      - uses: astral",
                "actions/checkout@main\n      - uses: astral",
            ),
            "uses actions/checkout@main is not pinned",
        ),
        (("pnpm/action-setup@v4", "pnpm/action-setup"), "uses pnpm/action-setup is not pinned"),
        (("    timeout-minutes: 20\n", ""), "job image: no timeout-minutes"),
        (
            (
                "      - run: uv sync --frozen\n",
                "      - run: echo ${{ github.event.pull_request.title }}\n",
            ),
            "puts event data straight into the script",
        ),
        (
            (
                "      - run: uv sync --frozen\n",
                "      - run: git checkout ${{ github.head_ref }}\n",
            ),
            "puts event data straight into the script",
        ),
    ],
)
def test_each_broken_rule_is_named(change: tuple[str, str], finding: str) -> None:
    broken = TEMPLATE.replace(*change, 1)
    assert broken != TEMPLATE
    found = problems(broken)
    assert any(finding in line for line in found), found


def test_what_is_allowed() -> None:
    text = """
on: [push, pull_request]
permissions: {}
jobs:
  a:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    env:
      TITLE: ${{ github.event.pull_request.title }}
    steps:
      - uses: ./.github/actions/local
      - uses: docker://alpine:3.20
      - uses: actions/cache@0123456789abcdef0123456789abcdef01234567
      - run: echo "$TITLE" and ${{ github.sha }}
"""
    assert problems(text) == []


def test_reusable_workflows_and_images() -> None:
    text = """
on: pull_request
permissions: read-all
jobs:
  a:
    timeout-minutes: 5
    uses: org/repo/.github/workflows/x.yml@main
    secrets: inherit
  b:
    timeout-minutes: 5
    steps:
      - uses: docker://alpine
"""
    assert problems(text) == [
        "uses secrets: a stranger's pull request must be able to run every job",
        "job a: uses org/repo/.github/workflows/x.yml@main is not pinned to a version or a SHA",
        "job b, step 1: uses docker://alpine has no pinned tag",
    ]


def test_not_a_workflow() -> None:
    assert problems("name: x") == ["no jobs"]
    assert problems("jobs: [")[0].startswith("not valid YAML")


def test_runs_as_a_module(tmp_path: Path) -> None:
    good, bad = tmp_path / "ci.yml", tmp_path / "bad.yml"
    good.write_text(TEMPLATE)
    bad.write_text(TEMPLATE.replace("  pull_request:\n", "  pull_request_target:\n"))
    root = Path(__file__).resolve().parents[3]  # the folder that holds toolkit/
    run = [sys.executable, "-W", "error", "-m", "murshid._toolkit.ci_workflow.core"]
    clean = subprocess.run([*run, str(good)], cwd=root, capture_output=True, text=True, check=False)
    assert (clean.returncode, clean.stderr) == (0, "")
    broken = subprocess.run([*run, str(bad)], cwd=root, capture_output=True, text=True, check=False)
    assert broken.returncode == 1
    assert f"{bad}: trigger pull_request_target runs" in broken.stderr
    assert main([str(good)]) == 0

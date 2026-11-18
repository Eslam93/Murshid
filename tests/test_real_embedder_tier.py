# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""The --real-embedder tier in the root conftest.py.

A test marked `real_embedder` is skipped, with a reason that names the option, unless pytest gets
`--real-embedder`; unmarked tests run either way. Exercised with pytester on a copy of the real
conftest, so no model is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

ROOT_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"

_TWO_TESTS = """
import pytest


@pytest.mark.real_embedder
def test_builds_the_real_index():
    pass


def test_needs_no_model():
    pass
"""


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
    pytester.makeini(
        "[pytest]\n"
        # The inner project has no async tests, so pytest-asyncio stays out of it.
        "addopts = --strict-markers -p no:asyncio\n"
        "markers =\n"
        "    real_embedder: needs the real BGE-M3 weights\n"
    )
    pytester.makepyfile(test_two=_TWO_TESTS)
    return pytester


def test_a_plain_run_skips_the_marked_test_and_says_how_to_run_it(
    project: pytest.Pytester,
) -> None:
    result = project.runpytest("-rs")
    result.assert_outcomes(passed=1, skipped=1)
    result.stdout.fnmatch_lines(["*test_two.py*run with --real-embedder*"])


def test_the_option_runs_the_marked_test_too(project: pytest.Pytester) -> None:
    result = project.runpytest("--real-embedder")
    result.assert_outcomes(passed=2)

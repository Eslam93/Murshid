# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""pyproject.toml keeps every Python quality gate.

The vendored C68 check refuses a configuration that has lost a gate: ruff without the security,
bugbear, pyupgrade or no-print rules (or ignoring one of them for every file), mypy that is not
strict or ignores errors, pytest that accepts unknown markers, and coverage below 80% or without
branch measurement. Narrow exceptions, such as a per-file T201 for a command-line entry point,
still pass.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from murshid._toolkit.python_tooling.core import problems

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_pyproject_keeps_every_quality_gate() -> None:
    assert problems(tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))) == []

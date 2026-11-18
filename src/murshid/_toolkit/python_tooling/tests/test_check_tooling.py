"""The tooling check against the fragment it ships and against weakened copies of it."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from murshid._toolkit.python_tooling.core import main, problems

FRAGMENT = Path(__file__).resolve().parents[1] / "core" / "tooling.toml"


def fragment() -> dict[str, Any]:
    return tomllib.loads(FRAGMENT.read_text())


def test_the_shipped_fragment_keeps_every_gate() -> None:
    assert problems(fragment()) == []


def test_every_lost_gate_is_named() -> None:
    config = fragment()
    config["tool"]["ruff"]["lint"]["select"] = ["E", "F"]
    config["tool"]["mypy"]["strict"] = False
    config["tool"]["pytest"]["ini_options"]["addopts"] = "-ra"
    config["tool"]["coverage"]["report"]["fail_under"] = 60
    del config["tool"]["coverage"]["run"]["branch"]
    assert problems(config) == [
        "ruff does not select B, S, T20, UP",
        "mypy is not strict",
        "pytest accepts unknown markers (add --strict-markers)",
        "coverage has no floor of at least 80%",
        "coverage does not measure branches",
    ]


def test_an_empty_configuration_has_every_problem() -> None:
    assert len(problems({})) == 5


def test_ruff_all_counts_as_every_rule() -> None:
    config = fragment()
    config["tool"]["ruff"]["lint"]["select"] = ["ALL"]
    assert problems(config) == []


def test_the_command_line_exits_1_and_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    weak = tmp_path / "pyproject.toml"
    weak.write_text("[tool.mypy]\nstrict = false\n")
    assert main([str(weak)]) == 1
    assert f"{weak}: mypy is not strict" in capsys.readouterr().err
    assert main([str(FRAGMENT)]) == 0


def test_runs_as_a_module_and_says_nothing_when_clean() -> None:
    root = Path(__file__).resolve().parents[3]  # the folder that holds toolkit/
    run = [sys.executable, "-W", "error", "-m", "murshid._toolkit.python_tooling.core", str(FRAGMENT)]
    result = subprocess.run(run, cwd=root, capture_output=True, text=True, check=False)
    assert (result.returncode, result.stderr) == (0, "")


# A gate can also be lost by switching it off rather than by not selecting it: an ignore, a
# per-file ignore for every file, mypy's ignore_errors, or a coverage omit that takes a whole
# package out of the measure.


def test_an_ignore_of_a_required_family_is_a_lost_gate() -> None:
    config = fragment()
    config["tool"]["ruff"]["lint"]["ignore"] = ["S", "B"]
    config["tool"]["ruff"]["lint"]["extend-ignore"] = ["T20"]
    assert problems(config) == ["ruff ignores B, S, T20 for every file"]


def test_a_per_file_ignore_for_every_file_is_a_lost_gate() -> None:
    config = fragment()
    config["tool"]["ruff"]["lint"]["per-file-ignores"]["**/*.py"] = ["UP"]
    assert problems(config) == ["ruff ignores UP for every file"]
    config = fragment()
    config["tool"]["ruff"]["lint"]["ignore"] = ["ALL"]
    assert problems(config) == ["ruff ignores B, E, F, S, T20, UP for every file"]


def test_a_narrow_ignore_keeps_the_gates() -> None:
    config = fragment()
    config["tool"]["ruff"]["lint"]["ignore"] = ["S311", "B008"]
    config["tool"]["ruff"]["lint"]["per-file-ignores"]["scripts/**"] = ["T20"]
    assert problems(config) == []


def test_mypy_ignore_errors_is_a_lost_gate() -> None:
    config = fragment()
    config["tool"]["mypy"]["ignore_errors"] = True
    assert problems(config) == ["mypy ignores errors"]
    config = fragment()
    config["tool"]["mypy"]["overrides"] = [{"module": ["app.*"], "ignore_errors": True}]
    assert problems(config) == ["mypy ignores errors in app.*"]


def test_a_coverage_omit_of_a_whole_package_is_a_lost_gate() -> None:
    config = fragment()
    config["tool"]["coverage"]["run"]["source"] = ["app", "toolkit"]
    config["tool"]["coverage"]["run"]["omit"] = ["*/tests/*", "app/web/*"]
    assert problems(config) == []
    config["tool"]["coverage"]["run"]["omit"] = ["app/*"]
    assert problems(config) == ["coverage omits every file of app"]
    config["tool"]["coverage"]["report"]["omit"] = ["*.py"]
    assert problems(config) == [
        "coverage omits every file of app",
        "coverage omits every file of toolkit",
    ]


# One run over several cores must run every core's own files. Two cores that both keep a
# tests/__init__.py and a test_lift.py are the case that went wrong: each file was named
# `tests.test_lift`, so the second core's file ran the first core's tests, and the run stayed green.


def _two_cores(root: Path, pytest_table: dict[str, Any]) -> None:
    for core in ("loans", "fines"):
        tests = root / "toolkit" / core / "tests"
        tests.mkdir(parents=True)
        (tests / "__init__.py").write_text("")
        (tests / "test_lift.py").write_text(f"def test_{core}_lifts() -> None:\n    pass\n")
    lines = ["[tool.pytest.ini_options]"]
    for key, value in pytest_table.items():
        if key.startswith("asyncio_"):
            continue  # pytest-asyncio's keys; the case needs no async test
        rendered = repr(value).replace("'", '"').replace("True", "true").replace("False", "false")
        lines.append(f"{key} = {rendered}")
    (root / "pyproject.toml").write_text("\n".join(lines) + "\n")


def _collected(root: Path) -> list[str]:
    run = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
    result = subprocess.run(run, cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return sorted(line for line in result.stdout.splitlines() if "::" in line)


def test_one_run_over_two_cores_runs_each_cores_own_test_file(tmp_path: Path) -> None:
    _two_cores(tmp_path, fragment()["tool"]["pytest"]["ini_options"])
    assert _collected(tmp_path) == [
        "toolkit/fines/tests/test_lift.py::test_fines_lifts",
        "toolkit/loans/tests/test_lift.py::test_loans_lifts",
    ]


def test_without_namespace_packages_one_core_runs_the_others_file(tmp_path: Path) -> None:
    # The control: the same two cores without the setting collect one core's test twice.
    table = dict(fragment()["tool"]["pytest"]["ini_options"])
    del table["consider_namespace_packages"]
    _two_cores(tmp_path, table)
    collected = _collected(tmp_path)
    assert len(collected) == 2
    assert len({line.split("::")[1] for line in collected}) == 1

"""A check that a project's pyproject.toml keeps its Python gates.

    python -m toolkit.python_tooling.core [path/to/pyproject.toml]

Refuses a configuration that has lost a gate: ruff without the security, bugbear, pyupgrade or
no-print rules, mypy that is not strict, pytest that accepts unknown markers, or coverage below
80% or without branches. A gate switched off counts as lost too: an ignore of a whole required
rule family (globally, or per file for a pattern that matches every file), mypy's ignore_errors,
and a coverage omit that matches every file of a measured package. Exit 0 when every gate is
there, 1 with one line per missing gate.
"""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Iterator, Mapping
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

__all__ = ["REQUIRED_RUFF_RULES", "main", "problems"]

REQUIRED_RUFF_RULES = frozenset({"E", "F", "B", "S", "UP", "T20"})
MIN_COVERAGE = 80
# Per-file patterns that match every Python file. A narrower pattern is a deliberate exception.
_EVERY_FILE = frozenset({"*", "**", "*.py", "**/*", "**/*.py"})


def _table(config: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    node: Any = config
    for key in path:
        node = node.get(key, {}) if isinstance(node, Mapping) else {}
    return node if isinstance(node, Mapping) else {}


def problems(config: Mapping[str, Any]) -> list[str]:
    """Every gate the configuration has lost, one line each."""
    found: list[str] = []
    selected = set(_table(config, "tool", "ruff", "lint").get("select", []))
    missing = set() if "ALL" in selected else REQUIRED_RUFF_RULES - selected
    if missing:
        found.append(f"ruff does not select {', '.join(sorted(missing))}")
    ignored = set(_ruff_ignores(config))
    # An ignored code switches off every rule it is a prefix of; ALL is a prefix of all of them.
    prefixes = ("",) if "ALL" in ignored else tuple(ignored)
    lost = {rule for rule in REQUIRED_RUFF_RULES - missing if rule.startswith(prefixes)}
    if lost:
        found.append(f"ruff ignores {', '.join(sorted(lost))} for every file")
    mypy = _table(config, "tool", "mypy")
    if mypy.get("strict") is not True:
        found.append("mypy is not strict")
    if mypy.get("ignore_errors") is True:
        found.append("mypy ignores errors")
    for override in mypy.get("overrides", []):
        if isinstance(override, Mapping) and override.get("ignore_errors") is True:
            modules = override.get("module", [])
            names = [modules] if isinstance(modules, str) else modules
            found.append(f"mypy ignores errors in {', '.join(map(str, names))}")
    addopts = _table(config, "tool", "pytest", "ini_options").get("addopts", [])
    if isinstance(addopts, str):
        addopts = addopts.split()
    if "--strict-markers" not in addopts:
        found.append("pytest accepts unknown markers (add --strict-markers)")
    floor = _table(config, "tool", "coverage", "report").get("fail_under")
    if not isinstance(floor, int | float) or floor < MIN_COVERAGE:
        found.append(f"coverage has no floor of at least {MIN_COVERAGE}%")
    if _table(config, "tool", "coverage", "run").get("branch") is not True:
        found.append("coverage does not measure branches")
    omit = [
        str(pattern)
        for section in ("run", "report")
        for pattern in _table(config, "tool", "coverage", section).get("omit", [])
    ]
    for source in _table(config, "tool", "coverage", "run").get("source", ["."]):
        # A pattern that matches a module at the top of the package and one a level down takes
        # the whole package out of the measure.
        top = "" if str(source) in {".", ""} else f"{source}/"
        if any(fnmatch(f"{top}m.py", p) and fnmatch(f"{top}sub/m.py", p) for p in omit):
            found.append(f"coverage omits every file of {source}")
    return found


def _ruff_ignores(config: Mapping[str, Any]) -> Iterator[str]:
    """Every rule code ruff ignores for every file, from both the current and the legacy keys."""
    for table in (_table(config, "tool", "ruff"), _table(config, "tool", "ruff", "lint")):
        for key in ("ignore", "extend-ignore"):
            yield from map(str, table.get(key, []))
        for key in ("per-file-ignores", "extend-per-file-ignores"):
            for pattern, codes in _table(table, key).items():
                if pattern.removeprefix("./") in _EVERY_FILE:
                    yield from map(str, codes)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0] if args else "pyproject.toml")
    found = problems(tomllib.loads(path.read_text(encoding="utf-8")))
    for line in found:
        sys.stderr.write(f"{path}: {line}\n")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())

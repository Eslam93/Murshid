"""Determinism, golden-file and invariant checks for code whose output must not drift.

Three questions a matching engine, a forecast or a report builder must answer the same way every
time:

- Is it deterministic? `assert_deterministic` runs it several times and compares the results in a
  canonical JSON form; `assert_order_independent` shuffles its input and compares again, because
  code that depends on the order rows arrive in gives a different answer on another database.
- Has its output changed? `Golden(folder).check(name, value)` compares the value with a committed
  JSON file. A missing or different file fails with the difference; setting `GOLDEN_UPDATE=1`
  writes the file instead, for a change a person has checked.
- Does it keep its rules? `broken_invariants(value, rules)` names each rule a result breaks
  ("the matched amounts add up to the invoice total"), for property-style tests over many inputs.

The canonical form sorts keys, writes decimals as their exact text and dates in ISO form, turns
dataclasses into objects and sets into sorted lists, so two equal results always print the same.
"""

from __future__ import annotations

import dataclasses
import difflib
import json
import os
import random
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

__all__ = [
    "UPDATE_ENV",
    "Golden",
    "assert_deterministic",
    "assert_order_independent",
    "broken_invariants",
    "canonical_json",
]

T = TypeVar("T")
UPDATE_ENV = "GOLDEN_UPDATE"


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(item) for item in value), key=lambda item: json.dumps(item))
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def canonical_json(value: Any) -> str:
    """The value as JSON that is the same for every equal value."""
    return json.dumps(_plain(value), sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _difference(expected: str, actual: str, label: str) -> str:
    lines = difflib.unified_diff(
        expected.splitlines(),
        actual.splitlines(),
        f"{label} (expected)",
        f"{label} (actual)",
        lineterm="",
    )
    return "\n".join(list(lines)[:60])


def assert_deterministic(
    function: Callable[..., Any], *args: Any, runs: int = 3, **kwargs: Any
) -> Any:
    """Calls the function `runs` times and fails when two results differ. Returns the result."""
    first = function(*args, **kwargs)
    expected = canonical_json(first)
    for run in range(2, runs + 1):
        actual = canonical_json(function(*args, **kwargs))
        if actual != expected:
            raise AssertionError(
                f"run {run} differs from run 1:\n" + _difference(expected, actual, "result")
            )
    return first


def assert_order_independent(
    function: Callable[[list[T]], Any], items: Sequence[T], *, runs: int = 5, seed: int = 0
) -> Any:
    """Calls the function on `runs` shuffles of the items and fails when a result differs from
    the one for the items in their given order."""
    rng = random.Random(seed)  # noqa: S311 - a shuffle for a test, not a secret
    expected = canonical_json(function(list(items)))
    for run in range(1, runs + 1):
        shuffled = list(items)
        rng.shuffle(shuffled)
        actual = canonical_json(function(shuffled))
        if actual != expected:
            raise AssertionError(
                f"shuffle {run} changes the result:\n" + _difference(expected, actual, "result")
            )
    return function(list(items))


class Golden:
    """Committed JSON files that a value must equal."""

    def __init__(self, folder: Path, *, env: Mapping[str, str] | None = None) -> None:
        self.folder = folder
        self._env = os.environ if env is None else env

    def check(self, name: str, value: Any) -> None:
        path = self.folder / f"{name}.json"
        actual = canonical_json(value)
        if self._env.get(UPDATE_ENV, "").strip() == "1":
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8")
            return
        if not path.exists():
            raise AssertionError(f"no golden file {path.name}: run once with {UPDATE_ENV}=1")
        expected = path.read_text(encoding="utf-8")
        if expected != actual:
            raise AssertionError(
                f"{path.name} differs; if the change is right, run with {UPDATE_ENV}=1:\n"
                + _difference(expected, actual, path.name)
            )


def broken_invariants(value: T, rules: Mapping[str, Callable[[T], bool]]) -> list[str]:
    """The names of the rules the value breaks, in the order given. A rule that raises is broken."""
    broken: list[str] = []
    for name, rule in rules.items():
        try:
            holds = rule(value)
        except Exception:
            holds = False
        if not holds:
            broken.append(name)
    return broken

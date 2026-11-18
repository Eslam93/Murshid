"""The determinism, golden and invariant helpers, with small functions of their own."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from murshid._toolkit.golden_tests.core import (
    UPDATE_ENV,
    Golden,
    assert_deterministic,
    assert_order_independent,
    broken_invariants,
    canonical_json,
)


@dataclass(frozen=True)
class Match:
    invoice: str
    amounts: tuple[Decimal, ...]
    on: date


def test_equal_values_print_the_same_canonical_json() -> None:
    one = {"b": Decimal("1.50"), "a": {3, 1, 2}, "on": date(2026, 3, 1)}
    two = {"on": date(2026, 3, 1), "a": {2, 3, 1}, "b": Decimal("1.50")}
    assert canonical_json(one) == canonical_json(two)
    assert '"b": "1.50"' in canonical_json(one)
    assert canonical_json(Match("INV-1", (Decimal(1),), date(2026, 1, 2))).count("INV-1") == 1


def test_uuids_print_as_text() -> None:
    value = {"id": uuid.UUID("00000000-0000-4000-8000-000000000001")}
    assert canonical_json(value) == '{\n  "id": "00000000-0000-4000-8000-000000000001"\n}\n'


def test_a_deterministic_function_passes_and_returns_its_result() -> None:
    assert assert_deterministic(sorted, [3, 1, 2]) == [1, 2, 3]


def test_a_function_with_hidden_state_is_caught() -> None:
    counter = itertools.count()
    with pytest.raises(AssertionError, match="run 2 differs from run 1"):
        assert_deterministic(lambda: {"id": next(counter)})


def test_a_result_that_depends_on_input_order_is_caught() -> None:
    def total(rows: list[Decimal]) -> str:
        return str(sum(rows, Decimal(0)))

    def first_wins(rows: list[str]) -> str:
        return rows[0]

    assert_order_independent(total, [Decimal("1.1"), Decimal("2.2"), Decimal("3.3")])
    with pytest.raises(AssertionError, match="changes the result"):
        assert_order_independent(first_wins, ["a", "b", "c", "d"])


def test_a_golden_file_is_written_on_request_and_then_held(tmp_path: Path) -> None:
    value = {"total": Decimal("10.00"), "lines": [1, 2]}
    with pytest.raises(AssertionError, match=r"no golden file totals\.json"):
        Golden(tmp_path, env={}).check("totals", value)
    Golden(tmp_path, env={UPDATE_ENV: "1"}).check("totals", value)
    Golden(tmp_path, env={}).check("totals", value)
    with pytest.raises(AssertionError, match=r'(?s)totals.json differs.*-  "total": "10.00"'):
        Golden(tmp_path, env={}).check("totals", {**value, "total": Decimal("10.01")})


def test_broken_invariants_are_named_in_order() -> None:
    match = Match("INV-1", (Decimal(4), Decimal(6)), date(2026, 3, 1))
    rules = {
        "amounts add up to ten": lambda m: sum(m.amounts) == 10,
        "there are three amounts": lambda m: len(m.amounts) == 3,
        "a rule that raises": lambda m: m.missing > 0,
    }
    assert broken_invariants(match, rules) == ["there are three amounts", "a rule that raises"]

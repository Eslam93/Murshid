"""The canonical form and the digest: stable for the same content, different for any change."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

import pytest

from murshid._toolkit.tamper_evident.core import canonical_json, digest, matches


class Status(Enum):
    SUBMITTED = "submitted"


REQUEST = {
    "id": uuid.UUID("0b6f5a2e-8a3c-4d1b-9f7e-2c1d0e9a8b7c"),
    "title": "Standing desks",
    "cost_centre": "OPS",
    "currency": "SAR",
    "needed_by": date(2026, 12, 1),
    "status": Status.SUBMITTED,
    "lines": [
        {
            "description": "Standing desk",
            "quantity": Decimal("2.000"),
            "unit_price": Decimal("900"),
        },
        {"description": "مكتب قائم", "quantity": Decimal("1"), "unit_price": Decimal("450.50")},
    ],
    "total": Decimal("2250.50"),
}
# The canonical form of REQUEST, written out by hand, and its SHA-256 computed from that text with
# `sha256sum`, not by this code. A change to the form (key order, number text, separators) changes
# every stored digest, so it must fail here first.
GOLDEN_TEXT = (
    '{"cost_centre":"OPS","currency":"SAR","id":"0b6f5a2e-8a3c-4d1b-9f7e-2c1d0e9a8b7c",'
    '"lines":[{"description":"Standing desk","quantity":"2","unit_price":"900"},'
    '{"description":"مكتب قائم","quantity":"1","unit_price":"450.5"}],'
    '"needed_by":"2026-12-01","status":"submitted","title":"Standing desks","total":"2250.5"}'
)
GOLDEN = "sha256:e0f34996a0293d0fc84d0101df3daec68ae21169d72375bce1907067092cbb49"


def test_the_canonical_form_is_one_byte_string() -> None:
    assert canonical_json(REQUEST).decode("utf-8") == GOLDEN_TEXT


def test_the_digest_of_a_fixed_request_is_pinned() -> None:
    assert digest(REQUEST) == digest(dict(reversed(list(REQUEST.items()))))
    assert digest(REQUEST).startswith("sha256:") and len(digest(REQUEST)) == 7 + 64
    assert digest(REQUEST) == GOLDEN


def test_equal_amounts_written_differently_give_one_digest() -> None:
    assert digest({"a": Decimal("1.50")}) == digest({"a": Decimal("1.5")})
    assert digest({"a": Decimal("0.00")}) == digest({"a": Decimal("-0")})
    assert digest({"a": Decimal("1E+3")}) == digest({"a": Decimal("1000")})


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Standing desk"},
        {"total": Decimal("2250.51")},
        {"needed_by": date(2026, 12, 2)},
        {"lines": list(reversed(REQUEST["lines"]))},  # type: ignore[call-overload]
        {"extra": None},
    ],
)
def test_any_change_gives_another_digest(change: dict[str, object]) -> None:
    changed = {**REQUEST, **change}
    assert not matches(changed, digest(REQUEST))
    assert matches(REQUEST, digest(REQUEST))


def test_values_without_one_exact_text_are_refused() -> None:
    with pytest.raises(TypeError, match="float"):
        digest({"a": 1.5})
    with pytest.raises(ValueError, match="timezone"):
        digest({"at": datetime(2026, 9, 27, 9, 0)})
    with pytest.raises(ValueError, match="infinite"):
        digest({"a": Decimal("Infinity")})
    with pytest.raises(TypeError, match="keys"):
        digest({1: "a"})
    with pytest.raises(TypeError, match="set"):
        digest({"a": {1, 2}})
    assert digest({"at": datetime(2026, 9, 27, 9, 0, tzinfo=UTC)}).startswith("sha256:")

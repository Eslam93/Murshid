"""Tamper-evident records: a decision commits to a hash of the exact version it was made on.

`canonical_json` writes a value one way only: keys sorted, no spaces, decimals and dates as text
with no float anywhere. The same content always gives the same bytes, and a different content gives
different bytes. `digest` is the SHA-256 of those bytes, labelled with the algorithm. Store the
digest with the decision; `matches` later says whether the record still has the content that was
decided on.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

__all__ = ["ALGORITHM", "canonical_json", "digest", "matches"]

ALGORITHM = "sha256"


def _plain(value: Any) -> Any:
    """The value as JSON types, with every number that is not an integer as exact text."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        raise TypeError("a float has no single exact text; pass a Decimal or a string")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("a digest cannot hold an infinite or undefined number")
        # Normalised, so 1.50 and 1.5 are one value, and never in exponent form.
        text = format(value.normalize(), "f")
        return "0" if text in {"-0", "0"} else text
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("a digest needs a time with its timezone")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, Mapping):
        keys = list(value)
        if any(not isinstance(key, str) for key in keys):
            raise TypeError("a digest's keys must be text")
        return {key: _plain(value[key]) for key in keys}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    raise TypeError(f"a digest cannot hold a {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """One byte string per content: sorted keys, no spaces, UTF-8, no float."""
    return json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    """`sha256:<64 hex>` of the value's canonical JSON."""
    return f"{ALGORITHM}:{hashlib.sha256(canonical_json(value)).hexdigest()}"


def matches(value: Any, recorded: str) -> bool:
    """True when the value still has the content the recorded digest was taken from."""
    return hmac.compare_digest(digest(value), recorded)

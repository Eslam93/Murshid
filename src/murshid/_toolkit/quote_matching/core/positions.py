"""What no span covers, and positions a browser can use.

`uncited` lists the stretches of a text that no found quote covers, so a person can see what the
records may have missed. `utf16_positions` converts positions for a browser: Python counts
characters (code points), while JavaScript counts UTF-16 code units, where a character outside the
Basic Multilingual Plane (many emoji, some rare scripts) is two units.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable, Sequence

__all__ = ["uncited", "utf16_positions"]

_ASTRAL = re.compile("[\U00010000-\U0010ffff]")


def uncited(
    text_length: int, spans: Iterable[tuple[int, int]], *, min_chars: int = 1
) -> list[tuple[int, int]]:
    """The stretches of 0..`text_length` that no span covers, each at least `min_chars` long.

    Spans may overlap and come in any order. A span outside the text is a caller's mistake and
    raises ValueError, because it means the positions belong to another text.
    """
    if text_length < 0:
        raise ValueError("text_length cannot be negative")
    if min_chars < 1:
        raise ValueError("min_chars must be at least 1")
    ordered = sorted(spans)
    for start, end in ordered:
        if not 0 <= start <= end <= text_length:
            raise ValueError(f"span {start}..{end} is outside the text (length {text_length})")
    stretches: list[tuple[int, int]] = []
    cursor = 0
    for start, end in ordered:
        if start == end:  # an empty span covers nothing
            continue
        if start - cursor >= min_chars:
            stretches.append((cursor, start))
        cursor = max(cursor, end)
    if text_length - cursor >= min_chars:
        stretches.append((cursor, text_length))
    return stretches


def utf16_positions(text: str, spans: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Each span of `text` in UTF-16 code units instead of characters, in the same order."""
    astral = [match.start() for match in _ASTRAL.finditer(text)]

    def convert(position: int) -> int:
        # Every character above U+FFFF before `position` adds one unit.
        return position + bisect_left(astral, position)

    converted: list[tuple[int, int]] = []
    for start, end in spans:
        if not 0 <= start <= end <= len(text):
            raise ValueError(f"span {start}..{end} is outside the text (length {len(text)})")
        converted.append((convert(start), convert(end)))
    return converted

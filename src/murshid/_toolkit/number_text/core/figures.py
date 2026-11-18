"""Finding a figure in a text by its value: in the passages it cites, elsewhere, or nowhere.

A record read from a document holds figures (a quantity, a unit price, a total) and cites the
passages they came from. `find_figure` looks for the value among the figures of the whole text, in
digits and, by default, in words, and says where it found it:

- `cited`: inside one of the cited spans (a number that overlaps a span counts);
- `elsewhere`: in the text, but in no cited span;
- `absent`: nowhere in the text.

Values are compared as numbers, so 12.50 is found in "12,5" and 1500 in "1,500" (one of its
readings). Signs are not read in text, so values compare by size. A date's parts and a code's
digits are not figures: 2026 is not found in "2026-11-01", 41 is not found in "INV-000041", and 3
is not found in "V003" (a joined code; `joined_codes=False` finds it).
List numbering at a line's start is not a figure either.

Scanning a long text takes time (about half a second for 400,000 characters, measured on
2026-10-16), so a caller that checks many values against one text scans it once with `figures_in`
and passes the figures to each `find_figure` call.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .scanning import CODE_SHAPE, Token, numbers_in
from .words import words_in

__all__ = ["FigureFound", "FigurePlace", "figures_in", "find_figure"]

FigurePlace = Literal["cited", "elsewhere", "absent"]


@dataclass(frozen=True)
class FigureFound:
    """Where a figure was found: its place, the span of the number that holds it (None when
    absent), and whether that number was written in words."""

    where: FigurePlace
    span: tuple[int, int] | None = None
    in_words: bool = False


def figures_in(
    text: str,
    *,
    words: bool = True,
    decimal_mark: str | None = None,
    code_shape: re.Pattern[str] = CODE_SHAPE,
    joined_codes: bool = True,
) -> list[Token]:
    """Every figure in a text: its numbers in digits except list numbering, and, unless `words` is
    False, its numbers in words. `decimal_mark`, `code_shape` and `joined_codes` are passed to
    `numbers_in`."""
    tokens = numbers_in(
        text, decimal_mark=decimal_mark, code_shape=code_shape, joined_codes=joined_codes
    )
    figures = [token for token in tokens if token.kind == "number" and not token.numbering]
    if words:
        figures += words_in(text)
    return figures


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < cited_end and cited_start < end for cited_start, cited_end in spans)


def find_figure(
    value: Decimal | int,
    text: str | Sequence[Token],
    cited: Iterable[tuple[int, int]] = (),
    *,
    words: bool = True,
    decimal_mark: str | None = None,
    code_shape: re.Pattern[str] = CODE_SHAPE,
    joined_codes: bool = True,
) -> FigureFound:
    """Where `value` appears in `text`, given the cited spans: cited, elsewhere or absent.

    `text` is the text itself, or its figures from `figures_in` when many values are checked
    against one text; the keyword options then come from that call and are not used here. Among
    several places, one in a cited span comes first, then digits before words, then the earliest.
    """
    target = Decimal(value)
    if not target.is_finite():
        raise ValueError("a figure must be a finite number")
    target = abs(target)
    spans = list(cited)
    figures = (
        figures_in(
            text,
            words=words,
            decimal_mark=decimal_mark,
            code_shape=code_shape,
            joined_codes=joined_codes,
        )
        if isinstance(text, str)
        else text
    )
    matches = [token for token in figures if target in token.values]
    if not matches:
        return FigureFound("absent")
    best = min(
        matches,
        key=lambda token: (not _overlaps(token.span, spans), token.in_words, token.span),
    )
    where: FigurePlace = "cited" if _overlaps(best.span, spans) else "elsewhere"
    return FigureFound(where, best.span, best.in_words)

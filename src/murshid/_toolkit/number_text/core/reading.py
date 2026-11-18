"""Reading one number as a person wrote it, by one decimal rule.

People write the same number in many ways: "1,234.56", "1.234,56", "1 234,56", or in Arabic-Indic
digits with the Arabic separators. A comma or a point can be a decimal mark or a thousands mark,
and the text alone does not always say which. The rule here decides from the marks themselves,
from the most decimal places the value may have (the caller knows this: two for SAR, three for KWD,
zero for a count of items), and from the document's decimal mark when the caller knows it:

1. The Arabic decimal separator (U+066B) is always the decimal mark, and the Arabic thousands
   separator (U+066C) always groups thousands.
2. With a comma and a point both present, the last one is the decimal mark, and the other groups
   by three.
3. A single comma or point followed by one or two final digits is the decimal mark ("12,50").
4. A single comma or point followed by exactly three digits: when the document's decimal mark is
   known, that mark decides, at any number of places ("12.505" in a document that writes "4,120.50"
   is 12.505, too precise for two places, never 12505). Otherwise it groups thousands when the
   value may have at most two decimal places ("1,200" is 1200), and when it may have three or more,
   or the places are unknown, the form is ambiguous. A leading zero makes it decimal ("0,500" is
   0.5).
5. Within one value, a plain, no-break or narrow no-break space between groups of three digits
   groups them ("4 120,50" is 4120.50).
6. Anything else is refused with a reason. Nothing is guessed.

Digits from any script are folded to 0 to 9 first, so the Arabic-Indic "١٢" and the Persian "۱۲"
read as 12.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

__all__ = [
    "ARABIC_DECIMAL",
    "ARABIC_GROUPING",
    "REASONS",
    "NumberRead",
    "Reason",
    "fold_arabic",
    "fold_digits",
    "infer_decimal_mark",
    "read_number",
]

Reason = Literal["empty", "ambiguous", "not_a_number", "out_of_range", "too_precise"]
REASONS: tuple[Reason, ...] = ("empty", "ambiguous", "not_a_number", "out_of_range", "too_precise")

ARABIC_DECIMAL = "\N{ARABIC DECIMAL SEPARATOR}"
ARABIC_GROUPING = "\N{ARABIC THOUSANDS SEPARATOR}"
NO_BREAK_SPACES = "\N{NO-BREAK SPACE}\N{NARROW NO-BREAK SPACE}"
_SPACES = " " + NO_BREAK_SPACES
_MARKS = ",."  # a comma or a point: a decimal mark or a thousands mark, by the rule
_DECIMAL_CAPABLE = _MARKS + ARABIC_DECIMAL
_SEPARATORS = _DECIMAL_CAPABLE + ARABIC_GROUPING + _SPACES
_SIGNS = "+-\N{MINUS SIGN}"
# Direction marks that a right-to-left editor puts around a number; they are not part of it.
_DIRECTION_MARKS = "".join(
    chr(code) for code in (0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A))
)
_ANY_DIGIT = re.compile(r"\d")  # in a str pattern, \d is every Unicode decimal digit (category Nd)


def fold_digits(text: str) -> str:
    """The text with every decimal digit written 0 to 9: Arabic-Indic (٣), Persian (۳), full-width
    and every other script's digits.

    One character stays one character, so a position in the folded text is the same position in
    the original. The Arabic separators (U+066B and U+066C) are not digits and stay as they are.
    """
    if text.isascii():
        return text
    return _ANY_DIGIT.sub(lambda found: str(unicodedata.decimal(found.group())), text)


# The letter forms people write for one letter, folded one character to one character.
_ARABIC_LETTER_FOLD = str.maketrans("أإآٱةىؤئ", "ااااهيوي")
# The harakat and the other combining marks, the superscript alef, and the tatweel.
_ARABIC_MARKS = re.compile(
    "[\N{ARABIC SIGN SALLALLAHOU ALAYHE WASSALLAM}-\N{ARABIC SMALL KASRA}"
    "\N{ARABIC FATHATAN}-\N{ARABIC WAVY HAMZA BELOW}"
    "\N{ARABIC LETTER SUPERSCRIPT ALEF}"
    "\N{ARABIC SMALL HIGH LIGATURE SAD WITH LAM WITH ALEF MAKSURA}-\N{ARABIC SMALL LOW MEEM}"
    "\N{ARABIC TATWEEL}]"
)


def fold_arabic(text: str, *, marks: bool = True) -> str:
    """The text with each Arabic letter form folded to its base letter: أ إ آ ٱ to ا, ة to ه,
    ى to ي, ؤ to و and ئ to ي.

    With `marks` True, the Arabic marks (the harakat, the other combining marks, the superscript
    alef) and the tatweel are removed too. With `marks` False, one character stays one character,
    so a position in the folded text is the same position in the original. Case is never changed.
    """
    folded = text.translate(_ARABIC_LETTER_FOLD)
    return _ARABIC_MARKS.sub("", folded) if marks else folded


@dataclass(frozen=True)
class NumberRead:
    """What `read_number` found: a value, or a refusal with its reason.

    `readings` lists the values an ambiguous form allows ("1,500" gives 1500 and 1.5), so the
    caller can show them; it is empty otherwise.
    """

    value: Decimal | None
    reason: Reason | None = None
    readings: tuple[Decimal, ...] = ()

    @property
    def ok(self) -> bool:
        return self.reason is None


@dataclass(frozen=True)
class _Form:
    """One way to read a written number: the whole part, the decimal part, and the marks' roles."""

    whole: str
    fraction: str
    decimal_char: str | None
    grouping_char: str | None

    def value(self) -> Decimal:
        whole = self.whole or "0"
        return Decimal(f"{whole}.{self.fraction}") if self.fraction else Decimal(whole)

    @property
    def places(self) -> int:
        """The decimal places that carry a value: "12.50" has one."""
        return len(self.fraction.rstrip("0"))


def _split(body: str) -> tuple[list[str], list[str]] | None:
    """The digit groups and the separators between them, or None when the text is not that shape.

    The body holds only the digits 0 to 9 and separators. Two separators in a row, a separator at
    the end, and a leading separator that cannot be a decimal mark are not a number.
    """
    groups: list[str] = []
    seps: list[str] = []
    start = 0
    for index, char in enumerate(body):
        if "0" <= char <= "9":
            continue
        if char not in _SEPARATORS:
            return None
        if index == start and (groups or char not in _DECIMAL_CAPABLE):
            return None
        groups.append(body[start:index])
        seps.append(char)
        start = index + 1
    if start == len(body):
        return None
    groups.append(body[start:])
    return groups, seps


def _grouped(groups: list[str], seps: list[str]) -> bool:
    """Whether the groups are thousands: one separator character, a first group of one to three
    digits, and every later group of exactly three."""
    return (
        len(set(seps)) == 1
        and seps[0] != ARABIC_DECIMAL
        and 1 <= len(groups[0]) <= 3
        and all(len(group) == 3 for group in groups[1:])
    )


def _with_decimal(groups: list[str], seps: list[str], at: int) -> list[_Form] | None:
    """The single form where the separator at index `at` is the decimal mark, or None."""
    mark = seps[at]
    if at != len(seps) - 1 or seps.count(mark) != 1:
        return None
    whole_groups, whole_seps = groups[: at + 1], seps[:at]
    if whole_seps and not _grouped(whole_groups, whole_seps):
        return None
    grouping = whole_seps[0] if whole_seps else None
    return [_Form("".join(whole_groups), groups[-1], mark, grouping)]


def _forms(
    groups: list[str], seps: list[str], max_places: int | None, decimal_mark: str | None
) -> list[_Form] | None:
    """Every form the written number allows: one, two when it is ambiguous (grouping first), or
    None when it is not a number."""
    if not seps:
        return [_Form(groups[0], "", None, None)]
    if not groups[0]:  # ".5": a leading decimal mark cannot group anything
        return [_Form("0", groups[1], seps[0], None)] if len(seps) == 1 else None
    kinds = set(seps)
    if ARABIC_DECIMAL in kinds:
        return _with_decimal(groups, seps, seps.index(ARABIC_DECIMAL))
    if "," in kinds and "." in kinds:
        last = max(index for index, sep in enumerate(seps) if sep in _MARKS)
        return _with_decimal(groups, seps, last)
    marks = [index for index, sep in enumerate(seps) if sep in _MARKS]
    if len(marks) != 1:  # no comma or point, or one of them repeated: every separator groups
        if not _grouped(groups, seps):
            return None
        return [_Form("".join(groups), "", None, seps[0])]
    (at,) = marks
    if len(seps) > 1:  # a space or `٬` groups, so the comma or point is the decimal mark
        return _with_decimal(groups, seps, at)
    head, tail = groups
    mark = seps[0]
    decimal = _Form(head, tail, mark, None)
    if len(tail) != 3 or len(head) > 3:  # it cannot group thousands
        return [decimal]
    grouping = _Form(head + tail, "", None, mark)
    if not head.strip("0"):  # a leading zero: "0,500" is 0.5
        return [decimal]
    if decimal_mark is not None:  # the document's own mark decides, at any number of places
        return [decimal] if decimal_mark == mark else [grouping]
    if max_places is not None and max_places <= 2:
        return [grouping]
    return [grouping, decimal]


def _trim(text: str) -> str:
    return text.strip().strip(_DIRECTION_MARKS).strip()


def _check_mark(decimal_mark: str | None) -> None:
    if decimal_mark not in (None, ",", "."):
        raise ValueError(f'decimal_mark must be ",", "." or None, not {decimal_mark!r}')


def read_number(
    text: str,
    *,
    max_places: int | None,
    decimal_mark: str | None = None,
    negative: bool = False,
    limit: Decimal | int | None = None,
) -> NumberRead:
    """One value as a person wrote it, read by the decimal rule, or a refusal with its reason.

    `max_places` is the most decimal places the value may have (two for SAR, three for KWD, zero
    for a count), or None when it is unknown. `decimal_mark` is the document's decimal mark ("," or
    "."), when the caller knows it from the document's unambiguous numbers (`infer_decimal_mark`).
    `negative` allows a leading minus. A value whose size reaches `limit` is out of range.

    Reasons: `empty` (nothing but spaces), `not_a_number` (letters, a currency, a misplaced mark),
    `ambiguous` (the rule cannot choose; `readings` lists the values), `out_of_range` (negative when
    not allowed, or at or above `limit`), `too_precise` (more decimal places carry a value than
    `max_places` allows: "12.50" has one, and "12.505" with the decimal mark "." has three).
    """
    _check_mark(decimal_mark)
    if max_places is not None and max_places < 0:
        raise ValueError("max_places must be zero or more, or None")
    body = _trim(text)
    if not body:
        return NumberRead(None, "empty")
    body = fold_digits(body)
    minus = body[0] in _SIGNS[1:]
    if body[0] in _SIGNS:
        body = body[1:]
    split = _split(body) if body else None
    forms = _forms(*split, max_places, decimal_mark) if split else None
    if not forms:
        return NumberRead(None, "not_a_number")
    values = tuple(-form.value() if minus else form.value() for form in forms)
    if len(values) > 1:
        return NumberRead(None, "ambiguous", values)
    (value,) = values
    if (value < 0 and not negative) or (limit is not None and abs(value) >= limit):
        return NumberRead(None, "out_of_range")
    if max_places is not None and forms[0].places > max_places:
        return NumberRead(None, "too_precise")
    return NumberRead(value)


def _evidence(text: str) -> str | None:
    """The decimal mark one written value proves, or None when it proves none."""
    body = fold_digits(_trim(text)).lstrip(_SIGNS)
    split = _split(body) if body else None
    forms = _forms(*split, None, None) if split else None
    if not forms or len(forms) != 1:
        return None
    (form,) = forms
    if form.decimal_char is not None and form.decimal_char in _MARKS:
        return form.decimal_char
    if (
        form.grouping_char is not None and form.grouping_char in _MARKS
    ):  # "1,234,567": the comma groups, so the point is decimal
        return "." if form.grouping_char == "," else ","
    return None


def infer_decimal_mark(values: Iterable[str]) -> str | None:
    """A document's decimal mark ("," or "."), taken from its values that prove one.

    Each text is one value as written, such as the amounts a reader took from one invoice.
    "12,50", "1.234,56" and "0,500" prove a comma; "4,120.50", "1,234,567" and "12.5" prove a
    point. "1,500" proves nothing, and neither does the Arabic decimal separator. Values that
    prove different marks give None, as does a document with no proof.
    """
    found = {mark for mark in map(_evidence, values) if mark is not None}
    return found.pop() if len(found) == 1 else None

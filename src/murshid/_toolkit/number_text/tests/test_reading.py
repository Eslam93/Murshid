"""Reading one value by the decimal rule, through the public interface.

The table holds every case the step's brief names for the rule, in English and Arabic forms, each
with the caller's maximum decimal places and, where it matters, the document's decimal mark.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from murshid._toolkit.number_text.core import (
    ARABIC_DECIMAL,
    ARABIC_GROUPING,
    REASONS,
    fold_arabic,
    fold_digits,
    infer_decimal_mark,
    read_number,
)

DEC = ARABIC_DECIMAL  # written through a name: the character looks like a comma
GRP = ARABIC_GROUPING
NBSP = "\N{NO-BREAK SPACE}"
NNBSP = "\N{NARROW NO-BREAK SPACE}"

# (text, maximum decimal places, document's decimal mark, the value or the refusal's reason)
CASES: list[tuple[str, int | None, str | None, str]] = [
    # One mark before one or two final digits is the decimal mark
    ("12,50", 2, None, "12.50"),
    ("1,5", 2, None, "1.5"),
    ("12.5", 2, None, "12.5"),
    # One mark before three digits: thousands at two places, ambiguous at three or unknown
    ("1,200", 2, None, "1200"),
    ("1,200", 3, None, "ambiguous"),
    ("1.500", 2, None, "1500"),
    ("1.500", 3, None, "ambiguous"),
    ("1,500", None, None, "ambiguous"),
    ("1,500", 0, None, "1500"),
    # unless the document's decimal mark is known
    ("1,500", 3, ",", "1.5"),
    ("1,500", 3, ".", "1500"),
    ("1.500", 3, ".", "1.5"),
    # and the known mark decides at two places too: never a thousand times the written value
    ("12.505", 2, ".", "too_precise"),
    ("1,500", 2, ",", "1.5"),
    ("1,200", 2, ".", "1200"),
    ("1,500", 0, ",", "too_precise"),
    # a leading zero makes it decimal
    ("0,500", 2, None, "0.5"),
    ("0,500", 3, None, "0.5"),
    ("0.050", None, None, "0.05"),
    # a whole part of four digits cannot be a thousands group
    ("1234,567", 3, None, "1234.567"),
    # A comma and a point: the last is decimal, the other groups by three
    ("1.234,56", 2, None, "1234.56"),
    ("1,234.56", 2, None, "1234.56"),
    ("1.234.567,8", 2, None, "1234567.8"),
    ("1,234,567", 0, None, "1234567"),
    ("1.234.567", 0, None, "1234567"),
    # Spaces group by three within one value: no-break, narrow no-break and plain
    (f"4{NBSP}120,50", 2, None, "4120.50"),
    (f"4{NNBSP}120,50", 2, None, "4120.50"),
    ("4 120,50", 2, None, "4120.50"),
    ("1 234 567", 0, None, "1234567"),
    # The Arabic separators: decimal always, grouping always; Arabic-Indic and Persian digits
    (f"١٢{DEC}٥٠", 2, None, "12.50"),
    (f"١٢{DEC}٥", 2, None, "12.5"),
    (f"٤{GRP}١٢٠{DEC}٥٠", 2, None, "4120.50"),
    (f"١{DEC}٢٣٤", 3, None, "1.234"),  # never ambiguous: the mark says decimal
    (f"١{GRP}٢٣٤", 3, None, "1234"),  # never ambiguous: the mark says grouping
    (f"۱۲{DEC}۵", 2, None, "12.5"),  # Persian digits
    (f"۴{GRP}۱۲۰", 0, None, "4120"),
    ("١٢٠٠", 2, None, "1200"),
    (
        "\N{FULLWIDTH DIGIT ONE}\N{FULLWIDTH DIGIT TWO},\N{FULLWIDTH DIGIT FIVE}",
        2,
        None,
        "12.5",
    ),  # full width
    # Other shapes that read
    (".5", 2, None, "0.5"),
    ("  12.5 \t", 2, None, "12.5"),
    ("\N{RIGHT-TO-LEFT MARK}١٢\N{LEFT-TO-RIGHT MARK}", 0, None, "12"),
    ("007", 0, None, "7"),
    ("12.50", 1, None, "12.5"),  # a trailing zero carries no value, so one place is enough
    # Refusals
    ("", 2, None, "empty"),
    ("   ", 2, None, "empty"),
    ("SAR 900", 2, None, "not_a_number"),
    ("900 ريال", 2, None, "not_a_number"),
    ("fifteen", 0, None, "not_a_number"),
    ("1.2.3", 2, None, "not_a_number"),
    ("1.234.56", 2, None, "not_a_number"),
    ("1,23,456", 0, None, "not_a_number"),
    ("12 50", 2, None, "not_a_number"),
    ("1,,5", 2, None, "not_a_number"),
    ("12,", 2, None, "not_a_number"),
    ("1,234 567", 2, None, "not_a_number"),
    ("1.234,567.8", 2, None, "not_a_number"),
    ("1,23.45", 2, None, "not_a_number"),
    (f"1{DEC}2{DEC}3", 2, None, "not_a_number"),
    (f"1{DEC}234,5", 2, None, "not_a_number"),
    ("1e3", 2, None, "not_a_number"),
    ("1_000", 0, None, "not_a_number"),
    ("NaN", 2, None, "not_a_number"),
    ("Infinity", 2, None, "not_a_number"),
    ("1 234", 0, None, "1234"),
    ("1\n234", 0, None, "not_a_number"),
    ("-", 2, None, "not_a_number"),
    ("--5", 2, None, "not_a_number"),
    ("1,5", 0, None, "too_precise"),
    ("0,500", 0, None, "too_precise"),
    ("12.345678", 2, None, "too_precise"),
    ("1234,567", 2, None, "too_precise"),
    ("-5", 2, None, "out_of_range"),
]


@pytest.mark.parametrize(("text", "places", "mark", "expected"), CASES)
def test_the_decimal_rule(text: str, places: int | None, mark: str | None, expected: str) -> None:
    read = read_number(text, max_places=places, decimal_mark=mark)
    if expected in REASONS:
        assert (read.value, read.reason) == (None, expected)
        assert not read.ok
    else:
        assert read.ok, read
        assert read.value == Decimal(expected)


def test_every_reason_has_a_case() -> None:
    assert {expected for *_, expected in CASES if expected in REASONS} == set(REASONS)


def test_an_ambiguous_form_lists_what_it_could_mean() -> None:
    assert read_number("1,500", max_places=3).readings == (Decimal(1500), Decimal("1.5"))
    assert read_number("-1.200", max_places=None, negative=True).readings == (
        Decimal(-1200),
        Decimal("-1.2"),
    )
    assert read_number("12,50", max_places=2).readings == ()


def test_a_sign_is_read_only_when_allowed() -> None:
    assert read_number("-5", max_places=0).reason == "out_of_range"
    assert read_number("-5", max_places=0, negative=True).value == Decimal(-5)
    assert read_number("\N{MINUS SIGN}1.234,5", max_places=2, negative=True).value == Decimal(
        "-1234.5"
    )
    assert read_number("+5", max_places=0).value == Decimal(5)
    assert read_number("-0", max_places=0).value == Decimal(0)


def test_a_value_at_or_above_the_limit_is_out_of_range() -> None:
    limit = Decimal(10**6)
    assert read_number("999,999.99", max_places=2, limit=limit).value == Decimal("999999.99")
    assert read_number("1,000,000", max_places=2, limit=limit).reason == "out_of_range"
    assert read_number("-1000000", max_places=0, negative=True, limit=limit).reason == (
        "out_of_range"
    )
    assert read_number("5", max_places=0, limit=5).reason == "out_of_range"


def test_wrong_settings_are_refused_loudly() -> None:
    with pytest.raises(ValueError, match="decimal_mark"):
        read_number("1", max_places=0, decimal_mark=DEC)
    with pytest.raises(ValueError, match="max_places"):
        read_number("1", max_places=-1)


@pytest.mark.parametrize(
    ("values", "mark"),
    [
        (["12,50", "1.234,56", "0,500"], ","),
        (["1 234,56"], ","),
        (["1.234.567"], ","),
        (["4,120.50", "1,234,567", "12.5"], "."),
        (["1,500", "12,50"], ","),  # "1,500" proves nothing, so "12,50" decides
        (["1,500"], None),
        ([f"١٢{DEC}٥٠", f"٤{GRP}١٢٠"], None),  # the Arabic separators say nothing about , and .
        (["12,50", "4,120.50"], None),  # conflicting proof gives none
        (["", "abc", "900 SAR"], None),
        ([], None),
    ],
)
def test_a_documents_decimal_mark_comes_from_its_unambiguous_values(
    values: list[str], mark: str | None
) -> None:
    assert infer_decimal_mark(values) == mark


def test_the_inferred_mark_settles_an_ambiguous_value() -> None:
    document = ["1,500", "12,50", "4.120,50"]
    mark = infer_decimal_mark(document)
    assert [read_number(value, max_places=3, decimal_mark=mark).value for value in document] == [
        Decimal("1.5"),
        Decimal("12.5"),
        Decimal("4120.5"),
    ]


def test_digits_of_every_script_fold_and_keep_their_positions() -> None:
    assert fold_digits("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert fold_digits("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert fold_digits("\N{FULLWIDTH DIGIT ONE}\N{FULLWIDTH DIGIT TWO}") == "12"
    mixed = f"المجموع ٤{GRP}١٢٠{DEC}٥٠ SAR"
    folded = fold_digits(mixed)
    assert len(folded) == len(mixed)
    assert folded == f"المجموع 4{GRP}120{DEC}50 SAR"
    assert fold_digits("plain 123") == "plain 123"


def test_arabic_letter_forms_fold_one_to_one_and_marks_go_unless_kept() -> None:
    assert fold_arabic("أإآٱةىؤئ") == "ااااهيوي"
    marked = "ثَلَاثـة هٰذا"  # with harakat, a tatweel and a superscript alef
    assert fold_arabic(marked) == "ثلاثه هذا"
    kept = fold_arabic(marked, marks=False)
    assert kept == "ثَلَاثـه هٰذا"
    assert len(kept) == len(marked)  # one character for one, so positions stay
    assert fold_arabic("Total أحمد ٤") == "Total احمد ٤"  # case and digits stay as written

"""Finding numbers, dates and codes in free text and in structured data, as whole tokens."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from murshid._toolkit.number_text.core import (
    ARABIC_DECIMAL,
    ARABIC_GROUPING,
    PartialDate,
    TimeOfDay,
    Token,
    code_key,
    dates_match,
    is_id_key,
    numbers_in,
    numbers_in_data,
    times_match,
)

DEC = ARABIC_DECIMAL
GRP = ARABIC_GROUPING
NBSP = "\N{NO-BREAK SPACE}"


def d(*values: str | int) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in values)


def only(text: str, **options: object) -> Token:
    tokens = numbers_in(text, **options)  # type: ignore[arg-type]
    assert len(tokens) == 1, tokens
    return tokens[0]


def summary(text: str) -> list[tuple[str, str]]:
    return [(token.kind, token.text) for token in numbers_in(text)]


# ---- numbers ----------------------------------------------------------------------------------


def test_a_plain_space_ends_a_number_in_free_text_and_a_no_break_space_groups() -> None:
    plain = numbers_in("Total 4 120,50 SAR")
    assert [token.text for token in plain] == ["4", "120,50"]
    assert plain[0].readings == (d(4),)
    assert plain[1].readings[0] == d("120.50")
    joined = only(f"Total 4{NBSP}120,50 SAR")
    assert joined.readings == (d("4120.50"),)
    assert joined.span == (6, 14)
    assert joined.currency == "SAR"


def test_an_ambiguous_form_gives_every_reading_and_is_never_refused() -> None:
    tokens = numbers_in("lines 1,2 and 3")
    assert [token.text for token in tokens] == ["1,2", "3"]
    assert tokens[0].readings == (d("1.2"), d(1, 2))
    assert tokens[0].values == frozenset(d("1.2", 1, 2))
    assert only("1,500 units").readings == (d(1500), d("1.5"))
    assert only("12,50").readings == (d("12.5"), d(12, 50))
    assert only("1,2,3").readings == (d(1, 2, 3),)
    assert only("version 1.2.3").readings == (d(1, 2, 3),)
    assert only(f"12{NBSP}50").readings == (d(12, 50),)


def test_a_known_decimal_mark_settles_the_three_digit_form() -> None:
    assert only("1,500", decimal_mark=",").readings == (d("1.5"),)
    assert only("1,500", decimal_mark=".").readings == (d(1500),)
    with pytest.raises(ValueError, match="decimal_mark"):
        numbers_in("1", decimal_mark=";")


def test_a_decimal_is_one_number_so_a_changed_fraction_is_another_number() -> None:
    tokens = numbers_in("It is 12.5, or 0.5, or 5.12, not 12.05 or 0.050.")
    assert [token.readings for token in tokens] == [
        (d("12.5"),),
        (d("0.5"),),
        (d("5.12"),),
        (d("12.05"),),
        (d("0.05"),),
    ]
    assert only("costs .5 SAR").readings == (d("0.5"),)


def test_arabic_digits_and_separators_read_in_free_text() -> None:
    assert only(f"المجموع ٤{GRP}١٢٠{DEC}٥٠ ريال").readings == (d("4120.50"),)
    assert only(f"١٢{DEC}٥").readings == (d("12.5"),)
    assert only("نبغى ١٥ جهاز").readings == (d(15),)
    assert only("۱۲۰۰").readings == (d(1200),)


def test_a_currency_glued_to_a_number_is_read_as_a_number() -> None:
    assert (only("SAR900").readings, only("SAR900").currency) == ((d(900),), "SAR")
    assert (only("٩٠٠ريال").readings, only("٩٠٠ريال").currency) == ((d(900),), "ريال")
    assert only("900 SAR").currency == "SAR"
    assert only("$1,200.00").currency == "$"
    assert only("٩٥ ريالًا للقطعة").currency == "ريالًا"
    assert only("4,120.50EUR").readings == (d("4120.50"),)
    assert only("I will try 5 times").currency == ""  # a lower-case word is not an ISO code
    assert only("5 laptops").currency == ""


def test_a_currency_glued_to_a_number_is_never_a_code_even_for_a_wider_code_shape() -> None:
    shape = re.compile(r"(?<![A-Z0-9])[A-Z]{2,3}[0-9]{3,6}(?![A-Z0-9])")
    tokens = numbers_in("Ref AB1234 for SAR9000", code_shape=shape)
    assert [(token.kind, token.text) for token in tokens] == [
        ("code", "AB1234"),
        ("number", "9000"),
    ]


def test_your_own_currencies_replace_the_default() -> None:
    shape = re.compile(r"(?i:kr)")
    assert only("120 kr", currency_shape=shape).currency == "kr"
    assert only("120 SAR", currency_shape=shape).currency == ""


def test_a_hyphen_between_numbers_is_a_range_not_a_sign() -> None:
    assert summary("15-20 laptops") == [("number", "15"), ("number", "20")]
    assert summary("2026-2027") == [("number", "2026"), ("number", "2027")]
    assert only("a credit of -120").readings == (d(120),)


@pytest.mark.parametrize(
    ("text", "numbering"),
    [
        ("1. Spend is 4120", [True, False]),
        ("2) done", [True]),
        ("  - 3. item", [True]),
        ("(4) item", [True]),
        ("١- البند الأول", [True]),
        ("12) twelve", [True]),
        ("1.\nnext", [True]),
        ("123. item", [False]),
        ("1.5 kg", [False]),
        ("Total 12. Next", [False]),
        ("15-20 laptops", [False, False]),
    ],
)
def test_list_numbering_at_a_lines_start_is_marked(text: str, numbering: list[bool]) -> None:
    assert [token.numbering for token in numbers_in(text)] == numbering


def test_numbering_is_found_on_every_line() -> None:
    text = "Totals:\n1. Spend is 4120\n2) Count is 7"
    assert [(token.text, token.numbering) for token in numbers_in(text)] == [
        ("1", True),
        ("4120", False),
        ("2", True),
        ("7", False),
    ]


# ---- dates ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "reading"),
    [
        ("2026-03-07", "date", PartialDate(2026, 3, 7)),
        ("2026-3-7", "date", PartialDate(2026, 3, 7)),
        ("٢٠٢٦-٠٣-٠٧", "date", PartialDate(2026, 3, 7)),
        ("2026-03-07T10:30:00Z", "date", PartialDate(2026, 3, 7)),
        ("2026-03-07 10:30:00+03:00", "date", PartialDate(2026, 3, 7)),
        ("15 October 2026", "date", PartialDate(2026, 10, 15)),
        ("15th of October 2026", "date", PartialDate(2026, 10, 15)),
        ("October 15, 2026", "date", PartialDate(2026, 10, 15)),
        ("Oct. 15 2026", "date", PartialDate(2026, 10, 15)),
        ("October 15", "day_month", PartialDate(None, 10, 15)),
        ("15 October", "day_month", PartialDate(None, 10, 15)),
        ("October 2026", "month_year", PartialDate(2026, 10, None)),
        ("October, 2026", "month_year", PartialDate(2026, 10, None)),
        ("SEPTEMBER 2026", "month_year", PartialDate(2026, 9, None)),
        ("١٥ أكتوبر ٢٠٢٦", "date", PartialDate(2026, 10, 15)),
        ("١٥ اكتوبر ٢٠٢٦", "date", PartialDate(2026, 10, 15)),
        ("أكتوبر، ٢٠٢٦", "month_year", PartialDate(2026, 10, None)),
        ("١٥ أكتوبر", "day_month", PartialDate(None, 10, 15)),
        ("٧ آذار ٢٠٢٦", "date", PartialDate(2026, 3, 7)),
        ("تشرين الأول ٢٠٢٦", "month_year", PartialDate(2026, 10, None)),
        ("تشرين أول ٢٠٢٦", "month_year", PartialDate(2026, 10, None)),
        ("٣ كانون الثاني", "day_month", PartialDate(None, 1, 3)),
        ("29 February 2028", "date", PartialDate(2028, 2, 29)),
        ("29 February", "day_month", PartialDate(None, 2, 29)),
        ("in May 2026", "month_year", PartialDate(2026, 5, None)),
        ("May 5", "day_month", PartialDate(None, 5, 5)),
    ],
)
def test_a_date_is_one_token(text: str, kind: str, reading: PartialDate) -> None:
    tokens = [token for token in numbers_in(text) if token.kind != "number"]
    assert len(tokens) == 1, tokens
    assert (tokens[0].kind, tokens[0].dates) == (kind, (reading,))
    start, end = tokens[0].span
    assert text[start:end] == tokens[0].text


ENGLISH_MONTHS = [
    ("January", "Jan"),
    ("February", "Feb"),
    ("March", "Mar"),
    ("April", "Apr"),
    ("May", "May"),
    ("June", "Jun"),
    ("July", "Jul"),
    ("August", "Aug"),
    ("September", "Sept"),
    ("October", "Oct"),
    ("November", "Nov"),
    ("December", "Dec"),
]
GULF_MONTHS = [
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
]
LEVANTINE_MONTHS = [
    "كانون الثاني",
    "شباط",
    "آذار",
    "نيسان",
    "أيار",
    "حزيران",
    "تموز",
    "آب",
    "أيلول",
    "تشرين الأول",
    "تشرين الثاني",
    "كانون الأول",
]


@pytest.mark.parametrize("month", range(1, 13))
def test_every_month_name_reads_in_english_and_both_arabic_forms(month: int) -> None:
    full, short = ENGLISH_MONTHS[month - 1]
    texts = [
        f"7 {full} 2026",
        f"7 {short} 2026",
        f"{full.lower()} 7, 2026",
        f"٧ {GULF_MONTHS[month - 1]} ٢٠٢٦",
        f"٧ {LEVANTINE_MONTHS[month - 1]} ٢٠٢٦",
    ]
    for text in texts:
        assert only(text).dates == (PartialDate(2026, month, 7),), text


def test_a_date_in_digits_with_the_day_and_month_unsaid_gives_both_readings() -> None:
    assert only("07/03/2026").dates == (PartialDate(2026, 3, 7), PartialDate(2026, 7, 3))
    assert only("13.03.2026").dates == (PartialDate(2026, 3, 13),)
    assert only("05-05-2026").dates == (PartialDate(2026, 5, 5),)


def test_something_that_is_not_a_calendar_day_is_not_a_date() -> None:
    assert summary("31 February 2026") == [("number", "31"), ("month_year", "February 2026")]
    assert summary("2026-13-40") == [("number", "2026"), ("number", "13"), ("number", "40")]
    assert summary("you may 5 times") == [("number", "5")]
    assert summary("12/2026") == [("number", "12"), ("number", "2026")]


def test_a_dates_parts_are_never_numbers() -> None:
    text = "Due 2026-03-07, issued 7 March 2026, for March 2026."
    assert {token.kind for token in numbers_in(text)} == {"date", "month_year"}


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("Spend: 4120.15 October 2026.", [("number", "4120.15"), ("month_year", "October 2026")]),
        ("Spend: 4120,15 October 2026", [("number", "4120,15"), ("month_year", "October 2026")]),
        ("4120.15 of October", [("number", "4120.15")]),
        (f"٤١٢٠{DEC}١٥ أكتوبر ٢٠٢٦", [("number", f"٤١٢٠{DEC}١٥"), ("month_year", "أكتوبر ٢٠٢٦")]),
        (f"٤{GRP}١٥ أكتوبر ٢٠٢٦", [("number", f"٤{GRP}١٥"), ("month_year", "أكتوبر ٢٠٢٦")]),
        (f"أكتوبر ٢٠٢٦{DEC}٥", [("number", f"٢٠٢٦{DEC}٥")]),
        # A space after the mark ends the number, so the day after it is still a day
        ("Total 4120, 15 October 2026", [("number", "4120"), ("date", "15 October 2026")]),
    ],
)
def test_a_number_beside_a_month_name_keeps_its_fraction(
    text: str, found: list[tuple[str, str]]
) -> None:
    assert summary(text) == found


def test_a_decimal_before_a_month_reads_the_same_in_data_and_in_free_text() -> None:
    apart = numbers_in_data({"total": 4120.15, "month": "October 2026"})
    together = numbers_in_data({"note": "Spend: 4120.15 October 2026."})
    for found in (apart, together):
        numbers = [item.token.readings for item in found if item.token.kind == "number"]
        dates = [item.token.dates for item in found if item.token.kind != "number"]
        assert numbers == [(d("4120.15"),)], found
        assert dates == [(PartialDate(2026, 10, None),)], found


@pytest.mark.parametrize(
    ("cited", "known", "matches"),
    [
        (PartialDate(2026, 3, 7), PartialDate(2026, 3, 7), True),
        (PartialDate(2026, 3, 7), PartialDate(2026, 3, 8), False),
        (PartialDate(2026, 3, 7), PartialDate(2025, 3, 7), False),
        (PartialDate(2026, 3, 7), PartialDate(2026, 3, None), False),
        (PartialDate(2026, 9, None), PartialDate(2026, 9, 30), True),
        (PartialDate(2026, 9, None), PartialDate(2026, 9, None), True),
        (PartialDate(2026, 9, None), PartialDate(2025, 9, 30), False),
        (PartialDate(2026, 9, None), PartialDate(None, 9, 30), False),
        (PartialDate(None, 3, 7), PartialDate(2026, 3, 7), True),
        (PartialDate(None, 3, 7), PartialDate(2019, 3, 7), True),
        (PartialDate(None, 3, 7), PartialDate(2026, 7, 3), False),
        (PartialDate(None, 3, 7), PartialDate(2026, 3, None), False),
    ],
)
def test_dates_match_by_calendar_day_and_by_the_parts_cited(
    cited: PartialDate, known: PartialDate, matches: bool
) -> None:
    assert dates_match(cited, known) is matches


def test_a_date_written_two_ways_is_the_same_calendar_day() -> None:
    iso, words = only("2026-03-07").dates[0], only("7 March 2026").dates[0]
    assert iso == words
    assert iso.full == date(2026, 3, 7)
    assert PartialDate(2026, 3, None).full is None
    assert dates_match(only("Spend in September 2026").dates[0], only("September 2026").dates[0])


# ---- codes ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("See INV-000041.", "INV000041"),
        ("PO-2026-17 is open", "PO202617"),
        ("inv-٠٠٠٠٤١", "INV000041"),
        ("Q1", "Q1"),
        ("Q2", "Q2"),
        ("in Q3 2026", "Q3"),
        ("q4", "Q4"),
    ],
)
def test_a_code_is_one_token_with_its_key(text: str, code: str) -> None:
    codes = [token for token in numbers_in(text) if token.kind == "code"]
    assert [token.code for token in codes] == [code]


def test_a_codes_digits_are_never_a_number() -> None:
    assert summary("Invoice INV-2041 for 9000 SAR") == [("code", "INV-2041"), ("number", "9000")]
    # "Q5" is no quarter: with joined codes it is a code, as "H1" is; before them it was 5.
    assert summary("Q5 and Q12") == [("code", "Q5"), ("code", "Q12")]
    plain = numbers_in("Q5 and Q12", joined_codes=False)
    assert [(token.kind, token.text) for token in plain] == [("number", "5"), ("number", "12")]
    assert summary("Q1-Q4") == [("code", "Q1"), ("code", "Q4")]


def test_codes_are_equal_by_letters_ignoring_case_and_digits_after_folding() -> None:
    assert code_key("inv-٠٠٠٠٤١") == code_key("INV-000041") == "INV000041"
    assert code_key("INV-2041") != code_key("INV-2042")
    assert code_key("INV-41") != code_key("INV-000041")


def test_your_own_code_shape_replaces_the_default() -> None:
    shape = re.compile(r"(?<![A-Z0-9])REQ[0-9]{4}(?![A-Z0-9])")
    before = numbers_in("REQ0042 and INV-2041", joined_codes=False)
    assert [(token.kind, token.text) for token in before] == [
        ("number", "0042"),
        ("code", "INV-2041"),
    ]
    assert summary("REQ0042 and INV-2041") == [("code", "REQ0042"), ("code", "INV-2041")]
    tokens = numbers_in("REQ0042 and INV-2041", code_shape=shape, joined_codes=False)
    assert [(token.kind, token.text) for token in tokens] == [
        ("code", "REQ0042"),
        ("number", "2041"),
    ]
    # The caller's shape decides first; the joined-code rule then reads what it leaves.
    tokens = numbers_in("REQ0042 and INV-2041", code_shape=shape)
    assert [(token.kind, token.text) for token in tokens] == [
        ("code", "REQ0042"),
        ("code", "INV-2041"),
    ]


def test_spans_index_the_original_text() -> None:
    text = f"فاتورة INV-٢٠٤١ بتاريخ ١٥ أكتوبر ٢٠٢٦ بمبلغ ٤{GRP}١٢٠{DEC}٥٠ ريال"
    for token in numbers_in(text):
        start, end = token.span
        assert text[start:end] == token.text
    assert [token.kind for token in numbers_in(text)] == ["code", "date", "number"]


# ---- structured data --------------------------------------------------------------------------


def test_ids_never_hold_a_figure() -> None:
    data = {
        "id": 999,
        "cost_centre_id": "77",
        "ref": "3f2a1b4c-1234-5678-9abc-def012345678",
        "total": "5",
        "paid": True,
        "note": None,
    }
    found = numbers_in_data(data)
    assert [(item.path, item.token.values) for item in found] == [(("total",), frozenset(d(5)))]
    assert is_id_key("id") and is_id_key("invoice_id") and not is_id_key("identity")


def test_your_own_id_keys_replace_the_default() -> None:
    data = {"_handle": "b7", "id": "41", "total": "41"}
    found = numbers_in_data(data, is_id=lambda key: key == "_handle")
    assert sorted(item.path for item in found) == [("id",), ("total",)]


def test_data_values_keep_their_paths_with_positions_counted_from_one() -> None:
    data = {
        "number": "INV-2041",
        "total": "4120.50",
        "issued": date(2026, 3, 7),
        "seen": datetime(2026, 3, 8, 9, 30),
        "lines": [{"amount": Decimal("12.5")}, {"amount": 3, "share": 0.25}],
        "label": "Spend in September 2026",
    }
    found = {item.path: item.token for item in numbers_in_data(data)}
    assert found[("number",)].code == "INV2041"
    assert found[("total",)].readings == (d("4120.50"),)
    assert found[("issued",)].dates == (PartialDate(2026, 3, 7),)
    assert found[("seen",)].dates == (PartialDate(2026, 3, 8),)
    assert found[("lines", 1, "amount")].readings == (d("12.5"),)
    assert found[("lines", 2, "amount")].readings == (d(3),)
    assert found[("lines", 2, "share")].readings == (d("0.25"),)
    assert found[("label",)].dates == (PartialDate(2026, 9, None),)


def test_a_machine_number_in_data_has_one_reading_and_free_text_has_all() -> None:
    found = numbers_in_data({"amount": "1.500", "note": "paid 1,500 last month", "neg": "-12"})
    readings = {item.path: item.token.readings for item in found}
    assert readings[("amount",)] == (d("1.5"),)
    assert readings[("note",)] == (d(1500), d("1.5"))
    assert readings[("neg",)] == (d(12),)  # a magnitude, as in free text


def test_values_that_are_not_finite_hold_nothing() -> None:
    data = {"a": float("nan"), "b": float("inf"), "c": Decimal("NaN"), "d": [], "e": {}}
    assert numbers_in_data(data) == []


# ---- times ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reading"),
    [
        ("9:00", TimeOfDay(9, 0)),
        ("09:00", TimeOfDay(9, 0)),
        ("00:00", TimeOfDay(0, 0)),
        ("23:59", TimeOfDay(23, 59)),
        ("9:00:30", TimeOfDay(9, 0, 30)),
        ("10:30:45.123", TimeOfDay(10, 30, 45)),
        ("9:30 am", TimeOfDay(9, 30)),
        ("9:30 pm", TimeOfDay(21, 30)),
        ("9:30pm", TimeOfDay(21, 30)),
        ("9:30 PM", TimeOfDay(21, 30)),
        ("9:30 a.m.", TimeOfDay(9, 30)),
        ("9:30 p.m.", TimeOfDay(21, 30)),
        ("09:30 pm", TimeOfDay(21, 30)),
        ("12:00 am", TimeOfDay(0, 0)),
        ("12:15 a.m.", TimeOfDay(0, 15)),
        ("12:00 pm", TimeOfDay(12, 0)),
        (f"9:30{NBSP}pm", TimeOfDay(21, 30)),
        ("٩:٣٠", TimeOfDay(9, 30)),
        ("۹:۳۰", TimeOfDay(9, 30)),
        ("٩:٣٠ ص", TimeOfDay(9, 30)),
        ("٩:٣٠ م", TimeOfDay(21, 30)),
        ("٠٩:٣٠م", TimeOfDay(21, 30)),
        ("١٢:٣٠ ص", TimeOfDay(0, 30)),
        ("٩:٣٠ صباحًا", TimeOfDay(9, 30)),
        ("٩:٣٠ صباحاً", TimeOfDay(9, 30)),
        ("٩:٣٠ صباحا", TimeOfDay(9, 30)),
        ("٩:٣٠ مساءً", TimeOfDay(21, 30)),
        ("٩:٣٠ مساء", TimeOfDay(21, 30)),
        ("10:30+03:00", TimeOfDay(10, 30)),
        ("10:30:00+0300", TimeOfDay(10, 30, 0)),
        ("10:30Z", TimeOfDay(10, 30)),
    ],
)
def test_a_time_is_one_token_on_the_24_hour_clock(text: str, reading: TimeOfDay) -> None:
    token = only(text)
    assert (token.kind, token.times, token.span) == ("time", (reading,), (0, len(text)))
    assert (token.readings, token.values, token.dates) == ((), frozenset(), ())


def test_a_time_in_a_sentence_keeps_its_span_in_the_original_text() -> None:
    text = "التسليم الساعة ٩:٣٠ م يوم الأحد، or at 9:30 a.m. on Monday."
    tokens = numbers_in(text)
    assert [(token.kind, token.text) for token in tokens] == [
        ("time", "٩:٣٠ م"),
        ("time", "9:30 a.m."),
    ]
    for token in tokens:
        start, end = token.span
        assert text[start:end] == token.text
    # A full stop after a time, or after "AM", ends the sentence and is not part of the token
    assert summary("Open at 9:00. Close at 5:00 PM.") == [("time", "9:00"), ("time", "5:00 PM")]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        # A marker that starts a word is not a marker
        ("9:30 amazing", [("time", "9:30")]),
        ("9:30 a meeting", [("time", "9:30")]),
        ("9:30 PMO", [("time", "9:30")]),
        ("٩:٣٠ مساعد", [("time", "٩:٣٠")]),
        ("٩:٣٠ صباحية", [("time", "٩:٣٠")]),
        # On an hour that is not from 1 to 12 the marker is left outside the token
        ("13:00 pm", [("time", "13:00")]),
        ("0:30 am", [("time", "0:30")]),
        ("10:30 Zone", [("time", "10:30")]),
    ],
)
def test_a_marker_counts_only_after_a_time_on_a_12_hour_clock(
    text: str, found: list[tuple[str, str]]
) -> None:
    assert summary(text) == found


def test_a_marker_on_an_hour_beyond_12_does_not_change_the_hour() -> None:
    assert only("13:00 pm").times == (TimeOfDay(13, 0),)
    assert only("0:30 am").times == (TimeOfDay(0, 30),)


@pytest.mark.parametrize(
    ("text", "found"),
    [
        # Never part of a larger number: these are numbers, and no time is read inside them
        ("10:30:45:12", [("number", "10"), ("number", "30"), ("number", "45"), ("number", "12")]),
        ("12:30.5", [("number", "12"), ("number", "30.5")]),
        ("12:345", [("number", "12"), ("number", "345")]),
        ("1.9:00", [("number", "1.9"), ("number", "00")]),
        ("127.0.0.1:5432", [("number", "127.0.0.1"), ("number", "5432")]),
        # Not a time of day: two numbers each
        ("24:00", [("number", "24"), ("number", "00")]),
        ("9:60", [("number", "9"), ("number", "60")]),
        ("25:30:00", [("number", "25"), ("number", "30"), ("number", "00")]),
        # A ratio whose second part is not two digits is its numbers
        ("a ratio of 3:1", [("number", "3"), ("number", "1")]),
        ("16:9 screens", [("number", "16"), ("number", "9")]),
    ],
)
def test_a_time_is_never_part_of_a_larger_number(text: str, found: list[tuple[str, str]]) -> None:
    assert summary(text) == found


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("8:00-9:30", [("time", "8:00"), ("time", "9:30")]),
        ("8:00\N{EN DASH}9:30", [("time", "8:00"), ("time", "9:30")]),
        ("10:00:00-11:00:00", [("time", "10:00:00"), ("time", "11:00:00")]),
        ("8:00, 9:00 and 10:00", [("time", "8:00"), ("time", "9:00"), ("time", "10:00")]),
        ("8:00,9:00", [("time", "8:00"), ("time", "9:00")]),
        ("from 9:00 for 3 hours", [("time", "9:00"), ("number", "3")]),
    ],
)
def test_times_in_a_range_or_a_list_are_each_one_token(
    text: str, found: list[tuple[str, str]]
) -> None:
    assert summary(text) == found


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("15 October 2026 at 10:30", [("date", "15 October 2026"), ("time", "10:30")]),
        ("10:15 October 2026", [("time", "10:15"), ("month_year", "October 2026")]),
        ("October 10:30", [("time", "10:30")]),
        ("October 10 10:30", [("day_month", "October 10"), ("time", "10:30")]),
        ("07/03/2026 9:00", [("date", "07/03/2026"), ("time", "9:00")]),
        ("١٥ أكتوبر ٢٠٢٦ الساعة ١٠:٣٠", [("date", "١٥ أكتوبر ٢٠٢٦"), ("time", "١٠:٣٠")]),
    ],
)
def test_a_day_is_never_the_hour_or_the_minutes_of_a_time(
    text: str, found: list[tuple[str, str]]
) -> None:
    assert summary(text) == found


@pytest.mark.parametrize(
    ("text", "times"),
    [
        ("2026-03-07T10:30:00Z", (TimeOfDay(10, 30, 0),)),
        ("2026-03-07 10:30:00+03:00", (TimeOfDay(10, 30, 0),)),
        ("2026-03-07T10:30:00.123456-05:00", (TimeOfDay(10, 30, 0),)),
        ("2026-03-07 10:30", (TimeOfDay(10, 30),)),
        ("2026-03-07 9:30", (TimeOfDay(9, 30),)),
        ("2026-03-07 10:30 pm", (TimeOfDay(22, 30),)),
        ("٢٠٢٦-٠٣-٠٧ ١٠:٣٠ م", (TimeOfDay(22, 30),)),
        ("2026-03-07", ()),
        # A time that is no time of day stays inside the date and holds nothing
        ("2026-03-07 25:99", ()),
    ],
)
def test_a_date_in_digits_holds_the_time_written_after_it(
    text: str, times: tuple[TimeOfDay, ...]
) -> None:
    token = only(text)
    assert (token.kind, token.dates, token.times) == ("date", (PartialDate(2026, 3, 7),), times)
    assert token.span == (0, len(text))


@pytest.mark.parametrize(
    ("text", "found", "times"),
    [
        # After a clock joined to the date by a space, a hyphen and a time are a range: the date
        # token ends at the first time, and the second time is its own token.
        (
            "Meeting 2026-11-05 10:30-11:30.",
            [("date", "2026-11-05 10:30"), ("time", "11:30")],
            [(TimeOfDay(10, 30),), (TimeOfDay(11, 30),)],
        ),
        (
            "2026-11-05 10:30:00-11:30:00",
            [("date", "2026-11-05 10:30:00"), ("time", "11:30:00")],
            [(TimeOfDay(10, 30, 0),), (TimeOfDay(11, 30, 0),)],
        ),
        (
            "2026-11-05 10:30-11:30 pm",
            [("date", "2026-11-05 10:30"), ("time", "11:30 pm")],
            [(TimeOfDay(10, 30),), (TimeOfDay(23, 30),)],
        ),
        (
            "2026-11-05 10:30-05:00",
            [("date", "2026-11-05 10:30"), ("time", "05:00")],
            [(TimeOfDay(10, 30),), (TimeOfDay(5, 0),)],
        ),
        # Joined with "T", the same hyphen starts an ISO zone offset, which belongs to the token.
        ("2026-11-05T10:30-05:00", [("date", "2026-11-05T10:30-05:00")], [(TimeOfDay(10, 30),)]),
        # "Z" and a "+" offset belong to the token in both forms.
        ("2026-11-05 10:30+03:00", [("date", "2026-11-05 10:30+03:00")], [(TimeOfDay(10, 30),)]),
        ("2026-11-05 10:30Z", [("date", "2026-11-05 10:30Z")], [(TimeOfDay(10, 30),)]),
        ("2026-11-05T10:30+0300", [("date", "2026-11-05T10:30+0300")], [(TimeOfDay(10, 30),)]),
    ],
)
def test_a_hyphen_after_a_dates_time_is_a_range_unless_the_time_is_joined_with_t(
    text: str, found: list[tuple[str, str]], times: list[tuple[TimeOfDay, ...]]
) -> None:
    assert summary(text) == found
    assert [token.times for token in numbers_in(text)] == times


def test_a_date_keeps_a_marker_that_does_not_fit_its_hour_outside() -> None:
    assert summary("2026-03-07 13:00 pm") == [("date", "2026-03-07 13:00")]
    assert only("2026-03-07 13:00 pm").times == (TimeOfDay(13, 0),)


@pytest.mark.parametrize(
    ("cited", "known", "matches"),
    [
        (TimeOfDay(9, 0), TimeOfDay(9, 0), True),
        (TimeOfDay(9, 0), TimeOfDay(9, 0, 30), True),
        (TimeOfDay(9, 0, 0), TimeOfDay(9, 0, 0), True),
        (TimeOfDay(9, 0, 30), TimeOfDay(9, 0), False),
        (TimeOfDay(9, 0, 30), TimeOfDay(9, 0, 31), False),
        (TimeOfDay(9, 1), TimeOfDay(9, 0, 59), False),
        (TimeOfDay(9, 0), TimeOfDay(21, 0), False),
        (TimeOfDay(21, 0), TimeOfDay(9, 0), False),
    ],
)
def test_times_match_by_hour_and_minute_and_the_second_when_cited(
    cited: TimeOfDay, known: TimeOfDay, matches: bool
) -> None:
    assert times_match(cited, known) is matches


def test_a_time_written_in_any_form_is_the_same_time_of_day() -> None:
    forms = ["21:30", "9:30 pm", "9:30 p.m.", "٢١:٣٠", "٩:٣٠ م", "٩:٣٠ مساءً", "21:30:00+03:00"]
    readings = {only(text).times for text in forms}
    assert {(t.hour, t.minute) for (t,) in readings} == {(21, 30)}
    # Without a marker a time is never the evening: "9:30" is the morning
    assert not times_match(only("9:30").times[0], only("21:30").times[0])


def test_times_in_data_are_read_from_strings_and_from_time_objects() -> None:
    minus_five = timezone(timedelta(hours=-5))
    data = {
        "opens": "09:00",
        "window": "Delivery 8:00-12:00",
        "at": time(9, 30),
        "zoned": time(9, 30, tzinfo=minus_five),
        "seen": datetime(2026, 3, 8, 9, 30, 15),
        "stamp": "2026-03-08T09:30:00+03:00",
        "day": date(2026, 3, 8),
    }
    found = numbers_in_data(data)
    by_path: dict[tuple[str | int, ...], list[Token]] = {}
    for item in found:
        by_path.setdefault(item.path, []).append(item.token)
    assert [t.times for t in by_path[("opens",)]] == [(TimeOfDay(9, 0),)]
    assert [t.times for t in by_path[("window",)]] == [(TimeOfDay(8, 0),), (TimeOfDay(12, 0),)]
    assert [(t.kind, t.times) for t in by_path[("at",)]] == [("time", (TimeOfDay(9, 30, 0),))]
    # A time object is read from the object, so its zone of -05:00 is never a second time
    assert [(t.kind, t.times) for t in by_path[("zoned",)]] == [("time", (TimeOfDay(9, 30, 0),))]
    assert [t.times for t in by_path[("seen",)]] == [(TimeOfDay(9, 30, 15),)]
    assert [t.dates for t in by_path[("seen",)]] == [(PartialDate(2026, 3, 8),)]
    assert [t.times for t in by_path[("stamp",)]] == [(TimeOfDay(9, 30, 0),)]
    assert [t.times for t in by_path[("day",)]] == [()]
    # A time's parts are never values
    assert all(not token.values for tokens in by_path.values() for token in tokens)

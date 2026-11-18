"""Joined codes: a run of Latin letters and digits that is written as no figure is, read as a code.

Each row of the code table is one `code` token with its key; each row of the figure table keeps its
reading, with no code in it. `joined_codes=False` gives the reading from before joined codes, for
every row of both tables. A seeded property test at the end shows a code's digits are never a
number, whatever the code looks like.
"""

from __future__ import annotations

import random
import re
from decimal import Decimal

import pytest

from murshid._toolkit.number_text.core import (
    CODE_SHAPE,
    Token,
    code_key,
    figures_in,
    find_figure,
    numbers_in,
    numbers_in_data,
)

ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def summary(text: str, **options: object) -> list[tuple[str, str]]:
    tokens = numbers_in(text, **options)  # type: ignore[arg-type]
    return [(token.kind, token.text) for token in tokens]


def only(text: str, **options: object) -> Token:
    tokens = numbers_in(text, **options)  # type: ignore[arg-type]
    assert len(tokens) == 1, tokens
    return tokens[0]


# ---- the tables -------------------------------------------------------------------------------

# A code as written, its key, and how the text read before joined codes.
CODES: list[tuple[str, str, list[tuple[str, str]]]] = [
    ("V003", "V003", [("number", "003")]),
    ("WDD1771421J550011", "WDD1771421J550011", [("number", "1771421"), ("number", "550011")]),
    ("ORD-48213", "ORD48213", [("code", "ORD-48213")]),
    ("ord48213", "ORD48213", [("number", "48213")]),
    ("BK-2291", "BK2291", [("code", "BK-2291")]),
    ("COVID-19", "COVID19", [("code", "COVID-19")]),
    ("Flat-12", "FLAT12", [("code", "Flat-12")]),
    ("FY2026", "FY2026", [("number", "2026")]),
    ("H1", "H1", [("number", "1")]),
    ("LN0042", "LN0042", [("number", "0042")]),
    ("B2B", "B2B", [("number", "2")]),
    ("rq-17b", "RQ17B", [("number", "17")]),
    ("AB12CD34", "AB12CD34", [("number", "12"), ("number", "34")]),
    ("7B3", "7B3", [("number", "7"), ("number", "3")]),
    ("PR2026-0042", "PR20260042", [("number", "2026"), ("number", "0042")]),
    ("V٠٠٣", "V003", [("number", "٠٠٣")]),
    ("inv-٠٠٠٠٤١", "INV000041", [("code", "inv-٠٠٠٠٤١")]),
    # A unit, am, pm or an x before a hyphen starts a code, and so does a month with more pieces
    # than one day or year, or an ISO code that is also a common word or abbreviation
    ("CM-000012", "CM000012", [("code", "CM-000012")]),
    ("PM-0042", "PM0042", [("code", "PM-0042")]),
    ("AM-77", "AM77", [("code", "AM-77")]),
    ("X-200", "X200", [("code", "X-200")]),
    ("M-12", "M12", [("code", "M-12")]),
    ("km-2", "KM2", [("code", "km-2")]),
    ("MAR-2026-01", "MAR202601", [("code", "MAR-2026-01")]),
    ("Oct-19-20", "OCT1920", [("code", "Oct-19-20")]),
    ("mar-32", "MAR32", [("code", "mar-32")]),
    ("CVE-2024-3094", "CVE20243094", [("code", "CVE-2024-3094")]),
]


@pytest.mark.parametrize(("text", "key", "before"), CODES)
def test_a_joined_code_is_one_code_token_with_its_key(
    text: str, key: str, before: list[tuple[str, str]]
) -> None:
    token = only(text)
    assert (token.kind, token.span, token.code) == ("code", (0, len(text)), key)
    assert token.values == frozenset()
    # Inside a sentence the code keeps its span, and the figure beside it keeps its reading
    sentence = f"Ref {text}, total 4,120.50 SAR."
    assert summary(sentence) == [("code", text), ("number", "4,120.50")]


@pytest.mark.parametrize(("text", "key", "before"), CODES)
def test_without_joined_codes_a_code_reads_as_it_did_before(
    text: str, key: str, before: list[tuple[str, str]]
) -> None:
    assert summary(text, joined_codes=False) == before


# A figure as written, its reading, and how it read before joined codes when that differs: the
# default code shape read a currency, a month or am before a hyphen as a code.
FIGURES: list[tuple[str, list[tuple[str, str]], list[tuple[str, str]] | None]] = [
    # a number with a word joined after it
    ("150k", [("number", "150")], None),
    ("5pm", [("number", "5")], None),
    ("10am", [("number", "10")], None),
    ("3x", [("number", "3")], None),
    ("2br", [("number", "2")], None),
    ("1st", [("number", "1")], None),
    ("12th", [("number", "12")], None),
    ("100km", [("number", "100")], None),
    ("250ml", [("number", "250")], None),
    ("4G", [("number", "4")], None),
    ("3.5GHz", [("number", "3.5")], None),
    ("2-year", [("number", "2")], None),
    ("17-character", [("number", "17")], None),
    ("2-year-old", [("number", "2")], None),
    # a size: numbers joined by an x
    ("160x200", [("number", "160"), ("number", "200")], None),
    ("4x4", [("number", "4"), ("number", "4")], None),
    ("2x3x4", [("number", "2"), ("number", "3"), ("number", "4")], None),
    ("160x200cm", [("number", "160"), ("number", "200")], None),
    # a currency or an x joined to a number, before it or after it
    ("QAR138000", [("number", "138000")], None),
    ("AED168,994", [("number", "168,994")], None),
    ("USD1,500.00", [("number", "1,500.00")], None),
    ("SAR900", [("number", "900")], None),
    ("sar900", [("number", "900")], None),
    ("138000QAR", [("number", "138000")], None),
    ("x2", [("number", "2")], None),
    ("AED-500", [("number", "500")], [("code", "AED-500")]),
    ("SAR-900", [("number", "900")], [("code", "SAR-900")]),
    # a month before its day
    ("Oct19", [("number", "19")], None),
    ("Oct19th", [("number", "19")], None),
    ("oct-19", [("number", "19")], [("code", "oct-19")]),
    ("Jan-05", [("number", "05")], [("code", "Jan-05")]),
    ("Oct-19th", [("number", "19")], None),
    ("Sept-2026", [("number", "2026")], [("code", "Sept-2026")]),
    # a unit with its power
    ("m2", [("number", "2")], None),
    ("km2", [("number", "2")], None),
    ("cm3", [("number", "3")], None),
    ("100m2", [("number", "100"), ("number", "2")], None),
    # a time of day with am or pm on either side of a hyphen
    (
        "9:30 am-11:30 am",
        [("time", "9:30 am"), ("time", "11:30 am")],
        [("time", "9:30"), ("code", "am-11"), ("number", "30")],
    ),
    ("10am-5pm", [("number", "10"), ("number", "5")], None),
    ("9 am-5 pm", [("number", "9"), ("number", "5")], [("number", "9"), ("code", "am-5")]),
    # a time written with a point is a number, and the range keeps both
    (
        "8.30 am-5.30 pm",
        [("number", "8.30"), ("number", "5.30")],
        [("number", "8.30"), ("code", "am-5"), ("number", "30")],
    ),
    (
        "9.30 am-11.30 am",
        [("number", "9.30"), ("number", "11.30")],
        [("number", "9.30"), ("code", "am-11"), ("number", "30")],
    ),
    (
        "12.30 pm-1.30 pm",
        [("number", "12.30"), ("number", "1.30")],
        [("number", "12.30"), ("code", "pm-1"), ("number", "30")],
    ),
    (
        "9.00 AM-5.00 PM",
        [("number", "9.00"), ("number", "5.00")],
        [("number", "9.00"), ("code", "AM-5"), ("number", "00")],
    ),
    (
        "Open 8.30 am-5 pm",
        [("number", "8.30"), ("number", "5")],
        [("number", "8.30"), ("code", "am-5")],
    ),
    # a range, a space, digits alone, digits with letters only after them
    ("15-20", [("number", "15"), ("number", "20")], None),
    ("Flat 12", [("number", "12")], None),
    ("48213902", [("number", "48213902")], None),
    ("48213AB", [("number", "48213")], None),
    ("48213-AB", [("number", "48213")], None),
    # a run joined to more digits by a decimal mark is part of a number
    ("v1.2", [("number", "1.2")], None),
    ("x1.5", [("number", "1.5")], None),
    # Arabic letters never stand in a code
    ("ال٣٣٣", [("number", "٣٣٣")], None),
    ("٥٠٠جنيه", [("number", "٥٠٠")], None),
    ("رقم٧٧", [("number", "٧٧")], None),
]


@pytest.mark.parametrize(("text", "reading", "before"), FIGURES)
def test_a_figure_shape_keeps_its_reading_and_holds_no_code(
    text: str, reading: list[tuple[str, str]], before: list[tuple[str, str]] | None
) -> None:
    assert summary(text) == reading


@pytest.mark.parametrize(("text", "reading", "before"), FIGURES)
def test_without_joined_codes_a_figure_reads_as_it_did_before(
    text: str, reading: list[tuple[str, str]], before: list[tuple[str, str]] | None
) -> None:
    assert summary(text, joined_codes=False) == (reading if before is None else before)


def test_the_tables_are_as_large_as_the_brief_asks() -> None:
    assert len(CODES) >= 10
    assert len(FIGURES) >= 33


def test_a_code_ends_at_a_full_stop_or_a_comma_before_a_space() -> None:
    assert summary("Ask about V003.") == [("code", "V003")]
    assert summary("V003, V004 and V005.") == [("code", "V003"), ("code", "V004"), ("code", "V005")]
    # A decimal is never split between a code and a number, on either side of the run
    assert summary("V003.5") == [("number", "003.5")]
    assert summary("2.5V003") == [("number", "2.5"), ("number", "003")]
    # A mark after a number and before a letter splits nothing: a list typed without its space
    assert summary("1.V003 is open") == [("number", "1"), ("code", "V003")]
    assert summary("V3a.5") == [("code", "V3a"), ("number", "5")]


def test_the_same_code_written_two_ways_has_one_key() -> None:
    assert only("ord48213").code == only("ORD-48213").code == code_key("Ord-48213")
    assert only("v٠٠٣").code == only("V003").code


def test_a_space_makes_a_figure_and_a_hyphen_a_code() -> None:
    assert summary("Flat-12") == [("code", "Flat-12")]
    assert summary("Flat 12") == [("number", "12")]


def test_a_figure_beside_a_code_keeps_its_reading() -> None:
    text = "VIN: WDD1771421J550011, budget 150000"
    tokens = numbers_in(text)
    assert [(token.kind, token.text) for token in tokens] == [
        ("code", "WDD1771421J550011"),
        ("number", "150000"),
    ]
    assert tokens[1].readings == ((Decimal(150000),),)


def test_a_currency_before_a_hyphen_is_money_and_is_the_numbers_currency() -> None:
    token = only("Yes, it is SAR-900.")
    assert (token.kind, token.text, token.currency) == ("number", "900", "SAR")
    assert only("AED-500").currency == "AED"
    # In a range only the first number has the currency written beside it, as before
    assert [token.currency for token in numbers_in("SAR 15-20")] == ["SAR", ""]
    # Without joined codes a hyphen never joins a currency to a number
    assert only("SAR-900", joined_codes=False, code_shape=re.compile("(?!)")).currency == ""


def test_any_iso_code_in_capitals_joined_to_a_number_is_money() -> None:
    # The currency pattern names some currencies; every ISO 4217 code written in capitals is one
    # too, so a price in another currency is never taken for a code.
    for text, number in (("CAD120", "120"), ("ZAR-450", "450"), ("120NOK", "120"), ("SEK10", "10")):
        assert [(token.kind, token.text) for token in numbers_in(text)] == [("number", number)]
    assert find_figure(Decimal("120"), "Labour CAD120").where == "elsewhere"
    # In small letters a word that is also a code ("top", "all") is not taken for a currency.
    assert [(token.kind, token.text) for token in numbers_in("top10")] == [("code", "top10")]
    assert [(token.kind, token.text) for token in numbers_in("XYZ120")] == [("code", "XYZ120")]
    # Beside a number, the code is the number's currency; a word in small letters is none.
    assert [token.currency for token in numbers_in("120 CAD and NOK 75, all 5")] == [
        "CAD",
        "NOK",
        "",
    ]


def test_an_iso_code_that_is_also_a_word_is_no_currency_in_capitals() -> None:
    # "TOP", "ALL", "PHP" and "SOS" are ISO 4217 codes and also words people write in capitals,
    # so beside a number they are no currency, and joined to one they make a code.
    for text in ("TOP 5", "ALL 5", "PHP 8", "SOS 3", "The TOP 5 suppliers.", "ALL 5 are paid."):
        assert [(token.kind, token.currency) for token in numbers_in(text)] == [("number", "")]
    for text in ("50 KGS", "12 AWG", "RON 95"):
        assert [token.currency for token in numbers_in(text)] == [""], text
    assert summary("TOP10") == [("code", "TOP10")]
    assert summary("COP28") == [("code", "COP28")]
    # The other codes keep their currency, before or after the number, joined or apart
    for text, currency in (
        ("120 CAD", "CAD"),
        ("CAD120", "CAD"),
        ("NOK 75", "NOK"),
        ("It is 1,500 RUB.", "RUB"),
    ):
        assert [(token.kind, token.currency) for token in numbers_in(text)] == [
            ("number", currency)
        ]


def test_without_joined_codes_an_iso_code_the_pattern_does_not_name_is_no_currency() -> None:
    # Any ISO 4217 code beside a number belongs to the joined-code reading; without it only the
    # currency pattern stands beside a number, as before.
    text = "120 CAD, CAD120, NOK 75 and SAR 900"
    assert [token.currency for token in numbers_in(text)] == ["CAD", "CAD", "NOK", "SAR"]
    assert [token.currency for token in numbers_in(text, joined_codes=False)] == [
        "",
        "",
        "",
        "SAR",
    ]
    data = numbers_in_data({"price": "120 CAD"}, joined_codes=False)
    assert [item.token.currency for item in data] == [""]


def test_a_code_after_a_number_starts_with_pm_unless_it_is_a_time_range() -> None:
    assert summary("Credit note CM-000012") == [("code", "CM-000012")]
    assert summary("Unit 3 PM-0042") == [("number", "3"), ("code", "PM-0042")]
    assert summary("Rate 1.50 PM-0042") == [("number", "1.50"), ("code", "PM-0042")]
    assert summary("Open 9 am-5 pm daily") == [("number", "9"), ("number", "5")]
    assert summary("9:30 pm-11 pm") == [("time", "9:30 pm"), ("number", "11")]
    assert summary("The site is open 8.30 am-5.30 pm.") == [
        ("number", "8.30"),
        ("number", "5.30"),
    ]
    assert summary("9.30 am-11:30 am") == [("number", "9.30"), ("time", "11:30 am")]
    assert summary("9:30 am-11.30 am") == [("time", "9:30 am"), ("number", "11.30")]


def test_the_faults_read_as_codes_and_figures() -> None:
    assert summary("Vendor V003 has 3 open disputes.") == [("code", "V003"), ("number", "3")]
    assert summary("Your VIN is WDD1771421J550011.") == [("code", "WDD1771421J550011")]
    assert summary("Yes, it is SAR-900.") == [("number", "900")]


def test_a_date_and_a_time_in_digits_are_read_before_any_code() -> None:
    assert summary("2026-03-07T10:30:00Z") == [("date", "2026-03-07T10:30:00Z")]
    assert summary("2026-11-05T10:30-05:00 B7") == [
        ("date", "2026-11-05T10:30-05:00"),
        ("code", "B7"),
    ]
    assert summary("Gate 12:30, H1") == [("time", "12:30"), ("code", "H1")]


def test_quarters_stay_two_codes_in_a_range() -> None:
    assert summary("Q1-Q4") == [("code", "Q1"), ("code", "Q4")]
    assert summary("Q3 2026") == [("code", "Q3"), ("number", "2026")]


# ---- the caller's code shape ------------------------------------------------------------------


def test_your_own_code_shape_decides_first_and_joined_codes_read_what_it_leaves() -> None:
    shape = re.compile(r"(?<![A-Z0-9])REQ[0-9]{4}(?![A-Z0-9])")
    assert summary("REQ0042, V003 and 12", code_shape=shape) == [
        ("code", "REQ0042"),
        ("code", "V003"),
        ("number", "12"),
    ]
    assert summary("REQ0042, V003 and 12", code_shape=shape, joined_codes=False) == [
        ("code", "REQ0042"),
        ("number", "003"),
        ("number", "12"),
    ]


def test_your_own_code_shape_keeps_a_code_written_as_a_figure() -> None:
    # The default shape gives way to the joined-code rule; a shape of your own is read as written
    shape = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3}-[0-9]+(?![A-Za-z0-9])")
    assert summary("oct-19 and SAR-900", code_shape=shape) == [
        ("code", "oct-19"),
        ("code", "SAR-900"),
    ]
    assert summary("oct-19 and SAR-900", code_shape=CODE_SHAPE) == [
        ("number", "19"),
        ("number", "900"),
    ]


def test_a_currency_glued_to_a_number_is_still_never_a_code_for_your_own_shape() -> None:
    shape = re.compile(r"(?<![A-Z0-9])[A-Z]{3}[0-9]{3,6}(?![A-Z0-9])")
    assert summary("REF123 for SAR9000", code_shape=shape) == [
        ("code", "REF123"),
        ("number", "9000"),
    ]


# ---- the other readers take the same switch ---------------------------------------------------


def test_data_reads_joined_codes_and_takes_the_switch() -> None:
    data = {"vendor": "V003", "open": 3, "note": "Flat 12 and Flat-12"}
    found = [(item.path, item.token.kind, item.token.text) for item in numbers_in_data(data)]
    assert found == [
        (("vendor",), "code", "V003"),
        (("open",), "number", "3"),
        (("note",), "number", "12"),
        (("note",), "code", "Flat-12"),
    ]
    before = numbers_in_data({"vendor": "V003"}, joined_codes=False)
    assert [(item.token.kind, item.token.text) for item in before] == [("number", "003")]


def test_a_codes_digits_are_not_a_figure_unless_joined_codes_are_off() -> None:
    text = "Vendor V003 has open disputes."
    whole = [(0, len(text))]
    assert find_figure(3, text, whole).where == "absent"
    assert find_figure(3, text, whole, joined_codes=False).where == "cited"
    assert [token.text for token in figures_in(text)] == []
    assert [token.text for token in figures_in(text, joined_codes=False)] == ["003"]


# ---- property: a code's digits are never a number ---------------------------------------------

# Code prefixes that are no currency, month, unit, x, am or pm, in any case
PREFIXES = ["LN", "BK", "WDD", "V", "FY", "H", "REF", "ORD", "KT", "LOT", "ZR", "B", "TK", "VIN"]
INNER_LETTERS = "BCDFHJKLNRTVWZ"
FILLER = ["Vendor", "total", "the", "loan", "member", "المورد", "المجموع", "طلب", "(see)"]
JOINS = ["; {} ", " {} ", "، {} ", "\n{} ", " ({}) ", ", {} "]
# A date in digits inside a code is read as a date first, so the generator leaves those out
DATE_SHAPE = re.compile(r"[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}|[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}")


def digits(rng: random.Random, most: int = 7) -> str:
    return "".join(rng.choice("0123456789") for _ in range(rng.randrange(1, most + 1)))


def mixed_case(text: str, rng: random.Random) -> str:
    return "".join(char.lower() if rng.random() < 0.3 else char for char in text)


def code_piece(rng: random.Random) -> str:
    """A code of one of two families: letters then hyphen-digit groups (the default shape's), or a
    first piece of letters and digits followed by any pieces that each hold a digit."""
    while True:
        prefix = mixed_case(rng.choice(PREFIXES), rng)
        if rng.random() < 0.4:
            code = prefix + "".join("-" + digits(rng) for _ in range(rng.randrange(1, 4)))
        else:
            code = prefix + digits(rng)
            for _ in range(rng.randrange(0, 3)):
                code += rng.choice(INNER_LETTERS) + digits(rng, 4)
            for _ in range(rng.randrange(0, 3)):
                letters = rng.choice(["", rng.choice(INNER_LETTERS)])
                code += "-" + digits(rng, 5) + letters
        if not DATE_SHAPE.search(code):
            return code.translate(ARABIC_INDIC) if rng.random() < 0.15 else code


def test_a_codes_digits_are_never_read_as_a_number() -> None:
    rng = random.Random(20261019)  # noqa: S311 - made-up text, not a secret
    numbers_inside_without_joined = 0
    for _ in range(600):
        text = rng.choice(FILLER)
        codes: list[tuple[tuple[int, int], str]] = []
        numbers: list[tuple[tuple[int, int], Decimal]] = []
        for _ in range(rng.randrange(1, 8)):
            text += rng.choice(JOINS).format(rng.choice(FILLER))
            if rng.random() < 0.5:
                piece = code_piece(rng)
                codes.append(((len(text), len(text) + len(piece)), code_key(piece)))
            else:
                value = Decimal(rng.randrange(10**6))
                piece = str(value)
                numbers.append(((len(text), len(text) + len(piece)), value))
            text += piece
        tokens = numbers_in(text)
        by_span = {token.span: token for token in tokens}
        for span, key in codes:
            assert span in by_span, (text, text[slice(*span)], tokens)
            assert (by_span[span].kind, by_span[span].code) == ("code", key), (text, by_span[span])
        for span, value in numbers:
            assert by_span[span].readings == ((value,),), (text, by_span[span])
        inside = [
            token
            for token in tokens
            for (start, end), _ in codes
            if token.kind != "code" and token.span[0] < end and start < token.span[1]
        ]
        assert inside == [], (text, inside)
        before = numbers_in(text, joined_codes=False)
        numbers_inside_without_joined += sum(
            1
            for token in before
            for (start, end), _ in codes
            if token.kind == "number" and start <= token.span[0] and token.span[1] <= end
        )
    # The property has something to show: without joined codes, codes' digits are read as numbers
    assert numbers_inside_without_joined > 100

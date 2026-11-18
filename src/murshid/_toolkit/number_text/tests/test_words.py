"""Whole numbers from 0 to 9,999 written in English and Arabic words, with the dialect forms of the
product's document fixtures, "a dozen", and a range in words read as its highest number."""

from __future__ import annotations

from decimal import Decimal

import pytest

from murshid._toolkit.number_text.core import MAX_WORDS_VALUE, read_words, words_in

ENGLISH = [
    ("zero", 0),
    ("one", 1),
    ("four", 4),
    ("nine", 9),
    ("ten", 10),
    ("eleven", 11),
    ("fifteen", 15),
    ("Fifteen", 15),
    ("nineteen", 19),
    ("twenty", 20),
    ("forty", 40),
    ("twenty-five", 25),
    ("twenty five", 25),
    ("ninety-nine", 99),
    ("a hundred", 100),
    ("one hundred and five", 105),
    ("two hundred thirty-four", 234),
    ("fifteen hundred", 1500),
    ("twenty-five hundred", 2500),
    ("a thousand", 1000),
    ("two thousand and twenty-six", 2026),
    ("two thousand five hundred", 2500),
    ("nine thousand nine hundred ninety-nine", 9999),
    ("ninety-nine hundred one", 9901),
    ("a dozen", 12),
    ("two dozen", 24),
    ("half a dozen", 6),
    ("two or three", 3),
    ("two to three", 3),
    ("five or four", 5),
]

ARABIC = [
    ("صفر", 0),
    ("واحد", 1),
    ("اثنان", 2),
    ("إثنين", 2),
    ("ثلاثة", 3),
    ("ثَلَاثَة", 3),  # with diacritics
    ("ثلاثـة", 3),  # with a tatweel
    ("أربع", 4),
    ("عشرة", 10),
    ("أحد عشر", 11),
    ("إحدى عشرة", 11),
    ("اثنا عشر", 12),
    ("خمسة عشر", 15),
    ("عشرون", 20),
    ("خمسة وعشرون", 25),
    ("خمسة و عشرين", 25),
    ("تسعة وتسعون", 99),
    ("مئة", 100),
    ("مائة", 100),
    ("مئتان", 200),
    ("ثلاثمائة", 300),
    ("ثلاث مئة", 300),
    ("ألف", 1000),
    ("ألفان", 2000),
    ("ثلاثة آلاف", 3000),
    ("ألف ومئتان وخمسة وعشرون", 1225),
    ("ثلاثة آلاف وخمسمائة", 3500),
    ("تسعة آلاف وتسعمائة وتسعة وتسعون", 9999),
    ("دستة", 12),
]

# The forms people type in the Gulf, in Egypt and in the Levant
DIALECT = [
    ("ثنين", 2),
    ("تنين", 2),
    ("تلات", 3),
    ("تمانية", 8),
    ("حداشر", 11),
    ("احدعش", 11),
    ("اتناشر", 12),
    ("اثنعش", 12),
    ("خمستاشر", 15),
    ("خمسطعش", 15),
    ("تلاتين", 30),
    ("تمانين", 80),
    ("مية وخمسين", 150),  # مية alone is not read: see the test on water below
    ("ميه وعشرين", 120),
    ("تلات مية", 300),
    ("ألف ومية", 1100),
    ("مية أو ميتين", 200),
    ("ميتين", 200),
    ("تلتمية", 300),
    ("خمسمية", 500),
    ("تلات تلاف", 3000),
    ("خمستلاف", 5000),
    ("اتنين ولا تلاتة", 3),
    ("درزن", 12),
]

# Every number in words in the product's document fixtures (app/document_intake/fixtures/)
FIXTURES = [
    ("fifteen", 15),
    ("two or three", 3),
    ("forty", 40),
    ("one", 1),
    ("four", 4),
    ("اتنين", 2),
    ("تلاتة", 3),
    ("اتنين أو تلاتة", 3),
    ("واحدة", 1),
    ("عشرين", 20),
    ("لعشرين", 20),
    ("لثلاثين", 30),
    ("الواحد", 1),
]


@pytest.mark.parametrize(("text", "value"), ENGLISH + ARABIC + DIALECT + FIXTURES)
def test_a_number_in_words_reads(text: str, value: int) -> None:
    read = read_words(text)
    assert read.ok, read
    assert read.value == Decimal(value)


@pytest.mark.parametrize(
    "text",
    ["twelve thousand", "ten thousand", "five hundred thousand", "عشرة آلاف", "مئة ألف"],
)
def test_a_number_above_9999_is_out_of_range(text: str) -> None:
    assert read_words(text).reason == "out_of_range"
    assert words_in(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "about fifteen",
        "fifteen laptops",
        "fifteen, twenty",
        "lots",
        "a",
        "half",
        "15",
        "تلت",  # "a third" in Egyptian, not three
        "تمن",  # "price" in Egyptian, not eight
        "لست",  # "I am not", not "for six"
        "أحد",  # "anyone" or "Sunday" alone; one only in أحد عشر
        "مية",  # "water" alone in Egyptian; a hundred only inside a longer number
        "الاثنين",  # Monday
    ],
)
def test_anything_but_one_number_in_words_is_not_a_number(text: str) -> None:
    assert read_words(text).reason == "not_a_number"


@pytest.mark.parametrize(
    "text",
    [
        "يوم الاثنين",
        "الإثنين",
        "والاثنين",
        "بالاثنين",
        "للاثنين",
        "الاثنان",
        "يوم الاتنين",  # Monday as people type it in Egypt and the Levant
    ],
)
def test_monday_with_the_article_is_never_a_number(text: str) -> None:
    assert words_in(text) == []


def test_two_without_the_article_is_still_two() -> None:
    assert [(token.text, token.readings) for token in words_in("لاثنين واثنين")] == [
        ("لاثنين", ((Decimal(2),),)),
        ("واثنين", ((Decimal(2),),)),
    ]


@pytest.mark.parametrize(
    "text",
    ["مية", "ميه", "المية", "زجاجات مية معدنية", "كرتونة ميه", "مية مية"],
)
def test_the_dialect_hundred_alone_is_water_and_is_not_read(text: str) -> None:
    assert words_in(text) == []


@pytest.mark.parametrize("text", ["مئة", "مئه", "بمئة"])
def test_the_standard_hundred_with_its_hamza_is_read_alone(text: str) -> None:
    assert [token.readings for token in words_in(text)] == [((Decimal(100),),)]


def test_empty_text_is_empty() -> None:
    assert read_words("").reason == "empty"
    assert read_words(" \n").reason == "empty"


def test_punctuation_around_one_number_is_allowed() -> None:
    assert read_words("(fifteen)").value == Decimal(15)
    assert read_words("، لعشرين.").value == Decimal(20)


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("We need fifteen laptops for the new analysts", [("fifteen", 15)]),
        ("headsets, two or three for the support desk", [("two or three", 3)]),
        ("Last week I proposed forty storage boxes", [("forty", 40)]),
        ("We also need four rolls of shipping labels", [("four", 4)]),
        ("محتاجين كراسي للقاعة، اتنين أو تلاتة زيادة", [("اتنين أو تلاتة", 3)]),
        ("وضيافة الاجتماع الشهري لعشرين شخصًا", [("لعشرين", 20)]),
        ("لأن المساحة لا تكفي لثلاثين", [("لثلاثين", 30)]),
        ("شحنة واحدة قبل الموعد", [("واحدة", 1)]),
        ("fifteen, twenty", [("fifteen", 15), ("twenty", 20)]),
        ("two, or three", [("two", 2), ("three", 3)]),
        ("one or more items", [("one", 1)]),
        ("one hundred and five and six", [("one hundred and five", 105), ("six", 6)]),
        ("خمسة وستة", [("خمسة", 5), ("وستة", 6)]),  # a span covers the whole word, prefix too
        ("twelve thousand chairs and a dozen desks", [("a dozen", 12)]),
        ("No numbers here, only 15 in digits", []),
    ],
)
def test_words_in_finds_each_number_with_its_span(text: str, found: list[tuple[str, int]]) -> None:
    tokens = words_in(text)
    assert [(token.text, int(token.readings[0][0])) for token in tokens] == found
    for token in tokens:
        start, end = token.span
        assert text[start:end] == token.text
        assert token.in_words and token.kind == "number"


def test_the_largest_number_in_words_is_9999() -> None:
    assert MAX_WORDS_VALUE == 9999

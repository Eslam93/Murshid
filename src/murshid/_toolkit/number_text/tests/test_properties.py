"""Properties over many generated texts: every span reads back its value.

Each text mixes English and Arabic filler with numbers written in every form the decimal rule
reads (grouping by comma, point, no-break space or the Arabic separator; Arabic-Indic and Persian
digits; a currency glued on), dates in digits and with month names, and codes. The test knows where
it put each piece and what it means, and checks that `numbers_in` finds a token with exactly that
span, holding that value, and that reading the span alone gives the same token. The generator is
seeded, so a failure repeats.
"""

from __future__ import annotations

import random
from decimal import Decimal

from murshid._toolkit.number_text.core import (
    ARABIC_DECIMAL,
    ARABIC_GROUPING,
    PartialDate,
    TimeOfDay,
    Token,
    code_key,
    numbers_in,
    read_number,
    read_words,
    words_in,
)

NBSP = "\N{NO-BREAK SPACE}"
NNBSP = "\N{NARROW NO-BREAK SPACE}"
ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
FILLER = [
    "Supplier",
    "total",
    "the",
    "laptops",
    "per",
    "unit",
    "المورد",
    "المجموع",
    "للقطعة",
    "جهاز",
    "طلب",
    "(see)",
]
# Between two pieces there is always a word, so no piece joins the next one
JOINS = ["; {} ", " {} ", "، {} ", "\n{} ", " ({}) "]
MONTHS = ["January", "March", "June", "September", "October", "December"]
GULF = {1: "يناير", 3: "مارس", 6: "يونيو", 9: "سبتمبر", 10: "أكتوبر", 12: "ديسمبر"}
LEVANTINE = {
    1: "كانون الثاني",
    3: "آذار",
    6: "حزيران",
    9: "أيلول",
    10: "تشرين الأول",
    12: "كانون الأول",
}


def grouped(whole: str, mark: str) -> str:
    groups: list[str] = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return mark.join([whole, *groups])


def written(value: Decimal, rng: random.Random) -> str:
    """The value as a person might write it, in a form the rule reads with two decimal places."""
    whole, _, fraction = f"{value:.2f}".partition(".")
    fraction = fraction if rng.random() < 0.7 else fraction.rstrip("0")
    form = rng.randrange(7)
    if form == 0:  # plain
        text = whole + (f".{fraction}" if fraction else "")
    elif form == 1:  # comma groups, point decimal
        text = grouped(whole, ",") + (f".{fraction}" if fraction else "")
    elif form == 2:  # point groups, comma decimal
        text = grouped(whole, ".") + (f",{fraction}" if fraction else "")
    elif form == 3:  # no-break spaces group, comma decimal
        text = grouped(whole, rng.choice([NBSP, NNBSP])) + (f",{fraction}" if fraction else "")
    elif form == 4:  # the Arabic separators, in Arabic-Indic digits
        text = grouped(whole, ARABIC_GROUPING) + (f"{ARABIC_DECIMAL}{fraction}" if fraction else "")
        return text.translate(ARABIC_INDIC)
    elif form == 5:  # Persian digits
        text = grouped(whole, ARABIC_GROUPING) + (f"{ARABIC_DECIMAL}{fraction}" if fraction else "")
        return text.translate(PERSIAN)
    else:  # a currency glued on
        plain = whole + (f".{fraction}" if fraction else "")
        return rng.choice([f"SAR{plain}", f"{plain}SAR", f"{plain.translate(ARABIC_INDIC)}ريال"])
    return text


def random_value(rng: random.Random) -> Decimal:
    places = rng.choice([0, 0, 1, 2])
    whole = rng.choice([rng.randrange(10), rng.randrange(1000), rng.randrange(10**7)])
    fraction = rng.randrange(10**places) if places else 0
    return Decimal(f"{whole}.{fraction:0{places}d}") if places else Decimal(whole)


def date_piece(rng: random.Random) -> tuple[str, str, PartialDate]:
    year, month, day = rng.randrange(1990, 2100), rng.choice(list(GULF)), rng.randrange(1, 29)
    digits = rng.random() < 0.3
    form = rng.randrange(6)
    if form == 0:
        text, kind, reading = f"{year}-{month:02d}-{day:02d}", "date", PartialDate(year, month, day)
    elif form == 1:
        name = MONTHS[list(GULF).index(month)]
        text, kind, reading = f"{day} {name} {year}", "date", PartialDate(year, month, day)
    elif form == 2:
        name = MONTHS[list(GULF).index(month)]
        text, kind, reading = f"{name} {day}, {year}", "date", PartialDate(year, month, day)
    elif form == 3:
        text, kind, reading = f"{day} {GULF[month]} {year}", "date", PartialDate(year, month, day)
    elif form == 4:
        text, kind, reading = (
            f"{LEVANTINE[month]} {year}",
            "month_year",
            PartialDate(year, month, None),
        )
    else:
        name = MONTHS[list(GULF).index(month)]
        text, kind, reading = f"{name} {year}", "month_year", PartialDate(year, month, None)
    return (text.translate(ARABIC_INDIC) if digits else text), kind, reading


def code_piece(rng: random.Random) -> str:
    letters = rng.choice(["INV", "PO", "PR", "inv"])
    digits = "".join(rng.choice("0123456789") for _ in range(rng.randrange(1, 7)))
    code = f"{letters}-{digits}"
    return code.translate(ARABIC_INDIC) if rng.random() < 0.2 else code


def check_reads_back(token: Token, text: str) -> None:
    start, end = token.span
    again = numbers_in(text[start:end])
    assert len(again) == 1, (text[start:end], again)
    assert (again[0].kind, again[0].readings, again[0].dates, again[0].code) == (
        token.kind,
        token.readings,
        token.dates,
        token.code,
    )


def test_every_span_in_a_generated_text_reads_back_its_value() -> None:
    rng = random.Random(20261016)  # noqa: S311 - made-up text, not a secret
    for _ in range(400):
        text = rng.choice(FILLER)
        expected: list[tuple[tuple[int, int], str, object]] = []
        for _ in range(rng.randrange(1, 9)):
            text += rng.choice(JOINS).format(rng.choice(FILLER))
            choice = rng.random()
            if choice < 0.6:
                value = random_value(rng)
                piece = written(value, rng)
                offset = next(i for i, char in enumerate(piece) if char.isdigit())
                digits = piece[offset:].rstrip("SARريال")
                start = len(text) + offset
                expected.append(((start, start + len(digits)), "number", value))
            elif choice < 0.85:
                piece, kind, reading = date_piece(rng)
                expected.append(((len(text), len(text) + len(piece)), kind, reading))
            else:
                piece = code_piece(rng)
                expected.append(((len(text), len(text) + len(piece)), "code", code_key(piece)))
            text += piece
        tokens = {token.span: token for token in numbers_in(text)}
        for span, kind, meaning in expected:
            assert span in tokens, (text, span, text[slice(*span)], list(tokens))
            token = tokens[span]
            assert token.kind == kind, (text, token)
            if kind == "number":
                assert (meaning,) in token.readings, (text, token)
            elif kind == "code":
                assert token.code == meaning
            else:
                assert meaning in token.dates
            check_reads_back(token, text)


def test_every_written_form_reads_back_its_value_with_two_places() -> None:
    rng = random.Random(7)  # noqa: S311 - made-up text, not a secret
    for _ in range(2000):
        value = random_value(rng)
        text = written(value, rng)
        if not text[0].isdigit() or not text[-1].isdigit():
            continue  # a currency glued on: `read_number` reads one value alone
        read = read_number(text, max_places=2)
        assert read.value == value, (text, read)


ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
TEENS = [
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def english(value: int, rng: random.Random) -> str:
    """An independent writer of English number words, with the variants people use."""

    def below_hundred(number: int) -> str:
        if number < 10:
            return ONES[number]
        if number < 20:
            return TEENS[number - 10]
        tens, ones = divmod(number, 10)
        return TENS[tens] + (rng.choice(["-", " "]) + ONES[ones] if ones else "")

    if value == 0:
        return "zero"
    parts = []
    thousands, rest = divmod(value, 1000)
    hundreds, rest = divmod(rest, 100)
    if thousands:
        parts.append("a" if thousands == 1 and rng.random() < 0.3 else ONES[thousands])
        parts.append("thousand")
    if hundreds:
        parts.append("a" if hundreds == 1 and rng.random() < 0.3 else ONES[hundreds])
        parts.append("hundred")
    if rest:
        if parts and rng.random() < 0.5:
            parts.append("and")
        parts.append(below_hundred(rest))
    return " ".join(parts)


AR_ONES = ["صفر", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
AR_TENS = ["_", "_", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
AR_HUNDREDS = [
    "_",
    "مئة",
    "مئتان",
    "ثلاثمائة",
    "أربعمائة",
    "خمسمائة",
    "ستمائة",
    "سبعمائة",
    "ثمانمائة",
    "تسعمائة",
]


def arabic(value: int) -> str:
    """An independent writer of Modern Standard Arabic number words."""

    def below_hundred(number: int) -> str:
        if number < 10:
            return AR_ONES[number]
        if number == 10:
            return "عشرة"
        if number < 20:
            return {11: "أحد عشر", 12: "اثنا عشر"}.get(number, f"{AR_ONES[number - 10]} عشر")
        tens, ones = divmod(number, 10)
        return f"{AR_ONES[ones]} و{AR_TENS[tens]}" if ones else AR_TENS[tens]

    if value == 0:
        return "صفر"
    parts = []
    thousands, rest = divmod(value, 1000)
    hundreds, rest = divmod(rest, 100)
    if thousands:
        parts.append({1: "ألف", 2: "ألفان"}.get(thousands, f"{AR_ONES[thousands]} آلاف"))
    if hundreds:
        parts.append(AR_HUNDREDS[hundreds])
    if rest:
        parts.append(below_hundred(rest))
    return " و".join(parts)


def test_every_number_in_words_reads_back_in_english_and_arabic() -> None:
    rng = random.Random(9999)  # noqa: S311 - made-up text, not a secret
    values = [*range(0, 120), *(rng.randrange(10000) for _ in range(1500)), 9999]
    for value in values:
        for words in (english(value, rng), arabic(value)):
            assert read_words(words).value == Decimal(value), (value, words)
            sentence = f"نحتاج {words} قطعة" if words[0] > "z" else f"We need {words} pieces"
            tokens = words_in(sentence)
            assert [token.text for token in tokens] == [words], (sentence, tokens)
            assert tokens[0].readings == ((Decimal(value),),)


MORNING = ["am", "a.m.", "AM", "ص", "صباحًا"]
EVENING = ["pm", "p.m.", "PM", "م", "مساءً"]


def time_piece(rng: random.Random) -> tuple[str, TimeOfDay]:
    """A time of day as a person or a machine might write it, and the time it means."""
    hour, minute = rng.randrange(24), rng.randrange(60)
    second = rng.randrange(60) if rng.random() < 0.3 else None
    written_hour, marker = hour, ""
    if rng.random() < 0.4:  # on the 12-hour clock, with its marker
        written_hour = hour % 12 or 12
        marker = rng.choice(["", " ", NBSP]) + rng.choice(EVENING if hour >= 12 else MORNING)
    hour_text = f"{written_hour:02d}" if rng.random() < 0.5 else str(written_hour)
    text = f"{hour_text}:{minute:02d}" + (f":{second:02d}" if second is not None else "")
    if not marker and rng.random() < 0.15:
        text += rng.choice(["Z", "+03:00", "+0400"])
    text = text.translate(rng.choice([ARABIC_INDIC, PERSIAN])) if rng.random() < 0.3 else text
    return text + marker, TimeOfDay(hour, minute, second)


def test_every_time_in_a_generated_text_reads_back_its_time_of_day() -> None:
    rng = random.Random(20261017)  # noqa: S311 - made-up text, not a secret
    for _ in range(400):
        text = rng.choice(FILLER)
        expected: list[tuple[tuple[int, int], str, object]] = []
        for _ in range(rng.randrange(1, 9)):
            text += rng.choice(JOINS).format(rng.choice(FILLER))
            choice = rng.random()
            if choice < 0.5:
                piece, reading = time_piece(rng)
                expected.append(((len(text), len(text) + len(piece)), "time", reading))
            elif choice < 0.65:  # a timestamp: the date holds its time
                day = PartialDate(
                    rng.randrange(1990, 2100), rng.randrange(1, 13), rng.randrange(1, 29)
                )
                clock = TimeOfDay(rng.randrange(24), rng.randrange(60))
                piece = (
                    f"{day.year}-{day.month:02d}-{day.day:02d}{rng.choice('T ')}"
                    f"{clock.hour:02d}:{clock.minute:02d}"
                )
                expected.append(((len(text), len(text) + len(piece)), "date", (day, clock)))
            else:
                value = random_value(rng)
                piece = written(value, rng)
                offset = next(i for i, char in enumerate(piece) if char.isdigit())
                digits = piece[offset:].rstrip("SARريال")
                start = len(text) + offset
                expected.append(((start, start + len(digits)), "number", value))
            text += piece
        tokens = {token.span: token for token in numbers_in(text)}
        for span, kind, meaning in expected:
            assert span in tokens, (text, span, text[slice(*span)], list(tokens))
            token = tokens[span]
            assert token.kind == kind, (text, token)
            if kind == "time":
                assert token.times == (meaning,), (text, token)
                assert token.values == frozenset(), (text, token)
            elif kind == "date":
                assert isinstance(meaning, tuple)
                assert (token.dates, token.times) == ((meaning[0],), (meaning[1],)), (text, token)
            else:
                assert (meaning,) in token.readings, (text, token)
            start, end = span
            again = numbers_in(text[start:end])
            assert [(t.kind, t.times, t.dates, t.readings) for t in again] == [
                (token.kind, token.times, token.dates, token.readings)
            ], (text[start:end], again)

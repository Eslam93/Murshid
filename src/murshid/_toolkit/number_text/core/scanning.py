"""Every number, date, time and code in free text, as whole tokens with spans in the original.

`numbers_in` reads a text in six passes, and each pass claims its spans so that a later pass
never reads inside them:

1. Dates with a month name: "15 October 2026", "October 15, 2026", "October 2026" (a month and
   year), "October 15" and "15 October" (a day and month), in English and in Arabic, with the Gulf
   and Egyptian names (يناير to ديسمبر) and the Levantine names (كانون الثاني to كانون الأول).
   A day is never the hour or the minutes of a time: "10:15 October 2026" is a time and a month.
2. Codes, by the caller's shape: by default letters, a hyphen and digits (INV-000041, PO-2026-17)
   and the quarters Q1 to Q4. A currency glued to a number ("SAR900") is never a code. With joined
   codes on, the default shape also leaves a run written as a figure ("SAR-900", "oct-19").
3. Dates in digits: "2026-03-07" (with a time after it, if any, which the date token holds; after
   a time joined by a space, a hyphen is a range, never a zone), and "07/03/2026", which gives two
   readings, 7 March and 3 July, because the text does not say which.
4. Times: "9:00", "21:30:15", "9:30 pm", "٩:٣٠ م", on the 24-hour clock unless a marker says
   otherwise. A time is never part of a larger number, so "10:30:45:12" is four numbers, and a
   ratio such as "3:1" (its second part is not two digits) is two numbers.
5. Joined codes, unless the caller turns them off: a run of Latin letters and digits, with single
   hyphens between them, that holds a letter and a digit and is written as no figure is ("V003",
   "WDD1771421J550011", "ORD-48213"). See `_written_as_figure` for the figure shapes.
6. Numbers: a run of digits with the separators of the decimal rule between them. A plain space
   ends a number here; only the no-break spaces group, so "4 120,50" is two numbers, 4 and 120.50.

A number in free text is never refused. Where its form is ambiguous it gets every reading the form
allows: "1,500" reads as 1500 and as 1.5, and "lines 1,2 and 3" reads "1,2" as 1.2 and as the two
numbers 1 and 2. A reading is a tuple of values, so a caller can count a token as supported when
every value of any one reading is. A hyphen between numbers is a range, not a sign: "15-20" is 15
and 20. Numbers are read as magnitudes, so a changed sign is not seen.

Digits are folded first and the folding keeps every position, so each span indexes the original
text. List numbering at a line's start ("1.", "2)", "١-") is marked on the token, not dropped.
"""

from __future__ import annotations

import calendar
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from .reading import NO_BREAK_SPACES, _check_mark, _forms, _split, fold_arabic, fold_digits

__all__ = [
    "CODE_SHAPE",
    "CURRENCY_SHAPE",
    "DataToken",
    "PartialDate",
    "TimeOfDay",
    "Token",
    "TokenKind",
    "code_key",
    "dates_match",
    "is_id_key",
    "numbers_in",
    "numbers_in_data",
    "times_match",
]

TokenKind = Literal["number", "date", "month_year", "day_month", "code", "time"]

# Letters, a hyphen and digits, with more hyphen-digit groups allowed, and the quarters Q1 to Q4.
# A shape runs on the text with its digits folded to 0-9, so write [0-9], never \d. With joined
# codes on, a match of this default shape that is written as a figure ("SAR-900") is not a code.
CODE_SHAPE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]+(?:-[0-9]+)+|[Qq][1-4])(?![A-Za-z0-9])")

# ISO codes in capitals, symbols, and the words and abbreviations people write in English and
# Arabic. An Arabic word may carry its tanween or plural ending (ريالًا, ريالات).
_ISO = (
    "SAR|AED|KWD|BHD|OMR|QAR|EGP|JOD|LBP|IQD|SYP|YER|MAD|TND|DZD|LYD|SDG|USD|EUR|GBP|CHF|JPY|CNY|"
    "INR|PKR|TRY"
)
# Every active ISO 4217 code. Written in capitals beside a number, each is a currency even when
# the currency pattern does not name it ("CAD120", "120 NOK"), except the words below; in small
# letters many more are words ("cad", "nok"), so only capitals count, only with the default
# currency pattern, and only with joined codes on.
_ISO_4217_CODES = """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN
    BWP BYN BZD CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN
    ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD
    JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT
    MOP MRU MUR MVR MWK MXN MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG
    QAR RON RSD RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT
    TND TOP TRY TTD TWD TZS UAH UGX USD USN UYI UYU UYW UZS VED VES VND VUV WST XAF XAG XAU XBA
    XBB XBC XBD XCD XCG XDR XOF XPD XPF XPT XSU XUA YER ZAR ZMW ZWG
"""
ISO_4217 = frozenset(_ISO_4217_CODES.split())
# The ISO 4217 codes that are also English words or common abbreviations in capitals. They are no
# currency beside a number unless the currency pattern names them; a lift that prices in one adds
# it to the pattern.
_ISO_WORDS = frozenset(
    {
        "ALL",  # the word: "ALL 5 are paid"
        "AMD",  # a processor maker: "AMD 7"
        "AWG",  # a wire gauge: "12 AWG"
        "BAM",  # the word, and a file format
        "BOB",  # a name
        "COP",  # the word, and a climate conference: "COP28"
        "CUP",  # the word: "CUP 2"
        "CVE",  # a vulnerability id: "CVE-2024-3094"
        "GEL",  # the word: "GEL 5"
        "KGS",  # kilograms: "50 KGS"
        "MOP",  # the word
        "PEN",  # the word: "PEN 3"
        "PHP",  # a programming language: "PHP 8"
        "RON",  # an octane rating: "RON 95"
        "SOS",  # a call for help
        "TOP",  # the word: "TOP 5"
    }
)
_ISO_CURRENCIES = ISO_4217 - _ISO_WORDS
_ARABIC_WORDS = ("ريال", "درهم", "دينار", "جنيه", "دولار", "يورو", "ليرة", "ليره")
_ARABIC_ABBREVIATIONS = ("ر.س", "ر.ق", "ر.ع", "د.إ", "د.ك", "د.ب", "ج.م")
_ARABIC_ENDING = r"(?:[\N{ARABIC FATHATAN}-\N{ARABIC SUKUN}]*ا|ات)?"
CURRENCY_SHAPE = re.compile(
    "|".join(
        [
            _ISO,
            r"[$€£¥\N{RIAL SIGN}]",
            *(re.escape(abbreviation) for abbreviation in _ARABIC_ABBREVIATIONS),
            "(?:" + "|".join(_ARABIC_WORDS) + ")" + _ARABIC_ENDING,
            "(?i:(?:riyal|dirham|dinar|pound|dollar|euro)s?)",
        ]
    )
)

_SPACE_CLASS = "[ \t" + NO_BREAK_SPACES + "]"
_LETTER = r"[^\W\d_]"


@dataclass(frozen=True)
class PartialDate:
    """A calendar day, a month and year (`day` None), or a day and month (`year` None)."""

    year: int | None
    month: int
    day: int | None

    @property
    def full(self) -> date | None:
        """The calendar day, when all three parts are known."""
        if self.year is None or self.day is None:
            return None
        return date(self.year, self.month, self.day)


def dates_match(cited: PartialDate, known: PartialDate) -> bool:
    """Whether a date as cited is backed by a date as known.

    Every part the cited date has must be in the known date and equal: a full date matches the
    same calendar day, whatever form either was written in; a month and year matches any day of
    that month, or the same month and year; a day and month matches that day and month in any year.
    """
    if cited.month != known.month:
        return False
    if cited.year is not None and cited.year != known.year:
        return False
    return cited.day is None or cited.day == known.day


@dataclass(frozen=True)
class TimeOfDay:
    """A time of day on the 24-hour clock: "9:30 pm" is hour 21, minute 30. `second` is None when
    the time was written without seconds; a fraction of a second is dropped."""

    hour: int
    minute: int
    second: int | None = None


def times_match(cited: TimeOfDay, known: TimeOfDay) -> bool:
    """Whether a time as cited is backed by a time as known.

    The hour and the minute must be equal, and the second too when the cited time names one, as
    `dates_match` compares only the parts cited: "9:00" is backed by 09:00:30, because a person
    reads a clock to the minute, while "09:00:30" is not backed by "9:00". The minute is never
    rounded, so "9:01" is not backed by 09:00:59.
    """
    if (cited.hour, cited.minute) != (known.hour, known.minute):
        return False
    return cited.second is None or cited.second == known.second


@dataclass(frozen=True)
class Token:
    """One number, date, time or code found in a text.

    `span` is (start, end) in the original text and `text` is that slice. A number has `readings`,
    each a tuple of values, and the `currency` written beside it ("" when none); `numbering` is
    True for list numbering at a line's start. A date has `dates`, one per reading. A time has
    `times`, and so does a date in digits written with its time ("2026-03-07T10:30"), so a
    timestamp backs the time it holds. A code has `code`, its key for equality (see `code_key`).
    `in_words` is True for a number read from words. A date's and a time's parts are never values.
    """

    kind: TokenKind
    span: tuple[int, int]
    text: str
    readings: tuple[tuple[Decimal, ...], ...] = ()
    dates: tuple[PartialDate, ...] = ()
    code: str = ""
    currency: str = ""
    numbering: bool = False
    in_words: bool = False
    times: tuple[TimeOfDay, ...] = ()

    @property
    def values(self) -> frozenset[Decimal]:
        """Every value in any reading of a number."""
        return frozenset(value for reading in self.readings for value in reading)


def code_key(text: str) -> str:
    """A code's key for equality: its letters in upper case and its digits folded to 0-9, with
    every other character dropped. "inv-٠٠٠٠٤١" and "INV-000041" have the same key."""
    return "".join(char.upper() for char in fold_digits(text) if char.isalnum())


def is_id_key(key: str) -> bool:
    """Whether a key holds an id, whose digits are never a figure: `id` and keys ending in `_id`."""
    return key == "id" or key.endswith("_id")


# ---- dates with a month name ----------------------------------------------------------------

_ENGLISH_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
    "dec": 12,
}  # fmt: skip
_ARABIC_MONTHS = {
    # The Gulf and Egyptian names
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "إبريل": 4, "مايو": 5, "يونيو": 6, "يونية": 6,
    "يونيه": 6, "يوليو": 7, "يولية": 7, "يوليه": 7, "أغسطس": 8, "سبتمبر": 9, "أكتوبر": 10,
    "نوفمبر": 11, "ديسمبر": 12,
    # The Levantine names; the two-word ones also without the article, as people often write them
    "كانون الثاني": 1, "كانون ثاني": 1, "شباط": 2, "آذار": 3, "نيسان": 4, "أيار": 5,
    "حزيران": 6, "تموز": 7, "آب": 8, "أيلول": 9, "تشرين الأول": 10, "تشرين أول": 10,
    "تشرين الثاني": 11, "تشرين ثاني": 11, "كانون الأول": 12, "كانون أول": 12,
}  # fmt: skip


def _fold_letters(text: str) -> str:
    """Lower case, and the Arabic letter forms folded, one character for one, so positions do not
    move. The marks stay: removing them would move every position after them."""
    lowered = "".join(low if len(low := char.lower()) == 1 else char for char in text)
    return fold_arabic(lowered, marks=False)


_MONTHS = {
    **_ENGLISH_MONTHS,
    **{_fold_letters(name): month for name, month in _ARABIC_MONTHS.items()},
}
_MONTH_NAMES = "|".join(
    re.escape(name).replace(r"\ ", _SPACE_CLASS + "+")
    for name in sorted(_MONTHS, key=len, reverse=True)
)
_MONTH = rf"(?<!{_LETTER})(?P<month>{_MONTH_NAMES})\.?(?!{_LETTER})"
_NUMBER_MARK = "[.,\N{ARABIC DECIMAL SEPARATOR}\N{ARABIC THOUSANDS SEPARATOR}]"
# A day is never the fraction or the last group of a number: in "4120.15 October 2026" the 15
# belongs to 4120.15, and the month and year after it are still read. Nor is it the hour or the
# minutes of a time: in "10:15 October 2026" and "October 10:30" the time is read whole.
_DAY = (
    rf"(?<![0-9])(?<![A-Za-z0-9]-)(?<![0-9]{_NUMBER_MARK})(?<![0-9]:)"
    r"(?P<day>[0-9]{1,2})(?:st|nd|rd|th)?(?![0-9])(?!:[0-9])"
)
# A year is never the whole part of a number: "October 2026.5" is the number 2026.5. A year always
# comes after a space here, so only what follows it can join it to a number.
_YEAR = rf"(?<![0-9])(?P<year>[0-9]{{4}})(?![0-9])(?!{_NUMBER_MARK}[0-9])"
_GAP = _SPACE_CLASS + "+"
_COMMA = r"[,\N{ARABIC COMMA}]?"
_NAMED_DATE_SHAPES: tuple[tuple[TokenKind, str], ...] = (
    ("date", rf"{_DAY}{_GAP}(?:of{_GAP})?{_MONTH}{_COMMA}{_GAP}{_YEAR}"),
    ("date", rf"{_MONTH}{_GAP}{_DAY}{_COMMA}{_GAP}{_YEAR}"),
    ("month_year", rf"{_MONTH}{_COMMA}{_GAP}{_YEAR}"),
    ("day_month", rf"{_MONTH}{_GAP}{_DAY}"),
    ("day_month", rf"{_DAY}{_GAP}(?:of{_GAP})?{_MONTH}"),
)
_NAMED_DATES = tuple((kind, re.compile(shape)) for kind, shape in _NAMED_DATE_SHAPES)

# ---- times ------------------------------------------------------------------------------------

# A marker of the morning or the afternoon after a time, with an optional space before it. The
# English "a.m." keeps its last point, while "AM." at a sentence's end does not take the full stop.
# The Arabic ص and م, and the words صباحًا and مساءً with or without their tanween, are markers only
# when no letter follows, so "٩:٣٠ مساعد" has no marker.
_TANWEEN = "\N{ARABIC FATHATAN}?"
_AM = rf"(?i:a\.m\.?|am)(?![A-Za-z])|ص(?:باح{_TANWEEN}ا?{_TANWEEN})?(?!{_LETTER})"
_PM = rf"(?i:p\.m\.?|pm)(?![A-Za-z])|م(?:ساء{_TANWEEN}ا?{_TANWEEN})?(?!{_LETTER})"
_MARKER = rf"{_SPACE_CLASS}?(?:(?P<am>{_AM})|(?P<pm>{_PM}))"
# The hour, the minutes and the optional seconds; a fraction of a second belongs to the time.
_CLOCK = (
    r"(?P<clock>(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{2})"
    r"(?::(?P<second>[0-9]{2})(?:\.[0-9]+)?)?)"
)
# A time is never part of a larger number: no digit, clock colon or decimal mark joins it before
# or after, so "10:30:45:12" and "12:30.5" are numbers. A comma before it is a list ("8:00,9:00"),
# and a hyphen after it is a range ("8:00-9:30"), so only "Z" or a "+" offset is read as the time
# zone of a free-standing time; the offset belongs to the token and does not change its reading.
_TIME_OF_DAY = re.compile(
    r"(?<![0-9])(?<![0-9][:.\N{ARABIC DECIMAL SEPARATOR}])"
    + _CLOCK
    + rf"(?:Z(?![A-Za-z])|\+[0-9]{{2}}:?[0-9]{{2}}|{_MARKER})?"
    + r"(?![0-9])(?![:.\N{ARABIC DECIMAL SEPARATOR}][0-9])"
)


def _time_of_day(found: re.Match[str]) -> tuple[TimeOfDay, int] | None:
    """The time a match names and where its token ends, or None when it is not a time of day.

    A marker counts only on an hour from 1 to 12, as on a 12-hour clock ("12:30 am" is 00:30); on
    any other hour the time is read on the 24-hour clock and the marker is left outside the token,
    so "13:00 pm" is 13:00.
    """
    hour, minute = int(found.group("hour")), int(found.group("minute"))
    second = int(found.group("second")) if found.group("second") is not None else None
    if hour > 23 or minute > 59 or (second is not None and second > 59):
        return None
    end = found.end()
    marked = found.group("am") is not None or found.group("pm") is not None
    if marked and 1 <= hour <= 12:
        hour = hour % 12 + (12 if found.group("pm") is not None else 0)
    elif marked:
        end = found.end("clock")
    return TimeOfDay(hour, minute, second), end


# ---- dates in digits ------------------------------------------------------------------------

# The time after a date in digits: "2026-03-07T10:30:00Z", "2026-03-07 10:30:00+03:00", or
# "2026-03-07 10:30 pm". The date token holds it, so a timestamp backs the time it names. A "-"
# offset is read only after a "T" ("2026-03-07T10:30-05:00", as ISO 8601 writes it): after a space
# a hyphen is a range, so "2026-03-07 10:30-11:30" ends the date token at 10:30, and 11:30 is a
# time of its own that must be backed too.
_ZONE = r"[0-9]{2}:?[0-9]{2}"
_TIME = (
    rf"(?:(?:(?P<iso>T)| ){_CLOCK}"
    rf"(?:Z|\+{_ZONE}|(?(iso)-{_ZONE}|(?!))|{_MARKER})?(?![0-9])(?![.,/][0-9]))"
)
_NOT_IN_NUMBER = r"(?<![0-9.,\N{ARABIC DECIMAL SEPARATOR}\N{ARABIC THOUSANDS SEPARATOR}])"
_DATE_END = r"(?![0-9])(?![.,/-][0-9])"
_YEAR_FIRST = re.compile(
    _NOT_IN_NUMBER + r"(?P<year>[0-9]{4})(?P<sep>[-/.])(?P<month>[0-9]{1,2})(?P=sep)"
    r"(?P<day>[0-9]{1,2})" + rf"(?:{_TIME}|{_DATE_END})"
)
_YEAR_LAST = re.compile(
    _NOT_IN_NUMBER + r"(?<![/-])(?P<first>[0-9]{1,2})(?P<sep>[-/.])(?P<second>[0-9]{1,2})"
    r"(?P=sep)(?P<year>[0-9]{4})" + _DATE_END
)

# ---- numbers ----------------------------------------------------------------------------------

_SEPARATOR_CLASS = (
    "[,.\N{ARABIC DECIMAL SEPARATOR}\N{ARABIC THOUSANDS SEPARATOR}" + NO_BREAK_SPACES + "]"
)
_RUN = re.compile(
    r"(?:(?<![^\s(\[])[.\N{ARABIC DECIMAL SEPARATOR}](?=[0-9]))?"  # a leading point: ".5"
    r"(?<![0-9])[0-9]+(?:" + _SEPARATOR_CLASS + r"[0-9]+)*"
)
_BEFORE_NUMBERING = re.compile(
    r"[ \t\N{ARABIC LETTER MARK}\N{LEFT-TO-RIGHT MARK}\N{RIGHT-TO-LEFT MARK}]*"
    r"(?:[-*\N{BULLET}][ \t]+)?\(?"
)
_NUMBERING = re.compile(r"[0-9]{1,2}")
_MACHINE_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_UUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")

# ---- joined codes -----------------------------------------------------------------------------

# A run of Latin letters and digits with single hyphens between them. Arabic letters never stand in
# a code, so in "ال٣٣٣" and "٥٠٠جنيه" the run is the digits alone, which is a figure.
_JOINED_RUN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
# A decimal mark joins the digits on its two sides into one number, so a run never takes some of
# a number's digits: "v1.2" is 1.2 and "2.5V003" is 2.5 and 003, while "1.V003" holds a code.
_DECIMAL_JOIN = "[.,\N{ARABIC DECIMAL SEPARATOR}\N{ARABIC THOUSANDS SEPARATOR}]"
_NUMBER_BEFORE = re.compile(rf"[0-9]{_DECIMAL_JOIN}\Z")
_NUMBER_AFTER = re.compile(rf"{_DECIMAL_JOIN}[0-9]")
# One piece of a run that holds a digit, in the order a figure writes it: a word before the number
# ("QAR", "Oct", "x"), the number or a size of numbers joined by an x ("160x200"), a word after it
# ("k", "pm", "st", "km"), and the power of that word when it is a unit ("100m2").
_FIGURE_PIECE = re.compile(
    r"(?P<before>[A-Za-z]*)(?P<number>[0-9]+(?:[Xx][0-9]+)*)(?P<after>[A-Za-z]*)(?P<power>[23]?)"
)
# The units that take a power ("m2", "km3").
_UNITS = frozenset({"mm", "cm", "m", "km", "ft", "yd"})
# The one piece after a month and its hyphen: a day, with its ordinal ending, or a year.
_DAY_OR_YEAR = re.compile(r"(?:0?[1-9]|[12][0-9]|3[01])(?:st|nd|rd|th)?|[0-9]{4}", re.IGNORECASE)
# The hour after am or pm and its hyphen, in a time range: "9:30 am-11:30 am", "9 am-5pm". A
# colon or a point ends a run, so the minutes after the hour ("5:30", "5.30") stay outside it.
_HOUR = re.compile(r"[0-9]{1,2}(?:[ap]m)?", re.IGNORECASE)
# A time or an hour written right before a run, with at most one space: the am or pm that starts
# the run is its marker. The minutes may follow a colon or a point ("9:30 am", "8.30 am").
_TIME_BEFORE = re.compile(
    rf"(?<![0-9.,:])[0-9]{{1,2}}(?:[:.][0-9]{{2}}(?::[0-9]{{2}})?)?{_SPACE_CLASS}?\Z"
)


@lru_cache(maxsize=32)
def _in_any_case(shape: re.Pattern[str]) -> re.Pattern[str]:
    """The caller's currency shape, read in any case, as people type "sar900" and "Sar-900"."""
    return re.compile(shape.pattern, shape.flags | re.IGNORECASE)


def _is_currency(word: str, currency: re.Pattern[str]) -> bool:
    """Whether a word is a currency: the caller's pattern in any case, and with the default
    pattern any ISO 4217 code in capitals that is not also a word ("CAD", not "TOP")."""
    return _in_any_case(currency).fullmatch(word) is not None or (
        currency == CURRENCY_SHAPE and word in _ISO_CURRENCIES
    )


def _before_a_number(word: str, currency: re.Pattern[str]) -> bool:
    """Whether a word joined before a number makes it a figure: a currency ("QAR138000"), a
    month before its day ("Oct19") or an x ("x2")."""
    return word.lower() in ("x", *_ENGLISH_MONTHS) or _is_currency(word, currency)


def _starts_a_figure(pieces: list[str], currency: re.Pattern[str], after_a_time: bool) -> bool:
    """Whether a first piece of letters alone, before a hyphen, starts a figure: a currency before
    a number ("AED-500"), a month before one day or one year and nothing more ("oct-19",
    "Sept-2026"), or am or pm after a time and before an hour ("9:30 am-11:30 am")."""
    word, rest = pieces[0], pieces[1:]
    if not rest or not any(char.isdigit() for char in rest[0]):
        return False
    if _is_currency(word, currency):
        return True
    if word.lower() in _ENGLISH_MONTHS:
        return len(rest) == 1 and _DAY_OR_YEAR.fullmatch(rest[0]) is not None
    return word.lower() in ("am", "pm") and after_a_time and _HOUR.fullmatch(rest[0]) is not None


def _written_as_figure(run: str, currency: re.Pattern[str], *, after_a_time: bool = False) -> bool:
    """Whether a run of Latin letters, digits and single hyphens is written as a figure is: every
    piece between its hyphens is a figure's piece.

    A piece with a digit is a number with an optional word after it ("150k", "1st", "48213AB"), a
    size ("160x200", "4x4"), a number with a currency, a month or an x before it ("QAR138000",
    "Oct19", "x2"), or a unit with its power ("m2", "100m2"). A piece of letters alone is a figure's
    when a piece with a number came before it, as the number's word ("2-year", "17-character"), or
    when it comes first and `_starts_a_figure` says so ("AED-500", "oct-19"); `after_a_time` says a
    time or an hour is written right before the run. Anything else is a code: "ORD-48213",
    "COVID-19", "V003", and a unit, am, pm or an x before a hyphen ("CM-000012", "X-200").
    """
    pieces = run.split("-")
    if pieces[0].isalpha() and not _starts_a_figure(pieces, currency, after_a_time):
        return False
    after_a_number = False
    for index, piece in enumerate(pieces):
        if piece.isalpha():
            if not (index == 0 or after_a_number):
                return False
            continue
        found = _FIGURE_PIECE.fullmatch(piece)
        if found is None:
            return False
        before, number, after, power = found.group("before", "number", "after", "power")
        unit_power = before.lower() in _UNITS and number in ("2", "3") and not after
        if before and not (_before_a_number(before, currency) or unit_power):
            return False
        if power and after.lower() not in _UNITS:
            return False
        after_a_number = True
    return True


def _is_joined_code(run: str, currency: re.Pattern[str], *, after_a_time: bool = False) -> bool:
    """Whether a run is a joined code: it holds a digit and is written as no figure is, so it holds
    a letter too. Digits alone, and digits with letters only after them ("48213AB"), stay figures,
    as their shape cannot tell them apart from one."""
    return any(char.isdigit() for char in run) and not _written_as_figure(
        run, currency, after_a_time=after_a_time
    )


def _valid_day(year: int | None, month: int, day: int) -> bool:
    if not 1 <= month <= 12:
        return False
    return 1 <= day <= calendar.monthrange(2000 if year is None else year, month)[1]


def _named_date(kind: TokenKind, found: re.Match[str], original: str) -> PartialDate | None:
    groups = found.groupdict()
    month_text = original[found.start("month") : found.end("month")]
    if month_text == "may" and kind != "date":
        return None  # "may" in lower case is a verb far more often than a month
    month = _MONTHS[" ".join(groups["month"].split())]
    year = int(groups["year"]) if groups.get("year") else None
    day = int(groups["day"]) if groups.get("day") else None
    if day is not None and not _valid_day(year, month, day):
        return None
    return PartialDate(year, month, day)


def _numeric_date(found: re.Match[str]) -> tuple[PartialDate, ...]:
    groups = found.groupdict()
    year = int(groups["year"])
    if groups.get("month"):
        pairs = [(int(groups["month"]), int(groups["day"]))]
    else:  # day first, then month first, when each is a calendar day
        first, second = int(groups["first"]), int(groups["second"])
        pairs = [(second, first), (first, second)]
    readings = [
        PartialDate(year, month, day) for month, day in pairs if _valid_day(year, month, day)
    ]
    return tuple(dict.fromkeys(readings))


def _run_readings(run: str, decimal_mark: str | None) -> tuple[tuple[Decimal, ...], ...]:
    """Every reading of a run of digits and separators in free text; never empty."""
    split = _split(run)
    if split is None:  # the run pattern rules this out; read each group of digits alone
        return (tuple(Decimal(group) for group in re.findall("[0-9]+", run)),)
    groups, seps = split
    forms = _forms(groups, seps, None, decimal_mark) or []
    readings: list[tuple[Decimal, ...]] = [(form.value(),) for form in forms]
    if set(seps) == {","} and any(len(group) != 3 for group in groups[1:]):
        readings.append(tuple(Decimal(group) for group in groups))  # a list: "1,2" is 1 and 2
    if not readings:  # not one number: each group is a number of its own
        readings.append(tuple(Decimal(group) for group in groups if group))
    return tuple(dict.fromkeys(readings))


@lru_cache(maxsize=32)
def _currency_patterns(shape: re.Pattern[str]) -> tuple[re.Pattern[str], ...]:
    """Patterns for a currency right before a number, right after it, glued to it whole, and
    before it with a hyphen between them."""
    source, flags = shape.pattern, shape.flags
    before = re.compile(rf"(?<!{_LETTER})(?:{source}){_SPACE_CLASS}?\Z", flags)
    after = re.compile(rf"{_SPACE_CLASS}?(?:{source})(?!{_LETTER})", flags)
    glued = re.compile(
        rf"(?:{source}){_SPACE_CLASS}?[0-9][0-9.,]*|[0-9][0-9.,]*{_SPACE_CLASS}?(?:{source})", flags
    )
    hyphen = re.compile(rf"(?<!{_LETTER})(?:{source})(?=-\Z)", flags | re.IGNORECASE)
    return before, after, glued, hyphen


_ISO_CODES = "|".join(sorted(_ISO_CURRENCIES))
_ISO_AFTER = re.compile(rf"{_SPACE_CLASS}?(?:{_ISO_CODES})(?!{_LETTER})")
_ISO_BEFORE = re.compile(rf"(?<!{_LETTER})(?:{_ISO_CODES}){_SPACE_CLASS}?\Z")
_ISO_HYPHEN = re.compile(rf"(?<!{_LETTER})(?:{_ISO_CODES})(?=-\Z)")


def _currency(
    text: str, start: int, end: int, shape: re.Pattern[str], *, joined: bool = False
) -> str:
    """The currency written beside a number, or "". Two readings belong to joined codes and count
    only with `joined`: a currency joined before the number by a hyphen, as a joined code reads
    "SAR-900" as money, and, with the default currency pattern, any ISO 4217 code in capitals
    beside the number ("120 CAD"), except a code that is also a word ("TOP 5")."""
    before, after, _, hyphen = _currency_patterns(shape)
    patterns = [(after, before, hyphen)]
    if joined and shape == CURRENCY_SHAPE:
        patterns.append((_ISO_AFTER, _ISO_BEFORE, _ISO_HYPHEN))
    for after_it, before_it, hyphen_before in patterns:
        following = after_it.match(text, end)
        if following:
            return following.group().strip()
        preceding = before_it.search(text, max(0, start - 24), start)
        if preceding is None and joined:
            preceding = hyphen_before.search(text, max(0, start - 24), start)
        if preceding:
            return preceding.group().strip()
    return ""


def _is_numbering(folded: str, start: int, end: int) -> bool:
    """Whether the number at start..end is list numbering: one or two digits at a line's start
    (after spaces and an optional bullet), followed by ".", ")" or "-" and then a space."""
    if not _NUMBERING.fullmatch(folded, start, end):
        return False
    line_start = folded.rfind("\n", 0, start) + 1
    if not _BEFORE_NUMBERING.fullmatch(folded, line_start, start):
        return False
    after = folded[end : end + 2]
    return after[:1] in (".", ")", "-") and after[1:] in ("", " ", "\t", "\n", "\r")


def numbers_in(
    text: str,
    *,
    decimal_mark: str | None = None,
    code_shape: re.Pattern[str] = CODE_SHAPE,
    currency_shape: re.Pattern[str] = CURRENCY_SHAPE,
    joined_codes: bool = True,
) -> list[Token]:
    """Every number, date and code in a text, in the order they appear.

    `decimal_mark` is the text's decimal mark ("," or ".") when the caller knows it; it settles
    "1,500" to one reading. `code_shape` is the caller's code pattern, and `currency_shape` the
    currencies that may be written right before or after a number. `joined_codes` reads a run of
    Latin letters and digits written as no figure is as a code ("V003"), after the caller's code
    shape and before any number, and with the default currency pattern reads any ISO 4217 code in
    capitals beside a number as its currency ("120 CAD"); False gives the reading without either.
    """
    _check_mark(decimal_mark)
    folded = fold_digits(text)
    claimed = bytearray(len(text))
    tokens: list[Token] = []

    def claim(token: Token) -> None:
        start, end = token.span
        if start < end and not any(claimed[start:end]):
            claimed[start:end] = b"\x01" * (end - start)
            tokens.append(token)

    def masked() -> str:
        return "".join("\0" if claimed[index] else char for index, char in enumerate(folded))

    def span_of(found: re.Match[str]) -> tuple[int, int]:
        return found.start(), found.end()

    letters = _fold_letters(folded)
    for kind, pattern in _NAMED_DATES:
        for found in pattern.finditer(letters):
            reading = _named_date(kind, found, folded)
            if reading is not None:
                span = span_of(found)
                claim(Token(kind, span, text[slice(*span)], dates=(reading,)))

    glued = _currency_patterns(currency_shape)[2]
    # The default shape gives way to the joined-code rule, so "SAR-900" is money and "oct-19" the
    # number 19 after its month; a shape of the caller's own is read as written.
    default_shape = joined_codes and code_shape == CODE_SHAPE
    for found in code_shape.finditer(masked()):
        written = found.group()
        if glued.fullmatch(written):
            continue
        one_run = default_shape and _JOINED_RUN.fullmatch(written) is not None
        start = found.start()
        after_a_time = _TIME_BEFORE.search(folded, max(0, start - 12), start) is not None
        if one_run and _written_as_figure(written, currency_shape, after_a_time=after_a_time):
            continue
        span = span_of(found)
        claim(Token("code", span, text[slice(*span)], code=code_key(written)))

    for pattern in (_YEAR_FIRST, _YEAR_LAST):
        for found in pattern.finditer(masked()):
            readings = _numeric_date(found)
            if readings:
                start, end = span_of(found)
                times: tuple[TimeOfDay, ...] = ()
                # A time that is no time of day ("25:99") stays inside the date token, so its
                # digits are never numbers, and it backs nothing.
                clock = _time_of_day(found) if found.groupdict().get("clock") else None
                if clock is not None:
                    at, end = clock
                    times = (at,)
                claim(Token("date", (start, end), text[start:end], dates=readings, times=times))

    for found in _TIME_OF_DAY.finditer(masked()):
        clock = _time_of_day(found)
        if clock is not None:
            at, end = clock
            start = found.start()
            claim(Token("time", (start, end), text[start:end], times=(at,)))

    # After the dates and times in digits, so a timestamp ("2026-03-07T10:30") is never a code
    if joined_codes:
        runs = masked()
        for found in _JOINED_RUN.finditer(runs):
            start, end = span = span_of(found)
            run = found.group()
            in_a_number = (
                run[0].isdigit() and _NUMBER_BEFORE.search(runs, max(0, start - 2), start)
            ) or (run[-1].isdigit() and _NUMBER_AFTER.match(runs, end))
            after_a_time = _TIME_BEFORE.search(folded, max(0, start - 12), start) is not None
            if not in_a_number and _is_joined_code(run, currency_shape, after_a_time=after_a_time):
                claim(Token("code", span, text[start:end], code=code_key(run)))

    for found in _RUN.finditer(masked()):
        start, end = span = span_of(found)
        token = Token(
            "number",
            span,
            text[start:end],
            readings=_run_readings(found.group(), decimal_mark),
            currency=_currency(text, start, end, currency_shape, joined=joined_codes),
            numbering=_is_numbering(folded, start, end),
        )
        claim(token)
    return sorted(tokens, key=lambda token: token.span)


@dataclass(frozen=True)
class DataToken:
    """A token found in structured data, with the path to the value that holds it.

    The path holds keys and list positions; positions count from one, as people count.
    """

    path: tuple[str | int, ...]
    token: Token


def _exact(value: Decimal, text: str) -> Token:
    return Token("number", (0, len(text)), text, readings=((abs(value),),))


def _clock_of(value: time) -> TimeOfDay:
    """A time object's time of day, as written in its own zone, with its seconds."""
    return TimeOfDay(value.hour, value.minute, value.second)


def numbers_in_data(
    data: object,
    *,
    is_id: Callable[[str], bool] = is_id_key,
    decimal_mark: str | None = None,
    code_shape: re.Pattern[str] = CODE_SHAPE,
    currency_shape: re.Pattern[str] = CURRENCY_SHAPE,
    joined_codes: bool = True,
) -> list[DataToken]:
    """Every number, date and code in structured data, such as a tool's result.

    Mappings and lists are walked. A value under a key that `is_id` names is skipped, and so is a
    UUID anywhere, so the digits of an id never count as a figure. None and booleans hold nothing.
    A number (int, float or Decimal) is one exact value, and so is a string that is a plain machine
    number ("4120.50", "-12"). A date is a calendar day, a datetime a calendar day with its time,
    and a time a time of day (its time zone is not read). Any other value is read as free text
    with `numbers_in`, so "09:00" is a time, "V003" a code, and its spans index the value's own
    text; `decimal_mark`, `code_shape`, `currency_shape` and `joined_codes` are passed to it.
    Numbers are magnitudes.
    """
    found: list[DataToken] = []

    def walk(value: object, path: tuple[str | int, ...]) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not (isinstance(key, str) and is_id(key)):
                    walk(item, (*path, key))
        elif isinstance(value, list | tuple):
            for position, item in enumerate(value, start=1):
                walk(item, (*path, position))
        elif value is None or isinstance(value, bool):
            return
        elif isinstance(value, int):
            found.append(DataToken(path, _exact(Decimal(value), str(value))))
        elif isinstance(value, float):
            if math.isfinite(value):
                found.append(DataToken(path, _exact(Decimal(repr(value)), repr(value))))
        elif isinstance(value, Decimal):
            if value.is_finite():
                found.append(DataToken(path, _exact(value, str(value))))
        elif isinstance(value, date):
            day = value.date() if isinstance(value, datetime) else value
            text = value.isoformat()
            reading = PartialDate(day.year, day.month, day.day)
            times = (_clock_of(value.time()),) if isinstance(value, datetime) else ()
            token = Token("date", (0, len(text)), text, dates=(reading,), times=times)
            found.append(DataToken(path, token))
        elif isinstance(value, time):
            # Read from the object, not its text: "09:00:00-05:00" in free text is a range.
            text = value.isoformat()
            token = Token("time", (0, len(text)), text, times=(_clock_of(value),))
            found.append(DataToken(path, token))
        else:
            text = str(value)
            if _UUID.fullmatch(text.strip()):
                return
            if _MACHINE_NUMBER.fullmatch(text):
                found.append(DataToken(path, _exact(Decimal(text), text)))
                return
            tokens = numbers_in(
                text,
                decimal_mark=decimal_mark,
                code_shape=code_shape,
                currency_shape=currency_shape,
                joined_codes=joined_codes,
            )
            found.extend(DataToken(path, token) for token in tokens)

    walk(data, ())
    return found

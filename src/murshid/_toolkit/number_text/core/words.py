"""Reading whole numbers from 0 to 9,999 written in English or Arabic words.

`words_in` finds every number written in words in a text, with its span: "fifteen", "twenty-five",
"one hundred and five", "a dozen" (12), "half a dozen" (6), "خمسة وعشرين" (25), "ألف ومئتان"
(1200). A range in words reads as its highest number: "two or three" is 3, and so is
"اتنين أو تلاتة". `read_words` reads a text that is one such number and nothing else.

Arabic is read in Modern Standard Arabic and in the Gulf, Egyptian and Levantine forms people type:
اتنين and ثنين for two, تلاتة for three, حداشر and احدعش for eleven, تلتمية for three hundred, تلت
تلاف for three thousand. Letters are compared after `fold_arabic` (hamza forms, ta marbuta, alef
maqsura, diacritics and tatweel), and a word may carry a prefix: و ("and"), ل ("for"), ب ("by") or
the article, so لعشرين reads as 20.

Some number words have another meaning: "one" as a pronoun, ست ("six", and "Mrs" in Egyptian),
سبع ("seven", and "lion"). They are read as numbers; a caller that needs the difference reads
the words around them. Two Egyptian forms are read only inside a longer word, because alone they
more often mean something else: تلت ("a third") and تمن ("price"). مية (and ميه) is a hundred and
also "water" in Egyptian, so it is read only inside a longer number: "مية وخمسين" is 150 and
"تلات مية" is 300, but مية alone, or "مية ريال", is not read. Two with the article (الاثنين,
الاتنين) is Monday, and is never read. Ordinals ("first"), fractions ("half" alone) and numbers
above 9,999 are not read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from .reading import NO_BREAK_SPACES, NumberRead, fold_arabic
from .scanning import Token

__all__ = ["MAX_WORDS_VALUE", "read_words", "words_in"]

MAX_WORDS_VALUE = 9999

_Kind = Literal[
    "unit",  # 0 to 9
    "ten_word",  # Arabic عشر and عشرة: 10 alone, or the end of a teen ("خمسة عشر")
    "teen_head",  # Arabic أحد, إحدى, اثنا, اثني: only before عشر, for 11 and 12
    "teen",  # 10 to 19 in one word
    "tens",  # 20 to 90
    "hundred_word",  # English "hundred": a multiplier
    "hundreds",  # Arabic 100 to 900 in one word
    "thousand_word",  # English "thousand": a multiplier
    "thousand",  # Arabic ألف: 1000, or a multiplier after a number
    "thousands",  # Arabic آلاف and تلاف: a multiplier after 3 to 10
    "thousands_value",  # Arabic 2000 to 9000 in one word
    "dozen",  # 12, or a multiplier
    "a",
    "half",
    "and",
    "or",  # a range: "two or three", "two to three", "اتنين أو تلاتة"
    "other",
]

_ENGLISH: dict[_Kind, dict[str, int]] = {
    "unit": {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9,
    },
    "teen": {
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    },
    "tens": {
        "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90,
    },
    "hundred_word": {"hundred": 100},
    "thousand_word": {"thousand": 1000},
    "dozen": {"dozen": 12},
    "a": {"a": 1},
    "half": {"half": 0},
    "and": {"and": 0},
    "or": {"or": 0, "to": 0},
}  # fmt: skip

_ARABIC: dict[_Kind, dict[str, int]] = {
    "unit": {
        "صفر": 0,
        "واحد": 1, "واحدة": 1,
        "اثنان": 2, "اثنين": 2, "اثنتان": 2, "اثنتين": 2, "اتنين": 2, "ثنين": 2, "تنين": 2,
        "ثنتين": 2, "تنتين": 2, "اتنتين": 2,
        "ثلاثة": 3, "ثلاث": 3, "تلاتة": 3, "تلات": 3,
        "أربعة": 4, "أربع": 4,
        "خمسة": 5, "خمس": 5,
        "ستة": 6, "ست": 6,
        "سبعة": 7, "سبع": 7,
        "ثمانية": 8, "ثماني": 8, "ثمان": 8, "تمانية": 8, "تمان": 8, "تماني": 8, "تمنية": 8,
        "تسعة": 9, "تسع": 9,
    },
    "ten_word": {"عشرة": 10, "عشر": 10},
    "teen_head": {"أحد": 1, "إحدى": 1, "اثنا": 2, "اثني": 2, "اثنتا": 2, "اثنتي": 2},
    "teen": {
        "حداشر": 11, "احداشر": 11, "احدعش": 11, "حدعش": 11,
        "اتناشر": 12, "اثناشر": 12, "اطناشر": 12, "اثنعش": 12, "ثنعش": 12, "اتنعش": 12,
        "تنعش": 12, "طنعش": 12,
        "تلتاشر": 13, "تلطاشر": 13, "ثلطعش": 13, "تلطعش": 13, "ثلاثطعش": 13, "ثلتعش": 13,
        "أربعتاشر": 14, "اربعطاشر": 14, "أربعطعش": 14, "ربعطعش": 14,
        "خمستاشر": 15, "خمسطاشر": 15, "خمسطعش": 15, "خمستعش": 15,
        "ستاشر": 16, "سطاشر": 16, "ستطعش": 16, "سطعش": 16, "ستعش": 16,
        "سبعتاشر": 17, "سبعطاشر": 17, "سبعطعش": 17, "سبعتعش": 17,
        "تمنتاشر": 18, "تمانتاشر": 18, "ثمنتاشر": 18, "تمنطاشر": 18, "ثمنطعش": 18,
        "تمنطعش": 18, "ثمانطعش": 18,
        "تسعتاشر": 19, "تسعطاشر": 19, "تسعطعش": 19, "تسعتعش": 19,
    },
    "tens": {
        "عشرون": 20, "عشرين": 20,
        "ثلاثون": 30, "ثلاثين": 30, "تلاتين": 30,
        "أربعون": 40, "أربعين": 40,
        "خمسون": 50, "خمسين": 50,
        "ستون": 60, "ستين": 60,
        "سبعون": 70, "سبعين": 70,
        "ثمانون": 80, "ثمانين": 80, "تمانين": 80,
        "تسعون": 90, "تسعين": 90,
    },
    "hundreds": {
        "مئة": 100, "مائة": 100, "مية": 100,
        "مئتان": 200, "مئتين": 200, "مائتان": 200, "مائتين": 200, "ميتين": 200, "متين": 200,
        "مئتا": 200, "مائتا": 200,
        "ثلاثمئة": 300, "ثلاثمائة": 300, "ثلاثمية": 300, "ثلثمية": 300, "ثلثمائة": 300,
        "تلتمية": 300, "تلاتمية": 300,
        "أربعمئة": 400, "أربعمائة": 400, "أربعمية": 400, "ربعمية": 400,
        "خمسمئة": 500, "خمسمائة": 500, "خمسمية": 500,
        "ستمئة": 600, "ستمائة": 600, "ستمية": 600,
        "سبعمئة": 700, "سبعمائة": 700, "سبعمية": 700,
        "ثمانمئة": 800, "ثمانمائة": 800, "ثمنمائة": 800, "ثمانمية": 800, "ثمنمية": 800,
        "تمنمية": 800, "تمانمية": 800,
        "تسعمئة": 900, "تسعمائة": 900, "تسعمية": 900,
    },
    "thousand": {"ألف": 1000, "ألفا": 1000},
    "thousands": {"آلاف": 1000, "ألاف": 1000, "تلاف": 1000},
    "thousands_value": {
        "ألفان": 2000, "ألفين": 2000, "ألفي": 2000,
        "تلتلاف": 3000, "تلاتلاف": 3000, "أربعتلاف": 4000, "خمستلاف": 5000, "ستلاف": 6000,
        "سبعتلاف": 7000, "تمنتلاف": 8000, "تمانتلاف": 8000, "تسعتلاف": 9000,
    },
    "dozen": {"دستة": 12, "درزن": 12, "دزينة": 12},
    "and": {"و": 0},
    "or": {"أو": 0, "ولا": 0, "إلى": 0},
}  # fmt: skip

_ARTICLES = ("وال", "بال", "لل", "ال")  # the article, alone or after و, ب or ل
_PREFIXES = (*_ARTICLES, "و", "ل", "ب")
_WORD = re.compile(
    r"(?:[^\W\d_]|[\N{ARABIC FATHATAN}-\N{ARABIC WAVY HAMZA BELOW}"
    r"\N{ARABIC LETTER SUPERSCRIPT ALEF}])+"
)
_GAP = re.compile("[ \t" + NO_BREAK_SPACES + "]*(?:-[ \t" + NO_BREAK_SPACES + "]*)?")


def _fold_word(word: str) -> str:
    return fold_arabic(word).lower()


_LEXICON: dict[str, tuple[_Kind, int]] = {
    _fold_word(word): (kind, value)
    for table in (_ENGLISH, _ARABIC)
    for kind, words in table.items()
    for word, value in words.items()
}
# With the article, two is the name of a day: الاثنين is Monday, written الاتنين in Egypt and the
# Levant. These are read as the day, never as a number.
_DAY_WITH_ARTICLE = frozenset(map(_fold_word, ("اثنين", "اثنان", "اتنين")))
# مية is a hundred and, in Egyptian, also "water", which alone is the more common meaning in an
# order ("مية معدنية", mineral water). It is read as a hundred only inside a longer number in
# words: "مية وخمسين" (150), "تلات مية" (300), "ألف ومية" (1100). ميه folds to the same word, and
# so does the standard مئة; "water" is never written with that hamza, so مئة alone stays 100.
_ONLY_IN_A_LONGER_NUMBER = frozenset(map(_fold_word, ("مية",)))
_HAMZA_ON_YA = "\N{ARABIC LETTER YEH WITH HAMZA ABOVE}"


def _alone(word: str, folded: str) -> bool:
    """Whether a number word, as written and as folded, is a number with no other number word."""
    return folded not in _ONLY_IN_A_LONGER_NUMBER or _HAMZA_ON_YA in word


@dataclass(frozen=True)
class _Item:
    kind: _Kind
    value: int
    start: int
    end: int
    # False for a word that is a number only beside another number word (see above)
    alone: bool = True


def _items(word: str, start: int, end: int) -> list[_Item]:
    """The items one word holds: itself, or an Arabic prefix and the number word after it."""
    folded = _fold_word(word)
    if folded in _LEXICON:
        return [_Item(*_LEXICON[folded], start, end, _alone(word, folded))]
    for prefix in _PREFIXES:
        rest = folded[len(prefix) :]
        if folded.startswith(prefix) and len(rest) >= 3 and rest in _LEXICON:
            if prefix in _ARTICLES and rest in _DAY_WITH_ARTICLE:
                break
            kind, value = _LEXICON[rest]
            joined = [_Item("and", 0, start, end)] if prefix.startswith("و") else []
            return [*joined, _Item(kind, value, start, end, _alone(word, rest))]
    return [_Item("other", 0, start, end)]


def _chains(text: str) -> list[list[_Item]]:
    """The text's words as items, in chains of words with only spaces or a hyphen between them."""
    chains: list[list[_Item]] = []
    last_end = -1
    for found in _WORD.finditer(text):
        start, end = found.span()
        if not chains or not _GAP.fullmatch(text, last_end, start):
            chains.append([])
        chains[-1].extend(_items(found.group(), start, end))
        last_end = end
    return chains


_Parsed = tuple[int, int] | None  # (value, index after the last item used), or None
_SCALES: dict[_Kind | None, int] = {
    "hundred_word": 100,
    "thousand_word": 1000,
    "thousand": 1000,
    "thousands": 1000,
}


class _Parser:
    """A small recursive reader of one chain of items."""

    def __init__(self, items: list[_Item]) -> None:
        self.items = items

    def kind(self, at: int) -> _Kind | None:
        return self.items[at].kind if at < len(self.items) else None

    def value(self, at: int) -> int:
        return self.items[at].value

    def tens(self, at: int) -> _Parsed:
        """0 to 99: a teen, "twenty five", "خمسة وعشرين", "خمسة عشر", or a unit."""
        kind = self.kind(at)
        if kind is None:
            return None
        small = kind in ("unit", "teen_head") and 1 <= self.value(at) <= 9
        if small and self.kind(at + 1) == "ten_word":
            return 10 + self.value(at), at + 2
        if small and kind == "unit" and self.kind(at + 1) == "and" and self.kind(at + 2) == "tens":
            return self.value(at) + self.value(at + 2), at + 3
        if kind == "tens":
            if self.kind(at + 1) == "unit" and 1 <= self.value(at + 1) <= 9:
                return self.value(at) + self.value(at + 1), at + 2
            return self.value(at), at + 1
        if kind in ("teen", "unit", "ten_word"):
            return self.value(at), at + 1
        return None

    def multiplier(self, at: int) -> _Parsed:
        """What may stand before "hundred", "thousand" or "dozen": "a", or a number below 100."""
        if self.kind(at) == "a":
            return 1, at + 1
        return self.tens(at)

    def hundreds(self, at: int) -> _Parsed:
        kind = self.kind(at)
        if kind == "hundreds":
            return self.value(at), at + 1
        times = self.multiplier(at)
        if times is not None:
            count, after = times
            if self.kind(after) == "hundred_word":
                return count * 100, after + 1
            if self.kind(after) == "hundreds" and self.value(after) == 100 and 3 <= count <= 9:
                return count * 100, after + 1  # "ثلاث مئة"
        return None

    def thousands(self, at: int) -> _Parsed:
        kind = self.kind(at)
        if kind == "thousands_value":
            return self.value(at), at + 1
        times = self.multiplier(at)
        if times is not None:
            count, after = times
            if self.kind(after) in ("thousand_word", "thousand", "thousands"):
                return count * 1000, after + 1
        if kind == "thousand":
            return 1000, at + 1
        return None

    def dozen(self, at: int) -> _Parsed:
        if self.kind(at) == "half" and self.kind(at + 1) == "a" and self.kind(at + 2) == "dozen":
            return 6, at + 3
        times = self.multiplier(at)
        if times is not None and self.kind(times[1]) == "dozen":
            return times[0] * 12, times[1] + 1
        if self.kind(at) == "dozen":
            return 12, at + 1
        return None

    def number(self, at: int) -> _Parsed:
        """One number: a dozen form, or thousands, hundreds and tens in that order, each optional
        and joined by an optional "and" (و)."""
        dozen = self.dozen(at)
        if dozen is not None:
            return dozen
        total, index, found = 0, at, False
        for part in (self.thousands, self.hundreds, self.tens):
            starts = [index + 1, index] if found and self.kind(index) == "and" else [index]
            for start in starts:
                got = part(start)
                if got is not None:
                    total, index, found = total + got[0], got[1], True
                    break
        if not found:
            return None
        # A scale word left after the number multiplies all of it: "five hundred thousand" is
        # 500,000 (out of range), never 500 followed by a stray word.
        while self.kind(index) in _SCALES:
            total, index = total * _SCALES[self.kind(index)], index + 1
        return total, index

    def phrase(self, at: int) -> _Parsed:
        """A number, or a range of two ("two or three"), read as its highest number."""
        first = self.number(at)
        if first is None:
            return None
        if self.kind(first[1]) == "or":
            second = self.number(first[1] + 1)
            if second is not None:
                return max(first[0], second[0]), second[1]
        return first


def _phrases(text: str) -> list[tuple[int, int, int]]:
    """Every number in words in the text, as (value, start, end), whatever its size."""
    found: list[tuple[int, int, int]] = []
    for chain in _chains(text):
        parser = _Parser(chain)
        index = 0
        while index < len(chain):
            got = parser.phrase(index)
            if got is None:
                index += 1
                continue
            value, after = got
            if after - index > 1 or chain[index].alone:
                found.append((value, chain[index].start, chain[after - 1].end))
            index = after
    return found


def words_in(text: str) -> list[Token]:
    """Every whole number from 0 to 9,999 written in words in the text, as number tokens with
    `in_words` True, in the order they appear. A larger number in words is left out."""
    return [
        Token("number", (start, end), text[start:end], readings=((Decimal(value),),), in_words=True)
        for value, start, end in _phrases(text)
        if value <= MAX_WORDS_VALUE
    ]


def read_words(text: str) -> NumberRead:
    """A text that is one number in words, or a range in words, and nothing else but spaces and
    punctuation: "fifteen", "two or three" (3), "لعشرين".

    Reasons: `empty`, `not_a_number` (no number in words, more than one, or other words beside
    it), `out_of_range` (above 9,999).
    """
    if not text.strip():
        return NumberRead(None, "empty")
    phrases = _phrases(text)
    if len(phrases) != 1:
        return NumberRead(None, "not_a_number")
    value, start, end = phrases[0]
    rest = text[:start] + text[end:]
    if any(char.isalnum() for char in rest):
        return NumberRead(None, "not_a_number")
    if value > MAX_WORDS_VALUE:
        return NumberRead(None, "out_of_range")
    return NumberRead(Decimal(value))

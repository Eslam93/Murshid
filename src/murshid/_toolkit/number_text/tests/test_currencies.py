"""The ISO 4217 codes a currency word can mean, and whether two currencies agree.

The totality test reads W09's own currency pattern: it spells every word, symbol and abbreviation
the pattern reads, and each must have a set of codes. A word added to the pattern without a set
fails it.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from murshid._toolkit.number_text.core import CURRENCY_SHAPE, currencies_agree, currency_codes

RIYALS = {"SAR", "QAR", "OMR", "YER"}
DINARS = {"KWD", "BHD", "JOD", "IQD", "LYD", "TND", "DZD"}


@pytest.mark.parametrize(
    ("word", "codes"),
    [
        ("SAR", {"SAR"}),
        ("ر.س", {"SAR"}),
        ("riyal", RIYALS),
        ("Riyals", RIYALS),
        ("ريال", RIYALS),
        ("ريالًا", RIYALS),
        ("ريالات", RIYALS),
        ("\N{RIAL SIGN}", RIYALS),
        ("ر.ق", {"QAR"}),
        ("ر.ع", {"OMR"}),
        ("dinar", DINARS),
        ("دينار", DINARS),
        ("KWD", {"KWD"}),
        ("د.ك", {"KWD"}),
        ("د.إ", {"AED"}),
        ("dirham", {"AED", "MAD"}),
        ("درهم", {"AED", "MAD"}),
        ("$", {"USD"}),
        ("dollar", {"USD"}),
        ("USD", {"USD"}),
        ("usd", {"USD"}),
        ("€", {"EUR"}),
        ("يورو", {"EUR"}),
        ("£", {"GBP", "EGP", "LBP", "SYP", "SDG"}),
        ("جنيه", {"EGP", "SDG", "GBP"}),
        ("ج.م", {"EGP"}),
        ("ليرة", {"LBP", "SYP", "TRY"}),
        ("¥", {"JPY", "CNY"}),
        (" SAR ", {"SAR"}),
        ("", set()),
        ("kr", set()),
        ("CAD", {"CAD"}),
        ("zar", {"ZAR"}),
        ("XYZ", set()),
        ("laptops", set()),
    ],
)
def test_a_currency_word_means_a_set_of_iso_codes(word: str, codes: set[str]) -> None:
    assert currency_codes(word) == frozenset(codes)


@pytest.mark.parametrize(
    ("one", "other", "agree"),
    [
        ("riyal", "SAR", True),
        ("ريال", "QAR", True),
        ("ر.س", "riyals", True),
        ("dinar", "KWD", True),
        ("دينار", "BHD", True),
        ("SAR", "SAR", True),
        ("$", "USD", True),
        ("USD", "SAR", False),
        ("$", "SAR", False),
        ("riyal", "KWD", False),
        ("ر.ق", "ر.س", False),
        ("dirham", "dinar", False),
        ("€", "£", False),
        # An unknown side agrees with any currency
        ("", "SAR", True),
        ("kr", "USD", True),
        ("", "", True),
    ],
)
def test_two_currencies_agree_when_their_sets_meet_or_one_is_unknown(
    one: str, other: str, agree: bool
) -> None:
    assert currencies_agree(one, other) is agree
    assert currencies_agree(other, one) is agree


# ---- totality: every word the currency pattern reads has a set ---------------------------------

_parser: Any = importlib.import_module("re._parser")
_codes: Any = importlib.import_module("re._constants")


def spellings(parsed: Any) -> set[str]:
    """Every string a parsed pattern reads, with each repeat taken zero times and once. The
    currency pattern is a set of alternatives of letters, character classes and optional endings;
    any other construct fails here, so the test never skips part of the pattern."""
    found = {""}
    for op, argument in parsed:
        if op is _codes.LITERAL:
            options = {chr(argument)}
        elif op is _codes.IN:
            options = set[str]()
            for item, value in argument:
                if item is _codes.LITERAL:
                    options.add(chr(value))
                elif item is _codes.RANGE:
                    options |= {chr(code) for code in range(value[0], value[1] + 1)}
                else:
                    raise AssertionError(f"cannot spell the class item {item}")
        elif op is _codes.BRANCH:
            options = set[str]().union(*(spellings(branch) for branch in argument[1]))
        elif op is _codes.SUBPATTERN:
            options = spellings(argument[3])
        elif op in (_codes.MAX_REPEAT, _codes.MIN_REPEAT):
            least, _, inner = argument
            if least > 1:
                raise AssertionError("cannot spell a repeat of more than one")
            options = spellings(inner) | ({""} if least == 0 else set[str]())
        else:
            raise AssertionError(f"cannot spell {op}")
        found = {before + option for before in found for option in options}
    return found


def test_every_word_the_currency_pattern_reads_has_a_set_of_codes() -> None:
    words = spellings(_parser.parse(CURRENCY_SHAPE.pattern, CURRENCY_SHAPE.flags))
    # The spelling reads the pattern itself: a control that must be among them, and its size
    assert {"SAR", "ر.س", "riyal", "riyals", "ريال", "ريالًا", "ريالات", "$", "دينار"} <= words
    assert len(words) > 100
    read = 0
    for word in words:
        for form in {word, word.upper(), word.title()}:
            if CURRENCY_SHAPE.fullmatch(form):
                read += 1
                assert currency_codes(form), form
    assert read >= len(words)

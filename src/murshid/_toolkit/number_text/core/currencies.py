"""The ISO 4217 codes a currency word can mean, and whether two currencies agree.

A text writes "riyal", "ريال", "$" or "SAR"; a record holds an ISO code. `currency_codes` gives the
set of codes a word, a symbol or an abbreviation can mean: "SAR" and "ر.س" mean SAR only, "riyal"
and "ريال" mean any of four riyals, an ISO code means itself, and an unknown word means the empty
set. `currencies_agree` is True when either side is unknown or the two sets share a code, so
"riyal" agrees with "SAR" and "dinar" with "KWD", while "USD" and "SAR" do not.

Every word the default currency pattern (`CURRENCY_SHAPE`) reads has a set here, with its Arabic
endings (ريالًا, ريالات) and its English plural (riyals). A lift with other currencies adds their
words to the table below.
"""

from __future__ import annotations

from .reading import fold_arabic
from .scanning import ISO_4217

__all__ = ["currencies_agree", "currency_codes"]

_RIYALS = frozenset({"SAR", "QAR", "OMR", "YER"})
_DINARS = frozenset({"KWD", "BHD", "JOD", "IQD", "LYD", "TND", "DZD"})
_DIRHAMS = frozenset({"AED", "MAD"})
_POUNDS = frozenset({"GBP", "EGP", "LBP", "SYP", "SDG"})
_LIRAS = frozenset({"LBP", "SYP", "TRY"})

# Each word, symbol and abbreviation, and the codes it can mean. A symbol shared by several
# currencies means all of them: the pound sign is written for the pound sterling and for the
# Egyptian, Lebanese, Syrian and Sudanese pounds, and the yen sign for the yen and the yuan.
_WORDS: dict[str, frozenset[str]] = {
    "$": frozenset({"USD"}),
    "€": frozenset({"EUR"}),
    "£": _POUNDS,
    "¥": frozenset({"JPY", "CNY"}),
    "\N{RIAL SIGN}": _RIYALS,
    "ر.س": frozenset({"SAR"}),
    "ر.ق": frozenset({"QAR"}),
    "ر.ع": frozenset({"OMR"}),
    "د.إ": frozenset({"AED"}),
    "د.ك": frozenset({"KWD"}),
    "د.ب": frozenset({"BHD"}),
    "ج.م": frozenset({"EGP"}),
    "riyal": _RIYALS,
    "ريال": _RIYALS,
    "dirham": _DIRHAMS,
    "درهم": _DIRHAMS,
    "dinar": _DINARS,
    "دينار": _DINARS,
    "pound": _POUNDS,
    "جنيه": frozenset({"EGP", "SDG", "GBP"}),
    "dollar": frozenset({"USD"}),
    "دولار": frozenset({"USD"}),
    "euro": frozenset({"EUR"}),
    "يورو": frozenset({"EUR"}),
    "ليرة": _LIRAS,
}


def _key(word: str) -> str:
    """A word as the table compares it: the Arabic letter forms and marks folded, in lower case."""
    return fold_arabic(word.strip()).lower()


_TABLE: dict[str, frozenset[str]] = {
    **{_key(code): frozenset({code}) for code in ISO_4217},
    **{_key(word): codes for word, codes in _WORDS.items()},
}


def currency_codes(word: str) -> frozenset[str]:
    """The ISO 4217 codes a currency word, symbol or abbreviation can mean; empty when unknown.

    Case does not count, and neither do the Arabic marks. An Arabic word may carry its tanween
    ending or its plural ending (ريالًا, ريالات), and an English word its plural (riyals).
    """
    key = _key(word)
    for ending in ("", "ات", "ا", "s"):
        if key.endswith(ending) and (stem := key[: len(key) - len(ending)]) in _TABLE:
            return _TABLE[stem]
    return frozenset()


def currencies_agree(one: str, other: str) -> bool:
    """Whether two currency words can name the same currency: True when either is unknown, so a
    figure with no known currency is never refused for it, or when their code sets meet."""
    first, second = currency_codes(one), currency_codes(other)
    return not first or not second or bool(first & second)

"""Normalisation, BM25 ranking and fusion through the public interface, and the speed of
normalisation against the implementation it replaced."""

from __future__ import annotations

import random
import re
import timeit
import unicodedata
from collections.abc import Callable, Sequence

from murshid._toolkit.lexical_retrieval.core import BM25Index, Document, Hit, fuse, normalize, tokenize

LINES = [
    Document("toner", "Toner cartridge for laser printer"),
    Document("paper", "A4 copy paper, 80 gsm"),
    Document("chairs", "Office chairs with lumbar support"),
    Document("ar-toner", "حبر طابعة ليزر أسود"),
    Document("ar-paper", "ورق تصوير مقاس A4"),
    Document("ar-chairs", "كراسي مكتب بمسند للظهر"),
    Document("cleaning", "Cleaning services for the office"),
]


def test_arabic_letter_variants_and_diacritics_fold_together() -> None:
    assert normalize("إدارة") == normalize("ادارة")
    assert normalize("مُدَرَّسَة") == normalize("مدرسة")
    assert normalize("مستشفى") == normalize("مستشفي")
    assert normalize("كـــتاب") == "كتاب"
    assert normalize("٢٠٢٦") == "2026"


def test_the_article_and_english_plurals_are_taken_off() -> None:
    assert tokenize("الطابعة") == tokenize("طابعة")
    assert tokenize("والطابعات") == ["طابعات"]
    assert tokenize("Printers and boxes") == ["printer", "box"]
    assert tokenize("glass class") == ["glass", "class"]
    assert tokenize("the of a") == []


def test_the_best_match_comes_first_with_the_words_it_matched() -> None:
    index = BM25Index(LINES)
    hits = index.search("laser printer toner", limit=3)
    assert hits[0].key == "toner"
    assert set(hits[0].matched) == {"laser", "printer", "toner"}
    assert len(index) == len(LINES)


def test_arabic_queries_match_arabic_lines_written_differently() -> None:
    index = BM25Index(LINES)
    assert index.search("الحبر للطابعة")[0].key == "ar-toner"
    assert index.search("كرسي مكتب")[0].key == "ar-chairs"


def test_a_query_with_no_known_word_finds_nothing() -> None:
    index = BM25Index(LINES)
    assert index.search("helicopter") == []
    assert index.search("") == []
    assert BM25Index([]).search("toner") == []


def test_rarer_words_weigh_more_than_common_ones() -> None:
    index = BM25Index(
        [
            Document(1, "office supplies"),
            Document(2, "office chairs"),
            Document(3, "office desks"),
            Document(4, "ergonomic chairs"),
        ]
    )
    # "ergonomic" appears once, "office" three times: the rare word decides.
    assert index.search("office ergonomic")[0].key == 4


def test_the_limit_is_kept_and_ties_keep_the_given_order() -> None:
    index = BM25Index([Document(n, "paper") for n in range(5)])
    assert [hit.key for hit in index.search("paper", limit=3)] == [0, 1, 2]


def test_fusion_raises_what_both_rankings_found() -> None:
    lexical = [Hit("a", 5.0, ("toner",)), Hit("b", 4.0, ("printer",)), Hit("c", 1.0)]
    dense = [Hit("b", 0.9), Hit("d", 0.8), Hit("a", 0.1)]
    fused = fuse([lexical, dense], limit=4)
    assert [hit.key for hit in fused][:2] == ["b", "a"]
    assert fused[0].matched == ("printer",)
    assert {hit.key for hit in fused} == {"a", "b", "c", "d"}


# ---- Folding through W03 ----------------------------------------------------------------------

ZWNJ = "\u200c"  # the zero-width non-joiner
PERSIAN_KAF = "\u06a9"
PERSIAN_YA = "\u06cc"


def test_hamza_on_waw_and_ya_folds_to_the_bare_letter() -> None:
    assert normalize("مسؤول") == normalize("مسوول") == "مسوول"
    assert normalize("رئيس") == normalize("رييس") == "رييس"
    # The same letters written as the carrier and then the hamza mark.
    assert normalize("مسو\u0654ول") == "مسوول"
    assert normalize("ري\u0654يس") == "رييس"
    index = BM25Index([Document("buyer", "مسؤول المشتريات"), *LINES])
    assert index.search("مسوول")[0].key == "buyer"


def test_the_persian_forms_of_ya_and_kaf_fold_to_the_arabic_letters() -> None:
    assert normalize(f"{PERSIAN_KAF}رس{PERSIAN_YA}") == "كرسي"
    assert tokenize(f"م{PERSIAN_KAF}تب") == ["مكتب"]
    assert BM25Index(LINES).search(f"م{PERSIAN_KAF}تب")[0].key == "ar-chairs"


def test_a_word_with_a_zero_width_non_joiner_stays_one_word() -> None:
    assert tokenize(f"لي{ZWNJ}زر") == ["ليزر"]
    assert tokenize(f"م{PERSIAN_YA}{ZWNJ}خواهم") == ["ميخواهم"]
    assert BM25Index(LINES).search(f"لي{ZWNJ}زر")[0].key == "ar-toner"


def test_other_zero_width_characters_and_direction_marks_leave_a_word_whole() -> None:
    for mark in "\u200b\u200d\u2060\ufeff\u200e\u200f\u061c\u2067":
        assert tokenize(f"حب{mark}ر") == ["حبر"], hex(ord(mark))


# ---- The implementation of 2026-10-15, kept as a reference ---------------------------------------

_DIACRITICS_2026_10_15 = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
_ALEF_FORMS_2026_10_15 = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
_DIGITS_2026_10_15 = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize_2026_10_15(text: str) -> str:
    """`normalize` as it was on 2026-10-15, with its own tables instead of W03's rules."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _DIACRITICS_2026_10_15.sub("", text)
    return text.translate(_ALEF_FORMS_2026_10_15).translate(_DIGITS_2026_10_15)


# Words that both implementations fold the same way: case, compatibility forms, diacritics, the
# tatweel, alef forms, alef maqsura, ta marbuta, both forms of digits, and a Quranic sign.
SAME_BOTH_WAYS = [
    "Toner",
    "CARTRIDGE",
    "for",
    "laser",
    "Printers",
    "A4-80",
    "paper,",
    "80gsm",
    "(SAR)",
    "x3.",
    "\ufb01ling",  # a ligature
    "\uff35\uff33\uff22",  # full-width letters
    "Stra\u00dfe",  # case folds to "strasse"
    "cafe\u0301",  # an accent written as a combining mark
    "حبر",
    "طابعة",
    "ليزر",
    "أسود",
    "إدارة",
    "آلة",
    "ٱلعقد",
    "مستشفى",
    "مُدَرَّسَة",
    "كـــتاب",
    "٢٠٢٦",
    "۱۴",
    "ورق",
    "تصوير",
    "كراسي",
    "مكتب",
    "قطعة",
    "\ufefbبد",  # the presentation form of lam-alef
    "يوماً",
    "قرآن\u06dd",  # the end-of-ayah sign
]
# Words that only the current implementation folds.
NEWLY_FOLDED = [
    "مسؤول",
    "رئيس",
    f"{PERSIAN_KAF}رس{PERSIAN_YA}",
    f"لي{ZWNJ}زر",
    "\u201cpremium\u201d",
    "A4\u2013paper",
    "نعم،",
    "\u200fمكتب",
]


def short_lines(rng: random.Random, count: int, words: Sequence[str]) -> list[str]:
    return [" ".join(rng.choice(words) for _ in range(rng.randint(3, 8))) for _ in range(count)]


def test_text_without_the_newly_folded_forms_normalises_as_before() -> None:
    rng = random.Random(20261015)  # noqa: S311 - made-up text, not a secret
    for line in short_lines(rng, 2_000, SAME_BOTH_WAYS):
        assert normalize(line) == normalize_2026_10_15(line), line


def test_normalize_takes_at_most_twice_as_long_as_the_implementation_it_replaced() -> None:
    rng = random.Random(10_000)  # noqa: S311 - made-up text, not a secret
    lines = short_lines(rng, 10_000, SAME_BOTH_WAYS + NEWLY_FOLDED)

    def seconds(function: Callable[[str], str]) -> float:
        # timeit turns the garbage collector off while it measures.
        return timeit.Timer(lambda: [function(line) for line in lines]).timeit(number=1)

    before: list[float] = []
    now: list[float] = []
    for _ in range(3):  # alternated, so both see the same load on the machine
        before.append(seconds(normalize_2026_10_15))
        now.append(seconds(normalize))
    assert min(now) <= 2 * min(before), (
        f"best of three: {min(now):.3f} s against {min(before):.3f} s"
    )

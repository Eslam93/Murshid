"""Folding through the public interface: each rule set, composing sets, the map back, and the
folded text alone."""

from __future__ import annotations

import re
import unicodedata
from typing import cast

import pytest

from murshid._toolkit.quote_matching.core import (
    ARABIC,
    DEFAULT_RULES,
    LATIN,
    MARKUP,
    TRANSCRIPT,
    CharRule,
    PatternRule,
    Rule,
    fold,
    fold_text,
)


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("The SUPPLIER", "the supplier"),
        ("\u201cServices\u201d means", '"services" means'),
        ("ten days\u2019 notice", "ten days' notice"),
        ("June \u2014 the printer", "june - the printer"),
        ("five \u2013 six", "five - six"),
        ("\ufb01eld kit", "field kit"),  # a ligature
        ("\uff13\uff10 days", "30 days"),  # full-width digits
        ("thirty\u00a0days", "thirty days"),  # a no-break space
        ("shall pay the\n\n  premium", "shall pay the premium"),
        ("re\u200bvised", "revised"),  # a zero-width space
    ],
)
def test_latin_rules_fold_case_quotes_dashes_compatibility_forms_and_spaces(
    text: str, folded: str
) -> None:
    assert fold(text, LATIN).text == folded


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("الإطلاق", "الاطلاق"),  # hamza below alef
        ("أخبر", "اخبر"),  # hamza above alef
        ("آخر", "اخر"),  # alef madda
        ("ٱلعقد", "العقد"),  # alef wasla
        ("مسؤول", "مسوول"),  # hamza on waw
        ("رئيس", "رييس"),  # hamza on ya
        ("على", "علي"),  # alef maqsura
        ("المعدلة", "المعدله"),  # ta marbuta
        ("الـمـدة", "المده"),  # tatweel
        ("يَجِبُ عَلى المُوَرِّد", "يجب علي المورد"),  # diacritics
        ("٣٠ يوماً", "30 يوما"),  # Arabic-Indic digits and tanween
        ("۱۴", "14"),  # the Persian forms of the digits
        ("\ufef7ي طرف", "لاي طرف"),  # the presentation form of lam-alef with hamza
        ("\ufefbبد", "لابد"),  # the presentation form of lam-alef
        ("لا\u0654سباب", "لاسباب"),  # lam-alef with hamza written as a mark after alef
        ("رقم\u200f العقد\u200e", "رقم العقد"),  # direction marks
        ("موافق، وسيرسل؟", "موافق, وسيرسل?"),  # Arabic punctuation
    ],
)
def test_arabic_rules_fold_letter_forms_marks_digits_and_presentation_forms(
    text: str, folded: str
) -> None:
    assert fold(text, ARABIC).text == folded


@pytest.mark.parametrize("letter", ["أ", "إ", "آ", "ؤ", "ئ"])
def test_a_letter_written_whole_or_as_carrier_and_mark_folds_alike(letter: str) -> None:
    decomposed = unicodedata.normalize("NFD", letter)
    assert decomposed != letter
    assert fold(letter, ARABIC).text == fold(decomposed, ARABIC).text


def test_transcript_rules_skip_tags_and_spaces_before_punctuation() -> None:
    assert fold("so {vocalsound} yes ?", TRANSCRIPT).text == "so  yes?"
    assert fold("I think {disfmarker} we keep it .", TRANSCRIPT + LATIN).text == (
        "i think we keep it."
    )
    assert fold("موافق ، شكرا", TRANSCRIPT).text == "موافق، شكرا"


def test_the_order_of_the_sets_does_not_change_the_result() -> None:
    text = "Omar:  \u00ab\ufef7ي\u00bb {disfmarker} الإطلاق ٣٠ \u2014 \u201cYes\u201d .\u200f"
    orders = [
        LATIN + ARABIC + TRANSCRIPT,
        TRANSCRIPT + ARABIC + LATIN,
        ARABIC + TRANSCRIPT + LATIN,
    ]
    assert {fold(text, rules).text for rules in orders} == {'omar: "لاي" الاطلاق 30 - "yes".'}


def test_every_folded_character_points_back_into_the_original() -> None:
    text = "\ufb01eld \u201cKIT\u201d  ٣٠ يَوماً {gap} ."
    folded = fold(text, DEFAULT_RULES)
    assert len(folded.starts) == len(folded.ends) == len(folded.text)
    for index in range(len(folded.text)):
        assert 0 <= folded.starts[index] < folded.ends[index] <= len(text)
        if index:
            assert folded.starts[index - 1] <= folded.starts[index]
            assert folded.ends[index - 1] <= folded.ends[index]
    # Both letters of the folded ligature point at the one original character, so half of it
    # maps back to all of it.
    assert folded.text.startswith("field")
    assert folded.to_original(0, 2) == (0, 1)
    assert folded.to_original(1, 2) == (0, 1)
    kit = folded.text.index("kit")
    start, end = folded.to_original(kit, kit + 3)
    assert text[start:end] == "KIT"
    end_of_text = len(folded.text)
    assert folded.to_original(end_of_text, end_of_text) == (len(text), len(text))
    with pytest.raises(ValueError, match="outside the folded text"):
        folded.to_original(3, 2)


def test_a_caller_adds_its_own_rules_and_drops_one_by_name() -> None:
    # Words split at a PDF line end. The rule is listed last but runs at the markup stage, before
    # white space is collapsed.
    hyphens = PatternRule("pdf_hyphens", re.compile(r"(?<=\w)-\n(?=\w)"), "", stage=MARKUP)
    text = "the obliga-\ntions of the Supplier"
    assert fold(text, LATIN).text == "the obliga- tions of the supplier"
    assert fold(text, (*LATIN, hyphens)).text == "the obligations of the supplier"

    def without_accents(char: str) -> str:
        decomposed = unicodedata.normalize("NFD", char)
        return "".join(part for part in decomposed if not unicodedata.combining(part))

    accents = CharRule("latin_accents", without_accents)
    assert fold("Café Noël", LATIN).text == "café noël"
    assert fold("Café Noël", (*LATIN, accents)).text == "cafe noel"

    keep_digits = tuple(rule for rule in ARABIC if rule.name != "arabic_digits")
    assert fold("٣٠ يوماً", keep_digits).text == "٣٠ يوما"


# ---- The folded text alone ------------------------------------------------------------------

FOLD_TEXT_SAMPLES = [
    "",
    "The SUPPLIER shall pay the\n\n  premium",
    "\ufb01eld \u201cKIT\u201d  ٣٠ يَوماً {gap} .",
    "Omar:  \u00ab\ufef7ي\u00bb {disfmarker} الإطلاق ٣٠ \u2014 \u201cYes\u201d .\u200f",
    "مسؤول، رئيس؟ \u06a9\u06cc ۱۴ re\u200bvised",
]


@pytest.mark.parametrize(
    "rules",
    [LATIN, ARABIC, TRANSCRIPT, DEFAULT_RULES, TRANSCRIPT + ARABIC + LATIN, ()],
    ids=["latin", "arabic", "transcript", "default", "reversed", "none"],
)
def test_fold_text_gives_the_text_that_fold_gives(rules: tuple[Rule, ...]) -> None:
    for text in FOLD_TEXT_SAMPLES:
        assert fold_text(text, rules) == fold(text, rules).text, text


def test_fold_text_skips_empty_matches_and_inserts_a_replacement_as_written() -> None:
    # "x*" also matches the empty string between characters; fold leaves those places alone. The
    # replacement holds what re.sub would read as a group reference; fold takes it literally.
    rule = PatternRule("runs_of_x", re.compile("x*"), r"[\g<0>]", stage=MARKUP)
    for text in ("", "abc", "axxbx", "xx"):
        assert fold_text(text, (rule,)) == fold(text, (rule,)).text, text
    assert fold_text("axxb", (rule,)) == r"a[\g<0>]b"


def test_fold_text_takes_any_iterable_of_rules_and_new_rules_on_every_call() -> None:
    text = "The  SUPPLIER الإطلاق ٣٠"
    expected = fold(text, LATIN + ARABIC).text
    assert fold_text(text, list(LATIN + ARABIC)) == expected
    assert fold_text(text, (rule for rule in LATIN + ARABIC)) == expected
    # A rule set built afresh for every call is folded with its own rules, never another set's.
    for number in range(100):

        def numbered_rule(char: str, n: int = number) -> str:
            return str(n) if char == "#" else char

        numbered = CharRule("number", numbered_rule)
        assert fold_text("Item #", (*LATIN, numbered)) == f"item {number}"


def test_fold_text_rewrites_each_character_once_across_calls() -> None:
    calls: list[str] = []

    def upper(char: str) -> str:
        calls.append(char)
        return char.upper()

    rules = (CharRule("upper", upper),)
    assert fold_text("abba", rules) == "ABBA"
    assert fold_text("baba", rules) == "BABA"
    assert sorted(calls) == ["a", "b"]


def test_something_that_is_not_a_rule_is_refused() -> None:
    not_a_rule = cast(Rule, "latin_case")
    with pytest.raises(TypeError, match="not a folding rule"):
        fold("text", (not_a_rule,))
    with pytest.raises(TypeError, match="not a folding rule"):
        fold_text("text", (not_a_rule,))

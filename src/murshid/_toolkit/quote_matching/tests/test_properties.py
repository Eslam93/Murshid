"""Properties over many generated texts and quotes: every span maps back inside the original,
and the folded text alone is the text of the full fold.

The texts mix English and Arabic words, digits in both forms, emoji, transcript tags, direction
marks and assorted white space. The generator is seeded, so a failure repeats.
"""

from __future__ import annotations

import random
import unicodedata

from murshid._toolkit.quote_matching.core import (
    ARABIC,
    DEFAULT_RULES,
    LATIN,
    TRANSCRIPT,
    Alignment,
    FuzzyPolicy,
    Rule,
    align,
    fold,
    fold_text,
)

WORDS = [
    "Supplier",
    "shall",
    "deliver",
    "launch",
    "June",
    "\ufb01eld",
    "kit",
    "notice",
    "30",
    "\u201cpremium\u201d",
    "الإطلاق",
    "المورد",
    "يوماً",
    "على",
    "الشركة",
    "آخر",
    "مسؤول",
    "\ufef7سباب",
    "٣٠",
    "\U0001f4e6",
    "\U0001f44d\U0001f3fd",
]
SEPARATORS = [" ", " ", " ", "  ", "\n", "\n\n", "\t", " {disfmarker} ", "\u200f ", " \u200e"]
ARABIC_LETTERS = {chr(code) for code in range(0x0621, 0x064B)}


def variant(word: str, rng: random.Random) -> str:
    """The same word as another writer might write it; it folds to the same text."""
    choice = rng.randrange(7)
    if choice == 0:
        return word.upper()
    if choice == 1:  # hamza dropped
        return word.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    if choice == 2:  # a diacritic added after some letters
        return "".join(
            char + ("\u064e" if char in ARABIC_LETTERS and rng.random() < 0.4 else "")
            for char in word
        )
    if choice == 3:  # tanween removed, ta marbuta and alef maqsura written as ha and ya
        return word.replace("\u064b", "").replace("ة", "ه").replace("ى", "ي")
    if choice == 4:  # digits in the other form
        return word.translate(str.maketrans("0123456789٠١٢٣٤٥٦٧٨٩", "٠١٢٣٤٥٦٧٨٩0123456789"))
    if choice == 5:  # presentation forms written out, curly quotes straightened
        return word.replace("\ufef7", "لأ").replace("\u201c", '"').replace("\u201d", '"')
    return word


def generate(rng: random.Random) -> tuple[str, list[tuple[int, int]]]:
    words = [rng.choice(WORDS) for _ in range(rng.randint(1, 30))]
    pieces: list[str] = []
    spans: list[tuple[int, int]] = []
    position = 0
    for index, word in enumerate(words):
        if index:
            separator = rng.choice(SEPARATORS)
            pieces.append(separator)
            position += len(separator)
        pieces.append(word)
        spans.append((position, position + len(word)))
        position += len(word)
    return "".join(pieces), spans


def is_mark(char: str) -> bool:
    return unicodedata.category(char) in ("Mn", "Me")


def check(text: str, quote: str, result: Alignment) -> None:
    if result.kind == "not_found":
        assert result.span is None
        assert result.score == 0.0
        return
    assert result.span is not None
    start, end = result.span
    assert 0 <= start <= end <= len(text)
    assert 0.0 < result.score <= 1.0
    if result.kind == "exact":
        # The quote character for character, then any marks of its last letter: a span never
        # cuts a letter from its diacritics.
        found, wanted = text[start:end], quote.strip()
        assert found.startswith(wanted)
        assert all(is_mark(char) for char in found[len(wanted) :])
    elif result.kind == "normalized":
        assert (
            fold(quote.strip(), DEFAULT_RULES).text.strip()
            in fold(text[start:end], DEFAULT_RULES).text
        )


def test_a_run_of_words_written_another_way_is_found_and_maps_back() -> None:
    rng = random.Random(20261012)  # noqa: S311 - made-up text, not a secret
    for _ in range(400):
        text, spans = generate(rng)
        first = rng.randrange(len(spans))
        last = rng.randrange(first, min(len(spans), first + 6))
        words = [text[start:end] for start, end in spans[first : last + 1]]
        quote = " ".join(variant(word, rng) for word in words)
        result = align(text, quote)
        assert result.kind in ("exact", "normalized"), (text, quote, result)
        check(text, quote, result)


def test_any_slice_of_the_text_is_found_and_maps_back() -> None:
    rng = random.Random(7)  # noqa: S311 - made-up text, not a secret
    for _ in range(400):
        text, _ = generate(rng)
        start = rng.randrange(len(text))
        end = rng.randrange(start, len(text)) + 1
        quote = text[start:end]
        result = align(text, quote, after=rng.randrange(len(text) + 1))
        check(text, quote, result)
        if quote.strip():
            assert result.kind in ("exact", "normalized"), (text, quote, result)


def test_no_span_ends_between_a_letter_and_its_diacritics() -> None:
    # Quotes copied from the text up to a letter whose diacritic follows it: every tier must take
    # the diacritic too. The exact tier used to stop before it.
    rng = random.Random(20261017)  # noqa: S311 - made-up text, not a secret
    checked = 0
    for _ in range(400):
        text, _ = generate(rng)
        text = "".join(
            char + ("\u064e" if char in ARABIC_LETTERS and rng.random() < 0.4 else "")
            for char in text
        )
        marks = [index for index, char in enumerate(text) if is_mark(char) and index > 0]
        if not marks:
            continue
        end = rng.choice(marks)
        start = rng.randrange(end)
        quote = text[start:end]
        if not quote.strip():
            continue
        fuzzy = rng.choice([None, FuzzyPolicy()])
        result = align(text, quote, fuzzy=fuzzy)
        check(text, quote, result)
        assert result.span is not None, (text, quote)
        found_end = result.span[1]
        assert found_end == len(text) or not is_mark(text[found_end]), (text, quote, result)
        checked += 1
    assert checked > 300


def test_random_quotes_windows_and_policies_always_give_spans_inside_the_text() -> None:
    rng = random.Random(11)  # noqa: S311 - made-up text, not a secret
    for _ in range(400):
        text, spans = generate(rng)
        quote, _ = generate(rng)
        windows = rng.sample(spans, k=rng.randint(0, min(3, len(spans))))
        fuzzy = rng.choice([None, FuzzyPolicy(), FuzzyPolicy(coverage=0.5, density=0.2)])
        result = align(
            text, quote, windows=windows, fuzzy=fuzzy, after=rng.randrange(len(text) + 1)
        )
        check(text, quote, result)
        if not windows:
            assert result.kind != "misattributed"
        elif result.kind in ("exact", "normalized", "fuzzy"):
            assert result.span is not None
            assert min(w[0] for w in windows) <= result.span[0]
            assert result.span[1] <= max(w[1] for w in windows)
        if fuzzy is None:
            assert result.kind != "fuzzy"


def test_every_folded_character_maps_back_inside_the_original() -> None:
    rng = random.Random(3)  # noqa: S311 - made-up text, not a secret
    for _ in range(300):
        text, _ = generate(rng)
        text = variant(text, rng)
        folded = fold(text, DEFAULT_RULES)
        assert len(folded.starts) == len(folded.ends) == len(folded.text)
        previous = (0, 0)
        for index in range(len(folded.text)):
            start, end = folded.starts[index], folded.ends[index]
            assert 0 <= start < end <= len(text)
            assert previous[0] <= start and previous[1] <= end
            previous = (start, end)
        for _ in range(5):
            left = rng.randrange(len(folded.text) + 1)
            right = rng.randrange(left, len(folded.text) + 1)
            start, end = folded.to_original(left, right)
            assert 0 <= start <= end <= len(text)


# Characters that some rule rewrites: zero-width characters and direction marks, Arabic marks,
# letter forms, punctuation and digits, presentation and compatibility forms, quotes and dashes,
# white space, letters whose case folds to several, a combining accent, and transcript braces and
# punctuation.
RARE = [
    *"\u200b\u200c\u200d\u2060\ufeff",
    *"\u200e\u200f\u061c\u202a\u202e\u2066\u2069",
    *"\u064b\u064e\u0651\u0652\u0654\u0655\u0670\u0640\u06d6\u06dd",
    *"آأإٱؤئىة\u06a9\u06cc",
    *"،؛؟٪\u066b\u066c",
    *"٣۴",
    *"\ufef7\ufefb\ufb01\uff13\u00bd",
    *"\u2018\u2019\u201c\u201d\u00ab\u00bb\u2013\u2014\u2212",
    *"\u00a0\u2009\u3000\t\n",
    *"\u00df\u0130\u03a3\u0301",
    "  ",
    "{",
    "}",
    "{gap}",
    " .",
    " ،",
    " )",
]


def test_fold_text_is_the_text_of_fold_for_any_text_and_rule_set() -> None:
    rng = random.Random(20261016)  # noqa: S311 - made-up text, not a secret
    fixed: list[tuple[Rule, ...]] = [
        LATIN,
        ARABIC,
        TRANSCRIPT,
        LATIN + ARABIC,
        TRANSCRIPT + ARABIC + LATIN,
        DEFAULT_RULES,
    ]
    for _ in range(600):
        text, _ = generate(rng)
        pieces = list(variant(text, rng))
        for _ in range(rng.randint(0, 8)):
            pieces.insert(rng.randrange(len(pieces) + 1), rng.choice(RARE))
        text = "".join(pieces)
        if rng.random() < 0.5:
            rules = list(rng.choice(fixed))
        else:  # any subset of the rules, in any order
            rules = [rule for rule in DEFAULT_RULES if rng.random() < 0.8]
            rng.shuffle(rules)
        assert fold_text(text, rules) == fold(text, rules).text, (text, [r.name for r in rules])

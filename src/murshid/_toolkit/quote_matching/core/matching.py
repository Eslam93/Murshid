"""Finding a quote in the text it came from, and saying how it was found.

A model that cites a document gives a block id and a short quote. The quote is rarely a perfect
copy: the model straightens a curly quote, drops a diacritic, writes 30 for ٣٠, or joins two lines.
`align` looks for the quote in tiers and reports the first tier that finds it:

1. `exact`: the quote, with spaces at its ends removed, appears character for character. The span
   also takes any diacritics that follow the quote's last letter, as the other tiers' spans do.
2. `normalized`: the folded quote appears in the folded text (see `folding.py`), and the match is
   mapped back to the original characters.
3. `fuzzy`, only when the caller passes a `FuzzyPolicy`: the longest run of quote words found in
   order in the text covers at least `coverage` of the quote's words, and those words fill at least
   `density` of the stretch of text they span.

The tiers run first inside the cited windows (the character ranges of the blocks the model named).
A quote found only outside them is `misattributed`, with the span where it was found. A quote found
nowhere is `not_found`. Nothing is dropped for matching badly: the kind is the verdict.

Windows that touch, overlap, or are separated only by text that folds to spaces are joined, so a
quote that runs from one block into the next (a clause across a page break) is found when the
caller passes every block from the first to the last.

A quote can appear more than once. `after` keeps repeated quotes in order: a match that starts at
or after it comes before one that starts earlier, so the second "agreed" of a transcript gets the
second place it was said. When nothing starts after it, the earlier match is still returned,
because two records may cite the same sentence.
"""

from __future__ import annotations

import math
import re
import unicodedata
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from .folding import DEFAULT_RULES, Folded, Rule, fold

__all__ = ["MATCH_KINDS", "Alignment", "FuzzyPolicy", "MatchKind", "align"]

MatchKind = Literal["exact", "normalized", "fuzzy", "misattributed", "not_found"]
MATCH_KINDS: tuple[MatchKind, ...] = ("exact", "normalized", "fuzzy", "misattributed", "not_found")


@dataclass(frozen=True)
class FuzzyPolicy:
    """When an approximate match is accepted. Starting values, for an evaluation to tune."""

    coverage: float = 0.75  # the share of the quote's words found, in order
    density: float = 1 / 3  # the share of the matched stretch's words that are quote words

    def __post_init__(self) -> None:
        if not (0 < self.coverage <= 1 and 0 < self.density <= 1):
            raise ValueError("coverage and density must be above 0 and at most 1")


@dataclass(frozen=True)
class Alignment:
    """Where a quote was found, and how.

    `span` is the start and end (end excluded) in the original text, or None when `not_found`.
    `score` is 1.0 for an exact or normalized match, coverage times density for a fuzzy one, the
    score of the tier that found it for a misattributed one, and 0.0 when not found.
    """

    kind: MatchKind
    span: tuple[int, int] | None
    score: float


NOT_FOUND = Alignment("not_found", None, 0.0)

_WORD = re.compile(r"\w+")
_EXACT = 0
_NORMALIZED = 1
_EPSILON = 1e-9

# Ordering of literal candidates: a match at or after `after` first, then one at word edges, then
# the exact tier before the normalized one, then the earlier position.
_LiteralKey = tuple[bool, bool, int, int]
# Ordering of fuzzy candidates: at or after `after` first, then coverage, density and position.
_FuzzyKey = tuple[bool, float, float, int]


def align(
    text: str,
    quote: str,
    *,
    windows: Sequence[tuple[int, int]] = (),
    after: int = 0,
    fuzzy: FuzzyPolicy | None = None,
    rules: Sequence[Rule] = DEFAULT_RULES,
) -> Alignment:
    """Find `quote` in `text`, inside `windows` first, at or after `after` first.

    `windows` are character ranges of `text` (start, end excluded), usually the cited blocks; with
    none, the whole text is the window and `misattributed` cannot happen. `fuzzy` turns on the
    approximate tier. `rules` are the folding rules of the normalized tier.
    """
    if not 0 <= after <= len(text):
        raise ValueError(f"after={after} is outside the text (length {len(text)})")
    rule_set = tuple(rules)
    wanted = quote.strip()
    if not wanted:
        return NOT_FOUND
    folded = _fold_document(text, rule_set)
    folded_quote = fold(wanted, rule_set).text.strip()
    whole = [(0, len(text))]
    regions = _regions(text, folded, windows)
    if not regions:
        return _find(text, wanted, folded, folded_quote, whole, after, fuzzy) or NOT_FOUND
    inside = _find(text, wanted, folded, folded_quote, regions, after, fuzzy)
    if inside is not None:
        return inside
    elsewhere = _find(text, wanted, folded, folded_quote, whole, after, fuzzy)
    if elsewhere is None:
        return NOT_FOUND
    return Alignment("misattributed", elsewhere.span, elsewhere.score)


def _find(
    text: str,
    wanted: str,
    folded: Folded,
    folded_quote: str,
    regions: Sequence[tuple[int, int]],
    after: int,
    fuzzy: FuzzyPolicy | None,
) -> Alignment | None:
    best: tuple[_LiteralKey, Alignment] | None = None
    for low, high in regions:
        candidates = [
            *_exact(text, wanted, low, high, after),
            *_normalized(text, folded, folded_quote, low, high, after),
        ]
        for key, span in candidates:
            if best is None or key < best[0]:
                kind: MatchKind = "exact" if key[2] == _EXACT else "normalized"
                best = (key, Alignment(kind, span, 1.0))
    if best is not None:
        return best[1]
    if fuzzy is None:
        return None
    return _fuzzy(text, folded, folded_quote, regions, after, fuzzy)


def _exact(
    text: str, wanted: str, low: int, high: int, after: int
) -> Iterator[tuple[_LiteralKey, tuple[int, int]]]:
    position = text.find(wanted, low, high)
    while position != -1:
        # A quote can stop at a letter whose diacritic follows it; the span takes the diacritic.
        end = _past_marks(text, position + len(wanted), high)
        before = position < after
        inside = _inside_word(text, position, end)
        yield (before, inside, _EXACT, position), (position, end)
        if not before and not inside:  # no later match of this tier can rank higher
            return
        position = text.find(wanted, position + 1, high)


def _normalized(
    text: str, folded: Folded, folded_quote: str, low: int, high: int, after: int
) -> Iterator[tuple[_LiteralKey, tuple[int, int]]]:
    if not folded_quote:
        return
    folded_low = folded.position_of(low)
    folded_high = folded.position_of(high)
    position = folded.text.find(folded_quote, folded_low, folded_high)
    while position != -1:
        folded_end = position + len(folded_quote)
        start, end = folded.to_original(position, folded_end)
        end = _past_marks(text, end, high)
        if end <= high:
            before = start < after
            inside = _inside_word(folded.text, position, folded_end)
            yield (before, inside, _NORMALIZED, start), (start, end)
            if not before and not inside:
                return
        position = folded.text.find(folded_quote, position + 1, folded_high)


def _fuzzy(
    text: str,
    folded: Folded,
    folded_quote: str,
    regions: Sequence[tuple[int, int]],
    after: int,
    policy: FuzzyPolicy,
) -> Alignment | None:
    quote = _WORD.findall(folded_quote)
    if not quote:
        return None
    starts, ends, places = _words(folded.text)
    best: tuple[_FuzzyKey, Alignment] | None = None
    for low, high in regions:
        first = bisect_left(starts, folded.position_of(low))
        last = bisect_right(ends, folded.position_of(high))
        for head, tail, matched in _runs(places, first, last, quote, policy):
            start, end = folded.to_original(starts[head], ends[tail])
            end = _past_marks(text, end, high)
            if start < low or end > high:
                continue
            coverage = matched / len(quote)
            density = matched / (tail - head + 1)
            key = (start < after, -coverage, -density, start)
            if best is None or key < best[0]:
                best = (key, Alignment("fuzzy", (start, end), coverage * density))
            if not key[0] and coverage == 1 and density == 1:  # nothing can rank higher
                return best[1]
    return None if best is None else best[1]


def _runs(
    places: dict[str, list[int]],
    first: int,
    last: int,
    quote: Sequence[str],
    policy: FuzzyPolicy,
) -> Iterator[tuple[int, int, int]]:
    """Each accepted run of quote words: its first word's index, its last word's, the count.

    A run starts at a text word the quote has. Its count is the longest common subsequence of the
    quote's words and the text's words from there on. A run is at most len(quote) / density words
    long, so only stretches that hold enough of the quote's words (each counted no more often than
    the quote has it) are computed. Words the quote does not have change no count, so only the
    quote's own words are visited, from the index of where each word appears.
    """
    size = len(quote)
    need = max(1, math.ceil(policy.coverage * size - _EPSILON))
    reach = max(1, math.floor(size / policy.density + _EPSILON))
    allowed = Counter(quote)
    masks: dict[str, int] = {}
    for bit, word in enumerate(quote):
        masks[word] = masks.get(word, 0) | (1 << bit)
    full = (1 << size) - 1
    hits: list[tuple[int, str]] = []
    for word in allowed:
        found = places.get(word, [])
        hits.extend(
            (index, word) for index in found[bisect_left(found, first) : bisect_left(found, last)]
        )
    hits.sort()
    in_reach: Counter[str] = Counter()
    bound = 0  # the most quote words the stretch in reach could match
    right = 0
    for left, (start, word) in enumerate(hits):
        while right < len(hits) and hits[right][0] < start + reach:
            entering = hits[right][1]
            if in_reach[entering] < allowed[entering]:
                bound += 1
            in_reach[entering] += 1
            right += 1
        if bound >= need:
            run = _best_run(hits, left, right, masks, full, need, policy.density)
            if run is not None:
                yield start, run[0], run[1]
        in_reach[word] -= 1
        if in_reach[word] < allowed[word]:
            bound -= 1


def _best_run(
    hits: Sequence[tuple[int, str]],
    left: int,
    right: int,
    masks: dict[str, int],
    full: int,
    need: int,
    density: float,
) -> tuple[int, int] | None:
    """The run from hits[left] with the highest count that passes both thresholds.

    The count is kept with the bit-parallel longest common subsequence: bit k of `vector` is
    cleared once quote word k is matched, so the count is the number of cleared bits.
    """
    start = hits[left][0]
    size = full.bit_length()
    vector = full
    matched = 0
    chosen: tuple[int, int] | None = None
    for step in range(left, right):
        index, word = hits[step]
        common = vector & masks[word]
        vector = ((vector + common) | (vector - common)) & full
        count = size - vector.bit_count()
        if count > matched:
            matched = count
            if matched >= need and matched + _EPSILON >= density * (index - start + 1):
                chosen = (index, matched)
    return chosen


def _regions(
    text: str, folded: Folded, windows: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if not 0 <= start <= end <= len(text):
            raise ValueError(f"window {start}..{end} is outside the text (length {len(text)})")
        if merged:
            first, last = merged[-1]
            gap = folded.text[folded.position_of(last) : folded.position_of(start)]
            if start <= last or not gap.strip():
                merged[-1] = (first, max(last, end))
                continue
        merged.append((start, end))
    return merged


def _inside_word(text: str, start: int, end: int) -> bool:
    """Whether the stretch from `start` to `end` begins or ends inside a longer word."""
    return (start > 0 and _is_word(text[start]) and _is_word(text[start - 1])) or (
        end < len(text) and _is_word(text[end - 1]) and _is_word(text[end])
    )


def _is_word(char: str) -> bool:
    return char.isalnum() or char == "_" or unicodedata.category(char) in ("Mn", "Mc", "Me")


def _past_marks(text: str, end: int, limit: int) -> int:
    """`end` moved past combining marks, so a span never cuts a letter from its diacritics."""
    while end < limit and unicodedata.category(text[end]) in ("Mn", "Me"):
        end += 1
    return end


def _fold_document(text: str, rules: tuple[Rule, ...]) -> Folded:
    try:
        return _fold_cached(text, rules)
    except TypeError:  # a caller's rule that cannot be hashed: fold without the cache
        return fold(text, rules)


@lru_cache(maxsize=4)
def _fold_cached(text: str, rules: tuple[Rule, ...]) -> Folded:
    # A document is folded once for all its quotes, not once per quote.
    return fold(text, rules)


@lru_cache(maxsize=4)
def _words(folded_text: str) -> tuple[list[int], list[int], dict[str, list[int]]]:
    """Where each word of a folded text starts and ends, and the indexes at which each appears."""
    starts: list[int] = []
    ends: list[int] = []
    places: dict[str, list[int]] = {}
    for index, match in enumerate(_WORD.finditer(folded_text)):
        starts.append(match.start())
        ends.append(match.end())
        places.setdefault(match.group(), []).append(index)
    return starts, ends, places

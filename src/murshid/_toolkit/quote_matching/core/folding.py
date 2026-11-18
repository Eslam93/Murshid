"""Folding: a text made comparable, with a map back to the original characters.

Two writings of the same words often differ only in ways a reader ignores: a curly quote for a
straight one, a line break for a space, أ for ا, a diacritic, ٣ for 3. `fold` rewrites a text so
that such writings become equal, and keeps, for every character of the folded text, the start and
end of the original characters it came from. A match found in the folded text is then turned back
into a span of the original text with `Folded.to_original`.

A rule works on the text as the earlier rules left it. There are two kinds:

- `CharRule`: each character becomes a string (itself, another character, several, or nothing).
  Each new character points at the character it came from.
- `PatternRule`: every match of a regular expression becomes a fixed string. Each new character
  points at the whole match; an empty replacement removes the match.

Each rule has a stage. `fold` runs the rules stage by stage (markup, then characters, then
spacing), and in the order given within a stage, so `LATIN + ARABIC + TRANSCRIPT` and
`TRANSCRIPT + ARABIC + LATIN` fold a text the same way. A caller adds its own rules to a set the
same way, as a tuple.

`fold_text` gives the same folded text without the map, for a caller that only compares texts,
such as a search index. It remembers how each character was rewritten, per rule set, so folding
many short texts costs about one table lookup per character.
"""

from __future__ import annotations

import functools
import operator
import re
import unicodedata
from array import array
from bisect import bisect_left
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

__all__ = [
    "ARABIC",
    "CHARACTERS",
    "DEFAULT_RULES",
    "LATIN",
    "MARKUP",
    "SPACING",
    "TRANSCRIPT",
    "CharRule",
    "Folded",
    "PatternRule",
    "Rule",
    "fold",
    "fold_text",
]

MARKUP = 10  # rules that remove or rewrite runs of text, such as transcript tags
CHARACTERS = 20  # rules that rewrite one character at a time
SPACING = 30  # rules that tidy the spaces the earlier rules left


@dataclass(frozen=True)
class CharRule:
    """Rewrites each character into a string: itself, another character, several, or nothing.

    `mapping` must return the same string for the same character every time: `fold` rewrites each
    distinct character of a text once, and `fold_text` remembers the rewrite between calls.
    """

    name: str
    mapping: Callable[[str], str]
    stage: int = CHARACTERS


@dataclass(frozen=True)
class PatternRule:
    """Rewrites every match of `pattern` into `replacement`, taken literally ("" removes it)."""

    name: str
    pattern: re.Pattern[str]
    replacement: str = ""
    stage: int = MARKUP


Rule = CharRule | PatternRule


@dataclass(frozen=True, eq=False)
class Folded:
    """A folded text and its map back to the original.

    The folded character at index i came from the original characters `starts[i]` to `ends[i]`
    (end excluded). Both sequences never decrease.
    """

    text: str
    starts: Sequence[int]
    ends: Sequence[int]
    source_length: int

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """The span of the original text that the folded span `start` to `end` came from.

        The span always covers whole original characters: a match on the "i" of the folded
        "fi" ligature (one character, U+FB01) maps back to the whole ligature.
        """
        if not 0 <= start <= end <= len(self.text):
            raise ValueError(f"span {start}..{end} is outside the folded text")
        if start == end:
            position = self.starts[start] if start < len(self.text) else self.source_length
            return position, position
        return self.starts[start], self.ends[end - 1]

    def position_of(self, original: int) -> int:
        """The first folded index whose original character starts at or after `original`."""
        return bisect_left(self.starts, original)


def fold(text: str, rules: Iterable[Rule]) -> Folded:
    """The folded text and its map back to `text`, after every rule, stage by stage."""
    folded = text
    starts = array("q", range(len(text)))
    ends = array("q", range(1, len(text) + 1))
    for step in _steps(rules):
        if isinstance(step, PatternRule):
            folded, starts, ends = _apply_pattern(folded, starts, ends, step)
        else:
            folded, starts, ends = _apply_characters(folded, starts, ends, step)
    return Folded(folded, starts, ends, len(text))


def _steps(rules: Iterable[Rule]) -> list[PatternRule | tuple[CharRule, ...]]:
    """The rules in the order they run: by stage, then in the order given.

    Neighbouring character rules form one group, so a character passes through the whole group
    before the next character starts. `fold` and `fold_text` both run these steps.
    """
    given = list(rules)
    for rule in given:
        if not isinstance(rule, CharRule | PatternRule):
            raise TypeError(f"not a folding rule: {rule!r}")
    ordered = sorted(given, key=lambda rule: rule.stage)  # stable: the given order stays per stage
    steps: list[PatternRule | tuple[CharRule, ...]] = []
    group: list[CharRule] = []
    for rule in ordered:
        if isinstance(rule, CharRule):
            group.append(rule)
            continue
        if group:
            steps.append(tuple(group))
            group = []
        steps.append(rule)
    if group:
        steps.append(tuple(group))
    return steps


def _rewrite(char: str, rules: Sequence[CharRule]) -> str:
    """One character after a group of character rules: each rule rewrites each character that the
    rule before it left."""
    mapped = char
    for rule in rules:
        mapped = "".join(rule.mapping(part) for part in mapped)
    return mapped


def _apply_characters(
    text: str, starts: array[int], ends: array[int], rules: Sequence[CharRule]
) -> tuple[str, array[int], array[int]]:
    # A document repeats few distinct characters, so each one is rewritten once and remembered.
    seen: dict[str, str] = {}
    pieces: list[str] = []
    new_starts: array[int] = array("q")
    new_ends: array[int] = array("q")
    for index, char in enumerate(text):
        mapped = seen.get(char)
        if mapped is None:
            mapped = _rewrite(char, rules)
            seen[char] = mapped
        if not mapped:
            continue
        pieces.append(mapped)
        if len(mapped) == 1:
            new_starts.append(starts[index])
            new_ends.append(ends[index])
        else:
            new_starts.extend([starts[index]] * len(mapped))
            new_ends.extend([ends[index]] * len(mapped))
    return "".join(pieces), new_starts, new_ends


def _apply_pattern(
    text: str, starts: array[int], ends: array[int], rule: PatternRule
) -> tuple[str, array[int], array[int]]:
    pieces: list[str] = []
    new_starts: array[int] = array("q")
    new_ends: array[int] = array("q")
    last = 0
    for match in rule.pattern.finditer(text):
        first, after = match.span()
        if first == after:  # an empty match has no characters to point back to
            continue
        pieces.append(text[last:first])
        new_starts.extend(starts[last:first])
        new_ends.extend(ends[last:first])
        if rule.replacement:
            pieces.append(rule.replacement)
            new_starts.extend([starts[first]] * len(rule.replacement))
            new_ends.extend([ends[after - 1]] * len(rule.replacement))
        last = after
    if last == 0 and not pieces:
        return text, starts, ends
    pieces.append(text[last:])
    new_starts.extend(starts[last:])
    new_ends.extend(ends[last:])
    return "".join(pieces), new_starts, new_ends


# ---- Folding without the map ------------------------------------------------------------------

_Step = Callable[[str], str]

# A rule set's steps, keyed by the identities of its rules. The entry holds the rules, so no other
# object can take one of those identities while the entry lives, and no rule is hashed or
# compared on the way in. A caller that builds new rules for every call fills the cache, which is
# then emptied; it never grows past this size.
_PLAN_LIMIT = 32
_PLANS: dict[tuple[int, ...], tuple[tuple[Rule, ...], tuple[_Step, ...]]] = {}
# Characters remembered per group of character rules. A text made of many rare characters cannot
# grow a table past this; a character beyond it is rewritten again each time it appears.
_REMEMBERED_LIMIT = 16_384


def fold_text(text: str, rules: Iterable[Rule]) -> str:
    """`fold(text, rules).text`, without building the map back to the original.

    A group of character rules becomes a table for `str.translate` that rewrites a character the
    first time a text asks for it and keeps the result, so later texts read it from the table. A
    pattern rule becomes one `re.sub` that skips empty matches and inserts its replacement as
    written, as `fold` does.
    """
    for step in _plan(rules):
        text = step(text)
    return text


def _plan(rules: Iterable[Rule]) -> tuple[_Step, ...]:
    given = rules if isinstance(rules, tuple) else tuple(rules)
    key = tuple(map(id, given))
    entry = _PLANS.get(key)
    if entry is not None:
        return entry[1]
    steps = tuple(_as_step(step) for step in _steps(given))
    if len(_PLANS) >= _PLAN_LIMIT:
        _PLANS.clear()
    _PLANS[key] = (given, steps)
    return steps


def _as_step(step: PatternRule | tuple[CharRule, ...]) -> _Step:
    if isinstance(step, PatternRule):
        replacement = step.replacement

        def literal(match: re.Match[str]) -> str:
            # `fold` leaves an empty match as it is, so it is replaced by nothing here. A function's
            # result is inserted as written: a backslash in it is not read as a group reference.
            return replacement if match.end() > match.start() else ""

        return functools.partial(step.pattern.sub, literal)
    # `methodcaller` calls `text.translate(table)` without a Python frame of its own.
    return operator.methodcaller("translate", _Rewrites(step))


class _Rewrites(dict[int, str]):
    """A table for `str.translate` that rewrites a character the first time a text asks for it.

    `str.translate` looks each character up in the table; a character the table does not hold yet
    reaches `__missing__`, which rewrites it with the group's rules and keeps the result.
    """

    __slots__ = ("_rules",)

    def __init__(self, rules: tuple[CharRule, ...]) -> None:
        super().__init__()
        self._rules = rules

    def __missing__(self, code: int) -> str:
        rewritten = _rewrite(chr(code), self._rules)
        if len(self) < _REMEMBERED_LIMIT:
            self[code] = rewritten
        return rewritten


# ---- Latin --------------------------------------------------------------------------------------

_QUOTES_AND_DASHES = {
    **dict.fromkeys("\u2018\u2019\u201a\u201b\u2032\u2039\u203a", "'"),
    **dict.fromkeys("\u201c\u201d\u201e\u201f\u2033\u00ab\u00bb", '"'),
    **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63", "-"),
}
# Zero-width space, non-joiner, joiner, word joiner and byte order mark: nothing to a reader.
_ZERO_WIDTH = frozenset("\u200b\u200c\u200d\u2060\ufeff")

LATIN: tuple[Rule, ...] = (
    CharRule("latin_compatibility", lambda char: unicodedata.normalize("NFKC", char)),
    CharRule("latin_case", str.casefold),
    CharRule("latin_quotes_and_dashes", lambda char: _QUOTES_AND_DASHES.get(char, char)),
    CharRule("latin_zero_width", lambda char: "" if char in _ZERO_WIDTH else char),
    # Any run of white space becomes one space; a single plain space is left as it is.
    PatternRule("latin_whitespace", re.compile(r"\s{2,}|[^\S ]"), " ", stage=SPACING),
)
"""Unicode NFKC per character (ligatures, full-width forms, no-break spaces), case folding,
typographic quotes and dashes, zero-width characters, and runs of white space."""


# ---- Arabic -------------------------------------------------------------------------------------


def _is_presentation_form(char: str) -> bool:
    return "\ufb50" <= char <= "\ufdff" or "\ufe70" <= char <= "\ufefe"


# Left-to-right, right-to-left and Arabic letter marks, embeddings, overrides and isolates.
_DIRECTION_MARKS = frozenset(
    "\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
)
# Harakat and tanween, shadda and sukun, madda, hamza above and below written as marks, the
# superscript alef, Quranic marks, and the tatweel (the stretching stroke, which has no sound).
_MARKS = frozenset(
    [chr(code) for code in range(0x0610, 0x061B)]
    + [chr(code) for code in range(0x064B, 0x0660)]
    + ["\u0670", "\u0640"]
    + [chr(code) for code in range(0x06D6, 0x06DD)]
    + [chr(code) for code in range(0x06DF, 0x06E5)]
    + ["\u06e7", "\u06e8"]
    + [chr(code) for code in range(0x06EA, 0x06EE)]
)
# A hamza or madda on a carrier folds to the bare carrier, so a letter written whole (أ) and the
# same letter written as a carrier and a mark (ا then U+0654) fold alike once the mark is removed.
_LETTERS = {
    **dict.fromkeys("آأإٱ", "ا"),  # alef with madda, hamza above, hamza below, wasla
    "ؤ": "و",  # hamza on waw
    "ئ": "ي",  # hamza on ya
    "ى": "ي",  # alef maqsura
    "ة": "ه",  # ta marbuta
    "\u06cc": "ي",  # the Persian form of ya
    "\u06a9": "ك",  # the Persian form of kaf
}
_DIGITS = {
    **{chr(0x0660 + value): str(value) for value in range(10)},  # ٠ to ٩
    **{chr(0x06F0 + value): str(value) for value in range(10)},  # the Persian forms
}
_PUNCTUATION = {
    "،": ",",  # comma
    "؛": ";",  # semicolon
    "؟": "?",  # question mark
    "٪": "%",  # percent sign
    "\u066b": ".",  # decimal separator
    "\u066c": ",",  # thousands separator
}

ARABIC: tuple[Rule, ...] = (
    # A ligature such as ﻷ (lam-alef with hamza) becomes its letters, which the next rules fold.
    CharRule(
        "arabic_presentation_forms",
        lambda char: unicodedata.normalize("NFKC", char) if _is_presentation_form(char) else char,
    ),
    CharRule("arabic_direction_marks", lambda char: "" if char in _DIRECTION_MARKS else char),
    CharRule("arabic_marks", lambda char: "" if char in _MARKS else char),
    CharRule("arabic_letters", lambda char: _LETTERS.get(char, char)),
    CharRule("arabic_digits", lambda char: _DIGITS.get(char, char)),
    CharRule("arabic_punctuation", lambda char: _PUNCTUATION.get(char, char)),
)
"""Presentation forms, direction marks, diacritics and tatweel, hamza and alef forms, alef
maqsura, ta marbuta, Arabic-Indic digits, and Arabic punctuation."""


# ---- Transcript markup ----------------------------------------------------------------------

TRANSCRIPT: tuple[Rule, ...] = (
    # Annotations such as {disfmarker} or {vocalsound}, which nobody said.
    PatternRule("transcript_tags", re.compile(r"\{[^{}\n]{1,40}\}"), ""),
    # Transcripts often write "the curve ." where a quote writes "the curve.".
    PatternRule(
        "transcript_space_before_punctuation",
        re.compile(r"\s+(?=[.,;:!?%)\]،؛؟٪])"),
        "",
        stage=SPACING,
    ),
)
"""Transcript annotations in braces, and spaces before punctuation."""

DEFAULT_RULES: tuple[Rule, ...] = LATIN + ARABIC + TRANSCRIPT
"""Every set this core ships."""

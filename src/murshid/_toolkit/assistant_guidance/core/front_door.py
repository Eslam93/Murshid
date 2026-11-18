"""The front door: answer a greeting or "what can you do" without a model call.

"hi", "hello!", "السلام عليكم", "what can you do?" and "ماذا تستطيع أن تفعل؟" need no lookup and no
model: code answers from the face's examples at once. Only a whole message of greetings and
capability questions is answered here. "hi, show my loans" holds a request, so it goes on to the
model, as does any word the phrase lists do not hold.

A message is folded with W03 (case, Arabic letter forms and marks, Arabic punctuation), its
punctuation is removed, and its words must be covered, end to end, by the phrases of `Phrases`:
greetings, capability questions and fillers ("there", "please", "يا"). Fillers alone are not
enough: "please" is not a greeting. A message that holds a capability question is `capabilities`;
one of greetings only is `greeting`. The reply's language is the language whose phrases covered
the most words, the earlier set winning a tie.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from ...quote_matching.core import ARABIC, LATIN, Rule, fold_text
from .wording import DEFAULT_COPY, Copy, copy_for, listed

__all__ = [
    "ARABIC_PHRASES",
    "DEFAULT_PHRASES",
    "ENGLISH_PHRASES",
    "FOLDING",
    "MAX_WORDS",
    "Hello",
    "HelloKind",
    "Opening",
    "Phrases",
    "front_door",
    "match_front_door",
    "normalized",
]

FOLDING: Final[tuple[Rule, ...]] = LATIN + ARABIC
"""W03's Latin and Arabic folding."""
MAX_WORDS: Final = 12
"""A longer message is never only a greeting, so it is not read at all."""

HelloKind = Literal["greeting", "capabilities"]
_KINDS: Final = ("greeting", "capabilities", "filler")
_NOT_A_WORD: Final = re.compile(r"[\W_]+")


def normalized(text: str, rules: Sequence[Rule] = FOLDING) -> str:
    """The text as phrases and questions are compared: folded, punctuation removed, one space
    between words."""
    return " ".join(_NOT_A_WORD.sub(" ", fold_text(text, tuple(rules))).split())


@dataclass(frozen=True)
class Phrases:
    """The front door's phrases in one language: whole greetings, whole capability questions, and
    fillers that may stand beside them."""

    language: str
    greetings: tuple[str, ...]
    capabilities: tuple[str, ...]
    fillers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.language.strip():
            raise ValueError("a phrase set names its language")
        for name in ("greetings", "capabilities", "fillers"):
            value = getattr(self, name)
            # A single string is a sequence of letters: refuse it rather than read each letter.
            if isinstance(value, str) or not isinstance(value, tuple):
                raise TypeError(f"{name} is a tuple of strings, not {type(value).__name__}")
            if any(not normalized(phrase) for phrase in value):
                raise ValueError(f"{self.language}: a phrase in {name} is empty after folding")
        if not self.greetings and not self.capabilities:
            raise ValueError(f"{self.language}: a phrase set holds a greeting or a question")


ENGLISH_PHRASES: Final = Phrases(
    "en",
    greetings=(
        "hi",
        "hello",
        "hey",
        "hiya",
        "good morning",
        "good afternoon",
        "good evening",
        "good day",
        "morning",
        "greetings",
        "how are you",
        "salam",
        "salaam",
        "salam alaikum",
        "assalamu alaikum",
    ),
    capabilities=(
        "what can you do",
        "what can you do for me",
        "what can you help with",
        "what can you help me with",
        "what do you do",
        "how can you help",
        "how can you help me",
        "how do you work",
        "what can i ask",
        "what can i ask you",
        "what should i ask",
        "who are you",
        "what are you",
        "help",
        "help me",
    ),
    fillers=("there", "again", "please", "all", "everyone", "and", "so", "ok", "okay", "assistant"),
)
ARABIC_PHRASES: Final = Phrases(
    "ar",
    greetings=(
        "السلام عليكم",
        "السلام عليكم ورحمة الله",
        "السلام عليكم ورحمة الله وبركاته",
        "سلام",
        "سلام عليكم",
        "مرحبا",
        "مرحبتين",
        "أهلا",
        "أهلا وسهلا",
        "أهلين",
        "هلا",
        "هاي",
        "صباح الخير",
        "صباح النور",
        "مساء الخير",
        "مساء النور",
        "كيف حالك",
        "كيفك",
        "شلونك",
        "ازيك",
    ),
    capabilities=(
        "ماذا تستطيع أن تفعل",
        "ماذا يمكنك أن تفعل",
        "ماذا تفعل",
        "ما الذي تستطيع فعله",
        "ما الذي يمكنك فعله",
        "بماذا تساعدني",
        "بماذا يمكنك مساعدتي",
        "كيف تساعدني",
        "كيف يمكنك مساعدتي",
        "كيف أستخدمك",
        "ماذا أسأل",
        "ماذا يمكنني أن أسأل",
        "ايش تقدر تسوي",
        "وش تقدر تسوي",
        "شو بتقدر تعمل",
        "تقدر تعمل ايه",
        "من أنت",
        "مين انت",
        "مساعدة",
        "ساعدني",
    ),
    fillers=("يا", "من فضلك", "لو سمحت", "رجاء", "و", "مساعد", "المساعد"),
)
DEFAULT_PHRASES: Final[tuple[Phrases, ...]] = (ENGLISH_PHRASES, ARABIC_PHRASES)


@dataclass(frozen=True)
class Opening:
    """What the front door read: the kind of message and the language to answer in."""

    kind: HelloKind
    language: str


@dataclass(frozen=True)
class Hello:
    """The front door's reply, written by code: what it read, the `text`, and the `examples` it
    lists."""

    kind: HelloKind
    language: str
    text: str
    examples: tuple[str, ...]


def match_front_door(
    message: str,
    phrases: Sequence[Phrases] = DEFAULT_PHRASES,
    rules: Sequence[Rule] = FOLDING,
) -> Opening | None:
    """What the message is when it is only greetings and capability questions, else None."""
    words = normalized(message, rules).split()
    if not words or len(words) > MAX_WORDS:
        return None
    entries = [
        (tuple(normalized(phrase, rules).split()), kind, order, phrase_set.language)
        for order, phrase_set in enumerate(phrases)
        for kind, group in zip(
            _KINDS, (phrase_set.greetings, phrase_set.capabilities, phrase_set.fillers), strict=True
        )
        for phrase in group
    ]
    # reached[i] holds the phrases that cover words[:i] end to end, or None when none do.
    reached: list[list[tuple[str, int, str, int]] | None] = [None] * (len(words) + 1)
    reached[0] = []
    for start in range(len(words)):
        path = reached[start]
        if path is None:
            continue
        for phrase_words, kind, order, language in entries:
            end = start + len(phrase_words)
            if end > len(words) or reached[end] is not None:
                continue
            if tuple(words[start:end]) == phrase_words:
                reached[end] = [*path, (kind, order, language, len(phrase_words))]
    path = reached[len(words)]
    if not path:
        return None
    spoken = [step for step in path if step[0] != "filler"]
    if not spoken:
        return None
    covered: dict[tuple[int, str], int] = {}
    for _, order, language, size in spoken:
        covered[(order, language)] = covered.get((order, language), 0) + size
    (_, chosen), _ = max(covered.items(), key=lambda item: (item[1], -item[0][0]))
    asks = any(step[0] == "capabilities" for step in spoken)
    return Opening("capabilities" if asks else "greeting", chosen)


def front_door(
    message: str,
    examples: Sequence[str] | Mapping[str, Sequence[str]],
    *,
    phrases: Sequence[Phrases] = DEFAULT_PHRASES,
    copy: Mapping[str, Copy] = DEFAULT_COPY,
    limit: int = 4,
    rules: Sequence[Rule] = FOLDING,
) -> Hello | None:
    """The reply to a greeting or a capability question, or None for any other message.

    `examples` are the face's examples, one list for every language or one per language; a
    language without its own list uses the first list given. Up to `limit` are shown. With no
    example to show, the front door does not answer, and the message goes on as any other.
    """
    opening = match_front_door(message, phrases, rules)
    if opening is None:
        return None
    words = copy_for(opening.language, copy)
    shown = tuple(_examples(examples, opening.language)[:limit])
    if not shown:
        return None
    head = words.greeting if opening.kind == "greeting" else words.capabilities
    return Hello(opening.kind, opening.language, listed(head, shown, words), shown)


def _examples(examples: Sequence[str] | Mapping[str, Sequence[str]], language: str) -> list[str]:
    if isinstance(examples, str):
        raise TypeError("examples is a list of questions, not one string")
    if isinstance(examples, Mapping):
        chosen = examples.get(language)
        if chosen is None:
            chosen = next(iter(examples.values()), ())
    else:
        chosen = examples
    if isinstance(chosen, str):
        raise TypeError("examples is a list of questions, not one string")
    return [example.strip() for example in chosen if example.strip()]

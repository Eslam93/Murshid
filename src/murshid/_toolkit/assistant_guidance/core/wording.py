"""The fixed copy code writes when it answers without a model, one set per language.

Every sentence here is shown to a person as the assistant's reply, so it is written once,
reviewed once, and never generated. A `Copy` is checked when it is built: no sentence is empty,
each uses only the placeholders it is given, and the second request for clarification is worded
differently from the first, so a person who answered something unclear sees that the question
changed.

`menu` and `clarification` need only the copy. The front door and `Guide` use the same copy for
their replies.
"""

from __future__ import annotations

import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Final

__all__ = [
    "ARABIC_COPY",
    "DEFAULT_COPY",
    "ENGLISH_COPY",
    "Copy",
    "clarification",
    "copy_for",
    "listed",
    "menu",
]

# The placeholders each sentence may use. A sentence with no entry uses none.
_PLACEHOLDERS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "guidance": frozenset({"label"}),
        "line": frozenset({"text"}),
        "option_line": frozenset({"number", "text"}),
    }
)


@dataclass(frozen=True)
class Copy:
    """The sentences of one language.

    `greeting` and `capabilities` open the front door's reply, before the examples. `menu` opens the
    menu given when the assistant could not work out what the person needs. `guidance` opens the
    reply when a question could not be answered and names the nearest tool (`{label}`);
    `guidance_plain` when there is no tool to name; `unavailable` when there is nothing to suggest.
    `ambiguity` opens a menu of tools, ended by `none_of_these`. `clarify_first` and
    `clarify_again` ask for more detail, the second worded differently. `line` writes a listed
    question, and `option_line` a numbered choice.
    """

    greeting: str
    capabilities: str
    menu: str
    guidance: str
    guidance_plain: str
    unavailable: str
    ambiguity: str
    none_of_these: str
    clarify_first: str
    clarify_again: str
    line: str = "- {text}"
    option_line: str = "{number}. {text}"

    def __post_init__(self) -> None:
        for item in fields(self):
            text = getattr(self, item.name)
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"the copy {item.name!r} is empty")
            allowed = _PLACEHOLDERS.get(item.name, frozenset())
            used = {part[1] for part in string.Formatter().parse(text) if part[1] is not None}
            if not used <= allowed:
                raise ValueError(f"the copy {item.name!r} uses {sorted(used - allowed)}")
        if self.clarify_first.strip() == self.clarify_again.strip():
            raise ValueError("the second clarification is worded differently from the first")


ENGLISH_COPY: Final = Copy(
    greeting="Hello. You can ask me, for example:",
    capabilities="I answer questions with this assistant's tools. You can ask, for example:",
    menu="I could not work out what you need. You can ask, for example:",
    guidance="I could not answer that. The closest I can help with is {label}. You could ask:",
    guidance_plain="I could not answer that. You could ask:",
    unavailable="I could not answer that, and there is nothing else I can look up for you here.",
    ambiguity="Which of these did you mean?",
    none_of_these="None of these",
    clarify_first="Could you say a little more about what you need, so I can pick the right "
    "lookup?",
    clarify_again="I still cannot tell what you need. Please ask the whole question again in one "
    "message, with the name or the period you mean.",
)
ARABIC_COPY: Final = Copy(
    greeting="أهلًا بك. يمكنك أن تسألني مثلًا:",
    capabilities="أجيب عن الأسئلة بأدوات هذا المساعد. يمكنك أن تسأل مثلًا:",
    menu="لم أتمكن من فهم ما تحتاجه. يمكنك أن تسأل مثلًا:",
    guidance="لم أتمكن من الإجابة عن ذلك. أقرب ما أستطيع المساعدة فيه هو {label}. يمكنك أن تسأل:",
    guidance_plain="لم أتمكن من الإجابة عن ذلك. يمكنك أن تسأل:",
    unavailable="لم أتمكن من الإجابة عن ذلك، ولا يوجد هنا ما أستطيع البحث فيه لك.",
    ambiguity="أيّ هذه تقصد؟",
    none_of_these="لا شيء من هذه",
    clarify_first="هل يمكنك توضيح ما تحتاجه أكثر قليلًا حتى أختار البحث المناسب؟",
    clarify_again="ما زلت لا أعرف ما تحتاجه. من فضلك اكتب سؤالك كاملًا في رسالة واحدة، "
    "مع الاسم أو الفترة التي تقصدها.",
)
DEFAULT_COPY: Final[Mapping[str, Copy]] = MappingProxyType({"en": ENGLISH_COPY, "ar": ARABIC_COPY})


def copy_for(language: str, copy: Mapping[str, Copy]) -> Copy:
    """The copy of `language`. An unknown language is the caller's mistake and raises ValueError."""
    found = copy.get(language)
    if found is None:
        raise ValueError(f"no copy for the language {language!r}")
    return found


def listed(opening: str, items: Sequence[str], words: Copy) -> str:
    """An opening sentence, then one line per item."""
    return "\n".join([opening, *(words.line.format(text=item) for item in items)])


def menu(
    examples: Sequence[str],
    *,
    language: str,
    copy: Mapping[str, Copy] = DEFAULT_COPY,
    limit: int = 4,
) -> str:
    """The menu: what the assistant can do, as up to `limit` of the face's examples.

    Given when the assistant could not work out what the person needs: a routing call that failed,
    or a conversation past its ceiling of questions back.
    """
    if isinstance(examples, str):
        raise TypeError("examples is a list of questions, not one string")
    words = copy_for(language, copy)
    shown = [example.strip() for example in examples if example.strip()][:limit]
    return listed(words.menu, shown, words) if shown else words.unavailable


def clarification(attempt: int, *, language: str, copy: Mapping[str, Copy] = DEFAULT_COPY) -> str:
    """The request for more detail: `clarify_first` the first time, `clarify_again` after that."""
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt starts at 1")
    words = copy_for(language, copy)
    return words.clarify_first if attempt == 1 else words.clarify_again

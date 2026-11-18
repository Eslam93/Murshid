"""The guide: a curated map of a face's tools, and the fixed replies code writes from it.

Each tool has a label and suggested questions per language, and neighbours: the other tools a
person who wanted this one may want instead, nearest first. From that map, with no model call:

- `guidance`: when a question could not be answered, name the nearest tool and list its suggested
  question and up to three neighbours' questions.
- `ambiguity_menu`: when two or more tools could answer, list them in the map's fixed order,
  numbered, then "None of these".
- `next_questions`: up to three questions to offer after an answer, from the tool's neighbours.
- `route`: a message equal to a suggested question goes straight to its tool.

Every function filters by `visible`, the tools this person may use now, so a hidden tool is
never named, listed or routed to. The map is checked when the guide is built (`guide_problems`):
every tool has a label and a suggested question in every language of the copy, every neighbour
is another known tool, and no suggested question belongs to two tools. A guide that is built
therefore never meets a missing entry while it answers.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from ...quote_matching.core import Rule
from .front_door import FOLDING, normalized
from .wording import DEFAULT_COPY, Copy, copy_for, listed

__all__ = [
    "MAX_NEIGHBOURS",
    "Choice",
    "Choices",
    "Guidance",
    "Guide",
    "GuideError",
    "ToolGuide",
    "guide_problems",
]

MAX_NEIGHBOURS: Final = 3
"""Guidance lists the nearest tool and at most three neighbours, so the reply stays one glance."""


@dataclass(frozen=True)
class ToolGuide:
    """One tool in the map: its `labels` and `questions` per language, and its `neighbours`.

    The first suggested question of a language is the one shown; every one of them routes to the
    tool. `neighbours` are other tools' names, nearest first.
    """

    name: str
    labels: Mapping[str, str]
    questions: Mapping[str, tuple[str, ...]]
    neighbours: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Kept read-only, so a map shared between guides cannot be changed through one of them.
        object.__setattr__(self, "labels", MappingProxyType(dict(self.labels)))
        object.__setattr__(self, "questions", MappingProxyType(dict(self.questions)))


class GuideError(ValueError):
    """The map is not total or not valid; `problems` names each gap."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class Guidance:
    """Guidance written by code: `text`, the nearest `tool` named (None when there was none to
    name), the `neighbours` listed, and the suggested `questions` shown, for buttons."""

    language: str
    text: str
    tool: str | None
    neighbours: tuple[str, ...]
    questions: tuple[str, ...]


@dataclass(frozen=True)
class Choice:
    """One numbered line of an ambiguity menu; `tool` is None for "None of these"."""

    number: int
    text: str
    tool: str | None


@dataclass(frozen=True)
class Choices:
    """An ambiguity menu: `text` as the person reads it, and its `choices` in order."""

    language: str
    text: str
    choices: tuple[Choice, ...]


def guide_problems(
    tools: Sequence[ToolGuide],
    copy: Mapping[str, Copy] = DEFAULT_COPY,
    rules: Sequence[Rule] = FOLDING,
) -> list[str]:
    """Every gap in the map, as sentences; empty when the map is total and valid."""
    problems: list[str] = []
    if not copy:
        problems.append("the copy holds no language")
    if not tools:
        problems.append("the guide holds no tool")
    names = [tool.name for tool in tools]
    known = set(names)
    for name in sorted({name for name in names if names.count(name) > 1}):
        problems.append(f"the tool {name!r} appears twice")
    owners: dict[str, str] = {}
    for tool in tools:
        if not isinstance(tool.name, str) or not tool.name.strip():
            problems.append("a tool has no name")
            continue
        for language in copy:
            label = tool.labels.get(language)
            if not isinstance(label, str) or not label.strip():
                problems.append(f"{tool.name}: no label in {language!r}")
            questions = tool.questions.get(language)
            if isinstance(questions, str) or not isinstance(questions, Sequence) or not questions:
                problems.append(f"{tool.name}: no suggested question in {language!r}")
                continue
            for question in questions:
                key = normalized(question, rules) if isinstance(question, str) else ""
                if not key:
                    problems.append(f"{tool.name}: an empty suggested question in {language!r}")
                elif key in owners:
                    problems.append(
                        f"{tool.name}: the suggested question {question!r} also routes to "
                        f"{owners[key]}"
                    )
                else:
                    owners[key] = tool.name
        if isinstance(tool.neighbours, str) or not isinstance(tool.neighbours, tuple):
            problems.append(f"{tool.name}: neighbours is a tuple of tool names")
            continue
        seen: set[str] = set()
        for neighbour in tool.neighbours:
            if neighbour == tool.name:
                problems.append(f"{tool.name}: a tool is not its own neighbour")
            elif neighbour not in known:
                problems.append(f"{tool.name}: the neighbour {neighbour!r} is not a tool")
            elif neighbour in seen:
                problems.append(f"{tool.name}: the neighbour {neighbour!r} appears twice")
            seen.add(neighbour)
    return problems


class Guide:
    """A face's tool map and copy, checked once, answering without a model."""

    def __init__(
        self,
        tools: Sequence[ToolGuide],
        *,
        copy: Mapping[str, Copy] = DEFAULT_COPY,
        rules: Sequence[Rule] = FOLDING,
    ) -> None:
        problems = guide_problems(tools, copy, rules)
        if problems:
            raise GuideError(problems)
        self._tools: Mapping[str, ToolGuide] = MappingProxyType({tool.name: tool for tool in tools})
        self._order = tuple(tool.name for tool in tools)
        self._copy: Mapping[str, Copy] = MappingProxyType(dict(copy))
        self._rules = tuple(rules)
        self._routes: Mapping[str, str] = MappingProxyType(
            {
                normalized(question, self._rules): tool.name
                for tool in tools
                for questions in tool.questions.values()
                for question in questions
            }
        )

    @property
    def tools(self) -> tuple[str, ...]:
        """The tools of the map, in its fixed order."""
        return self._order

    def problems(self, tools: Collection[str]) -> list[str]:
        """The gaps between the map and a face's tools: a tool without an entry, an entry that
        names no tool. Empty when the map covers the face exactly."""
        given = _names(tools)
        missing = [
            f"the tool {name!r} has no guide entry"
            for name in sorted(given)
            if name not in self._tools
        ]
        extra = [
            f"the guide entry {name!r} names no tool" for name in self._order if name not in given
        ]
        return missing + extra

    def label(self, tool: str, *, language: str) -> str:
        """The tool's label in `language`."""
        copy_for(language, self._copy)
        return self._tools[tool].labels[language]

    def suggested(self, tool: str, *, language: str) -> str:
        """The tool's first suggested question in `language`: the one shown."""
        copy_for(language, self._copy)
        return self._tools[tool].questions[language][0]

    def suggestions(
        self, *, visible: Collection[str], language: str, limit: int = 4
    ) -> tuple[str, ...]:
        """The first suggested question of each visible tool, in the map's order."""
        copy_for(language, self._copy)
        shown = [name for name in self._order if name in _names(visible)][:limit]
        return tuple(self.suggested(name, language=language) for name in shown)

    def guidance(self, tool: str | None, *, visible: Collection[str], language: str) -> Guidance:
        """Fixed copy for a question that could not be answered.

        `tool` is the nearest tool (the one that refused, say). When it is visible it is named,
        with its suggested question; then up to three of its visible neighbours' questions. When
        it is unknown, hidden or None, nothing is named, and the questions come from its visible
        neighbours, or else from the visible tools in the map's order.
        """
        words = copy_for(language, self._copy)
        shown = _names(visible) & set(self._order)
        nearest = tool if tool in shown else None
        known = self._tools.get(tool) if tool is not None else None
        pool = [name for name in known.neighbours if name in shown] if known else []
        if not pool:
            pool = [name for name in self._order if name in shown and name != tool]
        neighbours = tuple(pool[:MAX_NEIGHBOURS])
        listed_tools = ([nearest] if nearest else []) + list(neighbours)
        questions = tuple(self.suggested(name, language=language) for name in listed_tools)
        if nearest is not None:
            opening = words.guidance.format(label=self.label(nearest, language=language))
            text = listed(opening, questions, words)
        elif questions:
            text = listed(words.guidance_plain, questions, words)
        else:
            text = words.unavailable
        return Guidance(language, text, nearest, neighbours, questions)

    def ambiguity_menu(
        self,
        candidates: Collection[str],
        *,
        visible: Collection[str],
        language: str,
        limit: int = MAX_NEIGHBOURS,
    ) -> Choices | None:
        """A numbered menu of the visible candidates in the map's order, then "None of these".

        None when fewer than two known, visible candidates remain: one candidate is not a choice.
        """
        words = copy_for(language, self._copy)
        wanted = _names(candidates) & _names(visible)
        chosen = [name for name in self._order if name in wanted][:limit]
        if len(chosen) < 2:
            return None
        choices = [
            Choice(number, self.label(name, language=language), name)
            for number, name in enumerate(chosen, start=1)
        ]
        choices.append(Choice(len(choices) + 1, words.none_of_these, None))
        lines = [words.option_line.format(number=c.number, text=c.text) for c in choices]
        return Choices(language, "\n".join([words.ambiguity, *lines]), tuple(choices))

    def next_questions(
        self,
        tool: str,
        *,
        visible: Collection[str],
        language: str,
        limit: int = MAX_NEIGHBOURS,
    ) -> tuple[str, ...]:
        """Questions to offer after an answer from `tool`: the first suggested question of each
        visible neighbour, nearest first. Empty for a tool the map does not hold."""
        copy_for(language, self._copy)
        known = self._tools.get(tool)
        if known is None:
            return ()
        shown = _names(visible)
        names = [name for name in known.neighbours if name in shown][:limit]
        return tuple(self.suggested(name, language=language) for name in names)

    def route(self, message: str, *, visible: Collection[str]) -> str | None:
        """The tool whose suggested question the message is, compared after folding, when that
        tool is visible; None otherwise. Any language's questions count."""
        tool = self._routes.get(normalized(message, self._rules))
        return tool if tool is not None and tool in _names(visible) else None


def _names(tools: Collection[str]) -> set[str]:
    # A single string is a collection of letters: refuse it rather than read each letter.
    if isinstance(tools, str):
        raise TypeError("a list of tool names, not one string")
    return set(tools)

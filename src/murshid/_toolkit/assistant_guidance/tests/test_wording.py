"""W29's fixed copy: the menu, the reworded second clarification, and the checks on the copy."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from murshid._toolkit.assistant_guidance.core import (
    ARABIC_COPY,
    DEFAULT_COPY,
    ENGLISH_COPY,
    Copy,
    clarification,
    menu,
)
from murshid._toolkit.assistant_guidance.tests.library import ARABIC_EXAMPLES, EXAMPLES


@pytest.mark.parametrize("language", ["en", "ar"])
def test_a_second_clarification_is_worded_differently_from_the_first(language: str) -> None:
    first = clarification(1, language=language)
    second = clarification(2, language=language)
    assert first != second
    assert clarification(3, language=language) == second
    assert first == DEFAULT_COPY[language].clarify_first


def test_clarification_counts_from_one() -> None:
    for attempt in (0, -1, True):
        with pytest.raises(ValueError, match="starts at 1"):
            clarification(attempt, language="en")


def test_the_menu_lists_the_faces_examples() -> None:
    assert menu(EXAMPLES, language="en") == "\n".join(
        [ENGLISH_COPY.menu, *(f"- {example}" for example in EXAMPLES)]
    )
    assert menu(ARABIC_EXAMPLES, language="ar").splitlines()[0] == ARABIC_COPY.menu
    assert len(menu([f"Question {n}?" for n in range(9)], language="en").splitlines()) == 5
    assert menu([], language="en") == ENGLISH_COPY.unavailable
    with pytest.raises(TypeError, match="one string"):
        menu("Which books are overdue?", language="en")
    with pytest.raises(ValueError, match="language"):
        menu(EXAMPLES, language="fr")


def test_the_default_copy_has_every_sentence_in_both_languages() -> None:
    for language in ("en", "ar"):
        words = DEFAULT_COPY[language]
        for item in fields(Copy):
            assert getattr(words, item.name).strip(), (language, item.name)


def test_copy_is_checked_when_it_is_built() -> None:
    with pytest.raises(ValueError, match="worded differently"):
        replace(ENGLISH_COPY, clarify_again=ENGLISH_COPY.clarify_first)
    with pytest.raises(ValueError, match="empty"):
        replace(ENGLISH_COPY, menu="  ")
    with pytest.raises(ValueError, match=r"uses \['tool'\]"):
        replace(ENGLISH_COPY, guidance="Try {tool}.")
    with pytest.raises(ValueError, match=r"uses \['label'\]"):
        replace(ENGLISH_COPY, greeting="Hello from {label}.")
    assert replace(ENGLISH_COPY, line="* {text}").line == "* {text}"

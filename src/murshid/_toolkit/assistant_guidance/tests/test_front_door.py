"""W29's front door: a greeting or "what can you do" is answered by code, never by the model."""

from __future__ import annotations

import pytest

from murshid._toolkit.assistant_guidance.core import (
    ARABIC_COPY,
    DEFAULT_PHRASES,
    ENGLISH_COPY,
    MAX_WORDS,
    Opening,
    Phrases,
    front_door,
    match_front_door,
    normalized,
)
from murshid._toolkit.assistant_guidance.tests.library import (
    ARABIC_EXAMPLES,
    EXAMPLES,
    CountingModel,
    turn,
)


@pytest.mark.parametrize(
    ("message", "kind", "language"),
    [
        ("hi", "greeting", "en"),
        ("hello!", "greeting", "en"),
        ("السلام عليكم", "greeting", "ar"),
        ("what can you do?", "capabilities", "en"),
        ("ماذا تستطيع أن تفعل؟", "capabilities", "ar"),
    ],
)
def test_the_named_messages_are_answered_from_the_examples_with_no_model_call(
    message: str, kind: str, language: str
) -> None:
    model = CountingModel()
    written_by, reply = turn(message, model)
    assert written_by == "code"
    assert model.calls == []
    assert match_front_door(message) == Opening(kind, language)  # type: ignore[arg-type]
    examples = EXAMPLES if language == "en" else ARABIC_EXAMPLES
    for example in examples:
        assert f"- {example}" in reply


@pytest.mark.parametrize(
    "message",
    [
        "Hi there!",
        "HELLO",
        "hey, good morning",
        "Hi, what can you do?",
        "help",
        "Please help me.",
        "good evening everyone",
        "hi 👋",
        "أهلًا وسهلًا",
        "مرحبًا يا مساعد",
        "السلام عليكم ورحمة الله وبركاته",
        "مرحبا، ماذا يمكنك أن تفعل؟",
        "صباح الخير",
        "شو بتقدر تعمل؟",
        "salam alaikum",
    ],
)
def test_other_greetings_and_capability_questions_are_answered_by_code(message: str) -> None:
    model = CountingModel()
    assert turn(message, model)[0] == "code"
    assert model.calls == []


@pytest.mark.parametrize(
    "message",
    [
        "hi, show my loans",
        "Hello, which books are overdue?",
        "what can you do about overdue fines?",
        "help me renew a loan",
        "مرحبا، كم إعارة اليوم؟",
        "please",
        "و",
        "👋",
        "",
        "hi " * (MAX_WORDS + 1),
    ],
)
def test_a_message_that_holds_anything_else_goes_on_to_the_model(message: str) -> None:
    model = CountingModel()
    assert turn(message, model)[0] == "model"
    assert model.calls == [message]


def test_the_reply_opens_with_the_copy_of_its_kind_and_language() -> None:
    hello = front_door("hello!", EXAMPLES)
    assert hello is not None
    assert hello.text.splitlines()[0] == ENGLISH_COPY.greeting
    assert hello.examples == EXAMPLES
    question = front_door("what can you do?", EXAMPLES)
    assert question is not None and question.text.splitlines()[0] == ENGLISH_COPY.capabilities
    arabic = front_door("السلام عليكم", {"en": EXAMPLES, "ar": ARABIC_EXAMPLES})
    assert arabic is not None and arabic.text.splitlines()[0] == ARABIC_COPY.greeting
    assert arabic.examples == ARABIC_EXAMPLES


def test_a_language_without_its_own_examples_uses_the_first_list() -> None:
    hello = front_door("مرحبا", {"en": EXAMPLES})
    assert hello is not None
    assert hello.language == "ar" and hello.examples == EXAMPLES


def test_the_examples_are_trimmed_and_capped() -> None:
    many = [" One? ", "", "Two?", "Three?", "Four?", "Five?"]
    hello = front_door("hi", many)
    assert hello is not None
    assert hello.examples == ("One?", "Two?", "Three?", "Four?")
    capped = front_door("hi", many, limit=2)
    assert capped is not None and capped.examples == ("One?", "Two?")


def test_with_no_example_to_show_the_front_door_stays_silent() -> None:
    assert front_door("hi", []) is None
    assert front_door("hi", ["  "]) is None
    with pytest.raises(TypeError, match="one string"):
        front_door("hi", "Which books are overdue?")


def test_the_language_is_the_one_whose_phrases_cover_most_words() -> None:
    assert match_front_door("hi, ماذا تستطيع أن تفعل؟") == Opening("capabilities", "ar")
    assert match_front_door("مرحبا, what can you do?") == Opening("capabilities", "en")
    assert match_front_door("hi مرحبا") == Opening("greeting", "en")  # a tie: the earlier set


def test_the_phrases_are_a_seam() -> None:
    french = Phrases("fr", greetings=("bonjour", "salut"), capabilities=("que sais tu faire",))
    assert match_front_door("Bonjour !", (*DEFAULT_PHRASES, french)) == Opening("greeting", "fr")
    assert match_front_door("Que sais-tu faire ?", (french,)) == Opening("capabilities", "fr")
    assert match_front_door("hello", (french,)) is None


def test_a_phrase_set_is_checked_when_it_is_built() -> None:
    with pytest.raises(TypeError, match="tuple"):
        Phrases("en", greetings="hello", capabilities=())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="empty after folding"):
        Phrases("en", greetings=("hi", "!!"), capabilities=())
    with pytest.raises(ValueError, match="a greeting or a question"):
        Phrases("en", greetings=(), capabilities=(), fillers=("please",))
    with pytest.raises(ValueError, match="names its language"):
        Phrases("", greetings=("hi",), capabilities=())


def test_messages_are_compared_after_folding() -> None:
    assert normalized("  Hello,   WORLD!! ") == "hello world"
    assert normalized("أهلًا") == normalized("اهلا") == "اهلا"
    assert normalized("ماذا؟") == "ماذا"
    assert normalized("snake_case") == "snake case"

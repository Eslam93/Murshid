"""W29's guide: guidance, the ambiguity menu, next questions and suggested-question routing, each
filtered by the tools the person may use, and the totality checks over the map."""

from __future__ import annotations

from dataclasses import replace

import pytest

from murshid._toolkit.assistant_guidance.core import (
    ARABIC_COPY,
    DEFAULT_COPY,
    ENGLISH_COPY,
    Choice,
    Guide,
    GuideError,
    ToolGuide,
    guide_problems,
)
from murshid._toolkit.assistant_guidance.tests.library import GUIDE, NAMES, TOOLS

ALL = set(NAMES)


# ---- Guidance ---------------------------------------------------------------------------------


def test_guidance_names_the_nearest_tool_and_up_to_three_neighbours() -> None:
    found = GUIDE.guidance("count_loans", visible=ALL, language="en")
    assert found.tool == "count_loans"
    assert found.neighbours == ("overdue_books", "renewals", "fines")  # the fourth is left out
    assert found.questions == (
        "How many loans did each branch make this month?",
        "Which books are overdue?",
        "How many loans were renewed this week?",
        "What fines are unpaid?",
    )
    assert found.text == "\n".join(
        [
            ENGLISH_COPY.guidance.format(label="loans by branch"),
            *(f"- {question}" for question in found.questions),
        ]
    )


def test_guidance_lists_only_the_visible_tools() -> None:
    visible = {"count_loans", "fines", "find_member"}
    found = GUIDE.guidance("count_loans", visible=visible, language="en")
    assert found.neighbours == ("fines", "find_member")
    assert "overdue" not in found.text.casefold()
    assert "renewed" not in found.text.casefold()


def test_a_hidden_nearest_tool_is_never_named() -> None:
    found = GUIDE.guidance("fines", visible={"overdue_books", "count_loans"}, language="en")
    assert found.tool is None
    assert found.neighbours == ("overdue_books",)
    assert found.text.splitlines()[0] == ENGLISH_COPY.guidance_plain
    assert "fines" not in found.text.casefold()


def test_without_a_nearest_tool_the_visible_tools_are_listed_in_the_maps_order() -> None:
    for tool in (None, "a_tool_the_map_does_not_hold"):
        found = GUIDE.guidance(tool, visible={"fines", "renewals"}, language="en")
        assert (found.tool, found.neighbours) == (None, ("renewals", "fines"))


def test_a_hidden_tool_without_visible_neighbours_falls_back_to_the_visible_tools() -> None:
    found = GUIDE.guidance("find_member", visible={"count_loans"}, language="en")
    assert (found.tool, found.neighbours) == (None, ("count_loans",))


def test_with_nothing_visible_guidance_says_so() -> None:
    found = GUIDE.guidance("count_loans", visible=set(), language="ar")
    assert found.text == ARABIC_COPY.unavailable
    assert (found.tool, found.neighbours, found.questions) == (None, (), ())


def test_guidance_in_arabic_uses_the_arabic_labels_and_questions() -> None:
    found = GUIDE.guidance("overdue_books", visible=ALL, language="ar")
    assert found.text.splitlines()[0] == ARABIC_COPY.guidance.format(label="الكتب المتأخرة")
    assert found.questions == (
        "ما الكتب المتأخرة؟",
        "ما الغرامات غير المدفوعة؟",
        "كم إعارة جُددت هذا الأسبوع؟",
    )


# ---- The ambiguity menu ---------------------------------------------------------------------


def test_the_ambiguity_menu_lists_candidates_in_a_fixed_order_then_none_of_these() -> None:
    one = GUIDE.ambiguity_menu(["fines", "count_loans"], visible=ALL, language="en")
    other = GUIDE.ambiguity_menu(["count_loans", "fines"], visible=ALL, language="en")
    assert one is not None and one == other
    assert one.choices == (
        Choice(1, "loans by branch", "count_loans"),
        Choice(2, "fines", "fines"),
        Choice(3, "None of these", None),
    )
    assert (
        one.text == "Which of these did you mean?\n1. loans by branch\n2. fines\n3. None of these"
    )


def test_the_ambiguity_menu_needs_two_visible_candidates() -> None:
    assert GUIDE.ambiguity_menu(["fines"], visible=ALL, language="en") is None
    assert GUIDE.ambiguity_menu(["fines", "renewals"], visible={"fines"}, language="en") is None
    assert GUIDE.ambiguity_menu(["fines", "no_such_tool"], visible=ALL, language="en") is None
    menu = GUIDE.ambiguity_menu(
        ["fines", "renewals", "count_loans"], visible={"fines", "renewals"}, language="en"
    )
    assert menu is not None
    assert [choice.tool for choice in menu.choices] == ["renewals", "fines", None]


def test_the_ambiguity_menu_shows_at_most_three_candidates() -> None:
    menu = GUIDE.ambiguity_menu(NAMES, visible=ALL, language="ar")
    assert menu is not None
    assert [choice.tool for choice in menu.choices] == [
        "count_loans",
        "overdue_books",
        "renewals",
        None,
    ]
    assert menu.choices[-1].text == ARABIC_COPY.none_of_these
    assert menu.text.splitlines()[0] == ARABIC_COPY.ambiguity


# ---- Next questions and routing -------------------------------------------------------------


def test_next_questions_come_from_the_neighbour_map() -> None:
    assert GUIDE.next_questions("overdue_books", visible=ALL, language="en") == (
        "What fines are unpaid?",
        "How many loans were renewed this week?",
    )
    assert GUIDE.next_questions("count_loans", visible={"fines", "find_member"}, language="en") == (
        "What fines are unpaid?",
        "Find a member by card number",
    )
    assert len(GUIDE.next_questions("count_loans", visible=ALL, language="en")) == 3
    assert GUIDE.next_questions("no_such_tool", visible=ALL, language="en") == ()


@pytest.mark.parametrize(
    ("message", "tool"),
    [
        ("Which books are overdue?", "overdue_books"),
        ("which books are overdue", "overdue_books"),
        ("  WHICH BOOKS ARE OVERDUE?! ", "overdue_books"),
        ("Loans by branch this year", "count_loans"),
        ("ما الكتب المتأخرة؟", "overdue_books"),
        ("كم إعارة جددت هذا الأسبوع", "renewals"),
    ],
)
def test_a_suggested_question_routes_straight_to_its_tool(message: str, tool: str) -> None:
    assert GUIDE.route(message, visible=ALL) == tool


def test_routing_needs_the_whole_question_and_a_visible_tool() -> None:
    assert GUIDE.route("Which books are overdue at Riverside?", visible=ALL) is None
    assert GUIDE.route("Which books are overdue?", visible=ALL - {"overdue_books"}) is None
    with pytest.raises(TypeError, match="one string"):
        GUIDE.route("Which books are overdue?", visible="overdue_books")


def test_suggestions_are_the_first_question_of_each_visible_tool() -> None:
    assert GUIDE.suggestions(visible={"fines", "count_loans"}, language="en") == (
        "How many loans did each branch make this month?",
        "What fines are unpaid?",
    )


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(ValueError, match="language"):
        GUIDE.guidance("fines", visible=ALL, language="fr")
    with pytest.raises(ValueError, match="language"):
        GUIDE.next_questions("fines", visible=ALL, language="fr")


# ---- Totality ---------------------------------------------------------------------------------


def test_the_library_map_is_total_and_covers_the_faces_tools() -> None:
    assert guide_problems(TOOLS) == []
    assert GUIDE.problems(NAMES) == []
    assert GUIDE.tools == NAMES
    for name in NAMES:
        for language in DEFAULT_COPY:
            assert GUIDE.label(name, language=language)
            assert GUIDE.route(GUIDE.suggested(name, language=language), visible=ALL) == name


def test_coverage_names_a_tool_without_an_entry_and_an_entry_without_a_tool() -> None:
    assert GUIDE.problems((*NAMES, "reserve_book")) == [
        "the tool 'reserve_book' has no guide entry"
    ]
    assert GUIDE.problems(NAMES[1:]) == ["the guide entry 'count_loans' names no tool"]


def with_change(index: int, **change: object) -> list[ToolGuide]:
    tools = list(TOOLS)
    tools[index] = replace(tools[index], **change)  # type: ignore[arg-type]
    return tools


@pytest.mark.parametrize(
    ("tools", "problem"),
    [
        (with_change(1, labels={"en": "overdue books"}), "overdue_books: no label in 'ar'"),
        (
            with_change(1, labels={"en": "overdue books", "ar": " "}),
            "overdue_books: no label in 'ar'",
        ),
        (
            with_change(2, questions={"en": ("Renewals?",)}),
            "renewals: no suggested question in 'ar'",
        ),
        (
            with_change(2, questions={"en": (), "ar": ("التجديدات؟",)}),
            "renewals: no suggested question in 'en'",
        ),
        (
            with_change(2, questions={"en": "Renewals?", "ar": ("التجديدات؟",)}),
            "no suggested question in 'en'",
        ),
        (
            with_change(2, questions={"en": ("?",), "ar": ("التجديدات؟",)}),
            "an empty suggested question",
        ),
        (
            with_change(3, neighbours=("reserve_book",)),
            "fines: the neighbour 'reserve_book' is not a tool",
        ),
        (with_change(3, neighbours=("fines",)), "fines: a tool is not its own neighbour"),
        (with_change(3, neighbours=("find_member", "find_member")), "'find_member' appears twice"),
        (with_change(3, neighbours="find_member"), "fines: neighbours is a tuple of tool names"),
        (
            with_change(4, questions={"en": ("which books are OVERDUE",), "ar": ("ابحث عن عضو",)}),
            "the suggested question 'which books are OVERDUE' also routes to overdue_books",
        ),
        ([*TOOLS, TOOLS[0]], "the tool 'count_loans' appears twice"),
        (with_change(0, name=" "), "a tool has no name"),
        ([], "the guide holds no tool"),
    ],
)
def test_a_map_with_a_gap_is_refused_and_the_gap_is_named(
    tools: list[ToolGuide], problem: str
) -> None:
    assert any(problem in found for found in guide_problems(tools)), guide_problems(tools)
    with pytest.raises(GuideError) as raised:
        Guide(tools)
    assert any(problem in found for found in raised.value.problems)


def test_the_map_is_checked_against_every_language_of_the_copy() -> None:
    english_only = {"en": ENGLISH_COPY}
    tools = with_change(1, labels={"en": "overdue books"})
    assert guide_problems(tools, english_only) == []
    assert Guide(tools, copy=english_only).label("overdue_books", language="en") == "overdue books"
    assert "the copy holds no language" in guide_problems(TOOLS, {})


def test_a_tool_entry_cannot_be_changed_after_it_is_built() -> None:
    labels = {"en": "fines", "ar": "الغرامات"}
    tool = ToolGuide("fines", labels=labels, questions={"en": ("Fines?",), "ar": ("الغرامات؟",)})
    labels["en"] = "changed"
    assert tool.labels["en"] == "fines"
    with pytest.raises(TypeError):
        tool.labels["en"] = "changed"  # type: ignore[index]

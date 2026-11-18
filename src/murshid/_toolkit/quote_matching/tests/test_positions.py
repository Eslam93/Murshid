"""The stretches no quote covers, and UTF-16 positions, through the public interface."""

from __future__ import annotations

import pytest

from murshid._toolkit.quote_matching.core import align, uncited, utf16_positions


def units(text: str, position: int) -> int:
    """The reference: how many UTF-16 code units come before `position`."""
    return len(text[:position].encode("utf-16-le")) // 2


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        (
            "Shipment arrived \U0001f4e6 on time \U0001f44d\U0001f3fd,"
            " the team said \U0001f642 thanks",
            "the team said",
        ),
        (
            "Tomas: \U0001f468\u200d\U0001f469\u200d\U0001f467 family plan approved \U0001f389",
            "family plan",
        ),
        ("تم التسليم \U0001f4e6 في الموعد \U0001f44d", "في الموعد"),
    ],
)
def test_utf16_positions_count_characters_outside_the_basic_plane_as_two(
    text: str, quote: str
) -> None:
    result = align(text, quote)
    assert result.kind == "exact"
    assert result.span is not None
    start, end = result.span
    (converted,) = utf16_positions(text, [result.span])
    assert converted == (units(text, start), units(text, end))
    assert converted[0] > start  # emoji came before the quote
    assert (
        text.encode("utf-16-le")[2 * converted[0] : 2 * converted[1]].decode("utf-16-le") == quote
    )
    # Every position, one emoji at a time.
    spans = [(index, index + 1) for index in range(len(text))]
    assert utf16_positions(text, spans) == [(units(text, s), units(text, e)) for s, e in spans]


def test_utf16_positions_are_unchanged_without_such_characters() -> None:
    text = "يَجِبُ عَلى المُوَرِّد تسليم البضاعة"
    spans = [(0, 5), (7, 7), (3, len(text))]
    assert utf16_positions(text, spans) == spans
    assert utf16_positions(text, []) == []
    with pytest.raises(ValueError, match="outside the text"):
        utf16_positions(text, [(0, len(text) + 1)])


def test_uncited_lists_what_no_span_covers() -> None:
    assert uncited(10, []) == [(0, 10)]
    assert uncited(10, [(0, 10)]) == []
    assert uncited(10, [(6, 8), (2, 4), (3, 5)]) == [(0, 2), (5, 6), (8, 10)]
    assert uncited(10, [(6, 8), (2, 4), (3, 5)], min_chars=2) == [(0, 2), (8, 10)]
    assert uncited(10, [(2, 2)]) == [(0, 10)]  # an empty span covers nothing
    assert uncited(0, []) == []


def test_uncited_shows_the_turns_no_record_quotes() -> None:
    turns = [
        "Hala: The launch moves to June.",
        "Omar: The printer is booked for the second week.",
        "Priya: Tomas sends the plan by Friday.",
    ]
    text = "\n".join(turns)
    spans = []
    for quote in ("The launch moves to June", "Tomas sends the plan by Friday"):
        result = align(text, quote)
        assert result.span is not None
        spans.append(result.span)
    stretches = uncited(len(text), spans, min_chars=10)
    assert [text[start:end].strip() for start, end in stretches] == [
        ".\nOmar: The printer is booked for the second week.\nPriya:"
    ]


def test_uncited_refuses_spans_from_another_text() -> None:
    with pytest.raises(ValueError, match="outside the text"):
        uncited(10, [(8, 12)])
    with pytest.raises(ValueError, match="outside the text"):
        uncited(10, [(5, 3)])
    with pytest.raises(ValueError, match="min_chars"):
        uncited(10, [], min_chars=0)
    with pytest.raises(ValueError, match="negative"):
        uncited(-1, [])

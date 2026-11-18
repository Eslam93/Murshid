"""Finding a figure in a text by value: cited, elsewhere or absent, in digits and in words."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from murshid._toolkit.number_text.core import ARABIC_DECIMAL, FigureFound, figures_in, find_figure

PROBE = "We need fifteen laptops by 2026-11-01 at 900 SAR each."
WHOLE = [(0, len(PROBE))]


def test_the_probes_figures_are_absent_and_its_own_are_cited() -> None:
    # A purchase line read as quantity 50 at 9000, beside a passage that says fifteen at 900
    assert find_figure(Decimal(50), PROBE, WHOLE) == FigureFound("absent")
    assert find_figure(Decimal(9000), PROBE, WHOLE) == FigureFound("absent")
    assert find_figure(Decimal(15), PROBE, WHOLE) == FigureFound("cited", (8, 15), in_words=True)
    assert find_figure(Decimal(900), PROBE, WHOLE) == FigureFound("cited", (41, 44))


def test_a_dates_parts_are_not_figures() -> None:
    assert find_figure(Decimal(2026), PROBE, WHOLE).where == "absent"
    assert find_figure(11, PROBE, WHOLE).where == "absent"
    assert find_figure(1, PROBE, WHOLE).where == "absent"


def test_a_times_parts_are_not_figures() -> None:
    text = "Deliver 30 boxes between 9:30 and 12:00, or 2026-11-01 08:15."
    whole = [(0, len(text))]
    assert find_figure(30, text, whole) == FigureFound("cited", (8, 10))
    assert find_figure(9, text, whole).where == "absent"
    assert find_figure(12, text, whole).where == "absent"
    assert find_figure(15, text, whole).where == "absent"
    assert find_figure(30, "Open 9:30 to 17:30.", [(0, 19)]).where == "absent"
    assert [token.text for token in figures_in("الساعة ٩:٣٠ م، ٤ صناديق")] == ["٤"]


def test_a_codes_digits_and_list_numbering_are_not_figures() -> None:
    assert find_figure(41, "Invoice INV-000041 is open.", [(0, 27)]).where == "absent"
    text = "1. Laptops: 20\n2. Bags: 20"
    assert find_figure(1, text, [(0, len(text))]).where == "absent"
    assert find_figure(20, text, [(0, len(text))]) == FigureFound("cited", (12, 14))


def test_a_figure_outside_the_cited_spans_is_elsewhere() -> None:
    assert find_figure(900, PROBE, [(0, 23)]) == FigureFound("elsewhere", (41, 44))
    assert find_figure(900, PROBE) == FigureFound("elsewhere", (41, 44))


def test_a_number_that_overlaps_a_cited_span_is_cited() -> None:
    assert find_figure(900, PROBE, [(42, 60)]).where == "cited"
    assert find_figure(900, PROBE, [(44, 60)]).where == "elsewhere"  # the span ends where it starts


def test_cited_comes_first_then_digits_before_words_then_the_earliest() -> None:
    text = "Make it 20. As agreed: twenty laptops, 20 in all."
    assert find_figure(20, text, [(12, len(text))]) == FigureFound("cited", (39, 41))
    assert find_figure(20, text, [(12, 38)]) == FigureFound("cited", (23, 29), in_words=True)
    assert find_figure(20, text, [(100, 120)]) == FigureFound("elsewhere", (8, 10))


def test_words_can_be_left_out() -> None:
    assert find_figure(15, PROBE, WHOLE, words=False).where == "absent"


def test_values_compare_as_numbers_over_every_reading() -> None:
    assert find_figure(Decimal("12.5"), "unit price 12,50", [(0, 16)]).where == "cited"
    assert find_figure(Decimal("12.50"), "unit price 12.5", [(0, 15)]).where == "cited"
    assert find_figure(1500, "about 1,500 units", [(0, 17)]).where == "cited"
    assert find_figure(Decimal("1.5"), "about 1,500 units", [(0, 17)]).where == "cited"
    assert find_figure(1500, "about 1,500 units", [(0, 17)], decimal_mark=",").where == "absent"
    assert find_figure(Decimal("12.05"), "unit price 12.5", [(0, 15)]).where == "absent"


def test_arabic_figures_are_found_in_digits_and_in_words() -> None:
    text = "نبغى ١٥ جهاز لابتوب، السعر ٣٨٠٠ ريال للجهاز الواحد"
    assert find_figure(15, text, [(0, 19)]).where == "cited"
    assert find_figure(3800, text, [(0, 19)]).where == "elsewhere"
    assert find_figure(Decimal("4120.5"), f"المجموع ٤١٢٠{ARABIC_DECIMAL}٥٠", [(0, 20)]).where == (
        "cited"
    )
    words = "محتاجين كراسي للقاعة، اتنين أو تلاتة زيادة"
    assert find_figure(3, words, [(0, len(words))]) == FigureFound("cited", (22, 36), True)


def test_a_sign_is_not_read_so_a_figure_compares_by_size() -> None:
    assert find_figure(Decimal(-120), "a credit of 120", [(0, 15)]).where == "cited"


def test_a_figure_inside_your_own_code_shape_is_not_a_figure() -> None:
    shape = re.compile(r"(?<![A-Z0-9])REQ[0-9]{4}(?![A-Z0-9])")
    assert find_figure(42, "REQ0042", [(0, 7)], joined_codes=False).where == "cited"
    assert find_figure(42, "REQ0042", [(0, 7)]).where == "absent"
    assert find_figure(42, "REQ0042", [(0, 7)], code_shape=shape).where == "absent"


def test_a_figure_must_be_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        find_figure(Decimal("NaN"), PROBE)


def test_a_text_scanned_once_gives_the_same_answers_for_many_values() -> None:
    figures = figures_in(PROBE)
    assert [token.text for token in figures] == ["900", "fifteen"]
    for value in (15, 50, 900, 9000, 2026):
        assert find_figure(value, figures, WHOLE) == find_figure(value, PROBE, WHOLE)
    digits_only = figures_in(PROBE, words=False)
    assert find_figure(15, digits_only, WHOLE).where == "absent"
    numbered = figures_in("1. Laptops: 20 at 1,500")
    assert [token.text for token in numbered] == ["20", "1,500"]
    assert figures_in("1,500", decimal_mark=",")[0].readings == ((Decimal("1.5"),),)

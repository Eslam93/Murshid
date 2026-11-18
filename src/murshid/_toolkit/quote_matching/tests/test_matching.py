"""Finding quotes through the public interface, on a made-up contract and a made-up meeting.

The contract is not chronological and has headings, numbered clauses and one clause that runs
across a page break. The meeting is a list of speaker turns. Every company and person is fictional.
"""

from __future__ import annotations

import pytest

from murshid._toolkit.quote_matching.core import MATCH_KINDS, Alignment, FuzzyPolicy, align

Span = tuple[int, int]


def layout(blocks: list[str]) -> tuple[str, list[Span]]:
    """The blocks joined by blank lines, as a reader of documents would join them, and each
    block's start and end in the joined text."""
    spans: list[Span] = []
    position = 0
    for block in blocks:
        spans.append((position, position + len(block)))
        position += len(block) + 2
    return "\n\n".join(blocks), spans


CONTRACT, CLAUSES = layout(
    [
        "1. Definitions",  # page 1
        "1.1 \u201cServices\u201d means the freight handling described in Schedule A.",
        "2. Obligations of the Supplier",
        "2.1 The Supplier shall deliver each consignment within five (5) working days of the"
        " Client\u2019s written request.",
        "2.2 The Supplier shall keep the goods insured until delivery and shall pay the",
        "premium for that insurance without charging it to the Client.",  # page 2
        "3. Obligations of the Client",
        "3.1 The Client shall pay each monthly statement within thirty (30) days of receiving it.",
        "3.2 The Client shall give the Supplier at least ten days\u2019 notice of any change"
        " \u2014 in writing \u2014 to a delivery address.",
        "Signed for Lumen Harbor Freight LLC and Corvane Textiles Ltd, both fictional.",
    ]
)

MEETING, TURNS = layout(
    [
        "Hala: Okay, let's start. The launch date for the field kit is still open.",
        "Omar: I think {disfmarker} we keep the launch in May .",
        "Hala: Agreed .",
        "Priya: I'd rather move it to June \u2014 the printer can't do May.",
        "Omar: Fine, yes. We, uh, move the launch to June .",
        "Hala: Agreed. Tomas will send the revised plan by Friday.",
        "Tomas: Agreed, I'll send it by Friday.",
    ]
)

AR_CONTRACT, AR_CLAUSES = layout(
    [
        "المادة ٣: التزامات الطرف الأول",
        "٣.١ يَجِبُ عَلى المُوَرِّد تسليم البضاعة خلال ٣٠ يوماً من تاريخ الطلب الكتابي.",
        "٣.٢ يُسمّى \u00abالطرف الأول\u00bb في هذا العقد شركة نهر الضوء للشحن، وهي شركة وهمية.",
        "٣.٣ لا يجوز \ufef7ي طرف التنازل عن هذا العقد إلا بموافقة كتابية.",
        "٣.٤ يُعفى الطرف الأول من التزاماته لا\u0654سباب قاهرة،"
        " وتبلغ الـمـدة الـكـلـيـة للعقد سنتين.",
        "رقم العقد\u200f ٢٠٢٦/١٤ \u200eوتاريخه أول يناير.",
        "٣.٥ يدفع الطرف الثاني الرسوم خلال",  # the end of page 1
        "خمسة عشر يوماً من استلام الكشف الشهري.",  # page 2
    ]
)

AR_MEETING, AR_TURNS = layout(
    [
        "هالة: نؤجل الإطلاق إلى شهر يونيو.",
        "عمر: موافق.",
        "هالة: موافق، وسيرسل توماس الخطة المعدلة يوم الخميس.",
        "توماس: آخر موعد هو الخميس.",
    ]
)


def found_text(text: str, result: Alignment) -> str:
    assert result.span is not None, result
    start, end = result.span
    return text[start:end]


@pytest.mark.parametrize(
    ("text", "quote", "kind", "expected"),
    [
        (
            CONTRACT,
            "The Client shall pay each monthly statement within thirty (30) days",
            "exact",
            "The Client shall pay each monthly statement within thirty (30) days",
        ),
        (  # straight quotes for curly ones
            CONTRACT,
            '"Services" means the freight handling',
            "normalized",
            "\u201cServices\u201d means the freight handling",
        ),
        (CONTRACT, "at least ten days' notice", "normalized", "at least ten days\u2019 notice"),
        (  # case
            CONTRACT,
            "the supplier shall deliver each consignment",
            "normalized",
            "The Supplier shall deliver each consignment",
        ),
        (  # hyphens for dashes
            CONTRACT,
            "any change - in writing - to a delivery address",
            "normalized",
            "any change \u2014 in writing \u2014 to a delivery address",
        ),
        (  # one space for a blank line
            CONTRACT,
            "shall pay the premium for that insurance",
            "normalized",
            "shall pay the\n\npremium for that insurance",
        ),
        (  # a transcript tag and a space before a full stop
            MEETING,
            "I think we keep the launch in May.",
            "normalized",
            "I think {disfmarker} we keep the launch in May .",
        ),
        ("Check the \ufb01eld kit first.", "field kit", "normalized", "\ufb01eld kit"),
        (
            "Deliver within \uff13\uff10 days.",
            "within 30 days",
            "normalized",
            "within \uff13\uff10 days",
        ),
        (
            "Send the re\u200bvised plan.",
            "the revised plan",
            "normalized",
            "the re\u200bvised plan",
        ),
    ],
)
def test_english_golden_cases(text: str, quote: str, kind: str, expected: str) -> None:
    result = align(text, quote)
    assert result.kind == kind
    assert result.score == 1.0
    assert found_text(text, result) == expected


@pytest.mark.parametrize(
    ("text", "quote", "kind", "expected"),
    [
        (AR_CONTRACT, "التنازل عن هذا العقد", "exact", "التنازل عن هذا العقد"),
        (  # diacritics, and alef maqsura written as ya
            AR_CONTRACT,
            "يجب علي المورد تسليم البضاعة",
            "normalized",
            "يَجِبُ عَلى المُوَرِّد تسليم البضاعة",
        ),
        (  # Arabic-Indic digits and tanween: the span keeps the tanween on its letter
            AR_CONTRACT,
            "خلال 30 يوما",
            "normalized",
            "خلال ٣٠ يوماً",
        ),
        (AR_CONTRACT, "التزامات الطرف الاول", "normalized", "التزامات الطرف الأول"),
        (AR_CONTRACT, "شركه نهر الضوء للشحن", "normalized", "شركة نهر الضوء للشحن"),
        (AR_CONTRACT, "يعفي الطرف الأول", "normalized", "يُعفى الطرف الأول"),
        (  # guillemets for straight quotes
            AR_CONTRACT,
            '"الطرف الأول" في هذا العقد',
            "normalized",
            "\u00abالطرف الأول\u00bb في هذا العقد",
        ),
        (  # the presentation form of lam-alef with hamza
            AR_CONTRACT,
            "لا يجوز لأي طرف التنازل",
            "normalized",
            "لا يجوز \ufef7ي طرف التنازل",
        ),
        (  # lam-alef with hamza decomposed, as some PDF readers give it
            AR_CONTRACT,
            "لأسباب قاهرة",
            "normalized",
            "لا\u0654سباب قاهرة",
        ),
        (AR_CONTRACT, "المدة الكلية للعقد", "normalized", "الـمـدة الـكـلـيـة للعقد"),
        (  # direction marks and digits
            AR_CONTRACT,
            "رقم العقد 2026/14 وتاريخه",
            "normalized",
            "رقم العقد\u200f ٢٠٢٦/١٤ \u200eوتاريخه",
        ),
        (AR_CONTRACT, "للشحن, وهي شركة وهمية", "normalized", "للشحن، وهي شركة وهمية"),
        (  # collapsed spaces across a page break
            AR_CONTRACT,
            "الرسوم خلال خمسة عشر يوما",
            "normalized",
            "الرسوم خلال\n\nخمسة عشر يوماً",
        ),
        (AR_MEETING, "الخطه المعدله", "normalized", "الخطة المعدلة"),
        (AR_MEETING, "نوجل الاطلاق الي شهر يونيو", "normalized", "نؤجل الإطلاق إلى شهر يونيو"),
        (AR_MEETING, "اخر موعد", "normalized", "آخر موعد"),
    ],
)
def test_arabic_golden_cases(text: str, quote: str, kind: str, expected: str) -> None:
    result = align(text, quote)
    assert result.kind == kind
    assert found_text(text, result) == expected


@pytest.mark.parametrize("fuzzy", [None, FuzzyPolicy()])
@pytest.mark.parametrize(
    ("text", "quote"),
    [
        (CONTRACT, "the client must settle every statement inside a month"),
        (MEETING, "everyone wanted to postpone the product release"),
        (AR_CONTRACT, "على المورّد أن يسلّم السلع في غضون شهر"),
    ],
)
def test_a_paraphrase_is_not_found(text: str, quote: str, fuzzy: FuzzyPolicy | None) -> None:
    assert align(text, quote, fuzzy=fuzzy) == Alignment("not_found", None, 0.0)


def test_repeated_quotes_are_matched_in_order() -> None:
    spans: list[Span] = []
    after = 0
    for _ in range(3):
        result = align(MEETING, "Agreed", after=after)
        assert result.kind == "exact"
        assert result.span is not None
        spans.append(result.span)
        after = result.span[1]
    assert [MEETING[start:end] for start, end in spans] == ["Agreed"] * 3
    assert [TURNS.index(turn) for turn in turns_of(spans, TURNS)] == [2, 5, 6]
    # Folded matches keep the same order.
    after = 0
    folded_spans: list[Span] = []
    for _ in range(3):
        result = align(MEETING, "agreed", after=after)
        assert result.kind == "normalized"
        assert result.span is not None
        folded_spans.append(result.span)
        after = result.span[1]
    assert folded_spans == spans
    # A fourth "Agreed" has nothing after the third: the earliest is returned, not "not found".
    fourth = align(MEETING, "Agreed", after=after)
    assert fourth.kind == "exact"
    assert fourth.span == spans[0]


def turns_of(spans: list[Span], turns: list[Span]) -> list[Span]:
    return [next(t for t in turns if t[0] <= s and e <= t[1]) for s, e in spans]


def test_the_cited_windows_are_searched_first() -> None:
    quote = "The Supplier shall"
    anywhere = align(CONTRACT, quote)
    cited = align(CONTRACT, quote, windows=[CLAUSES[4]])
    assert anywhere.kind == cited.kind == "exact"
    assert anywhere.span is not None and cited.span is not None
    assert within(anywhere.span, CLAUSES[3])
    assert within(cited.span, CLAUSES[4])


def test_a_quote_outside_its_cited_block_is_misattributed() -> None:
    quote = "The Client shall pay each monthly statement"
    result = align(CONTRACT, quote, windows=[CLAUSES[3]])
    assert result.kind == "misattributed"
    assert result.score == 1.0
    assert result.span is not None
    assert within(result.span, CLAUSES[7])
    assert found_text(CONTRACT, result) == quote
    # The same with the fuzzy tier on: the cited block holds nothing close enough.
    assert align(CONTRACT, quote, windows=[CLAUSES[3]], fuzzy=FuzzyPolicy()) == result


@pytest.mark.parametrize(
    ("text", "blocks", "first", "last", "quote", "expected"),
    [
        (
            CONTRACT,
            CLAUSES,
            4,
            5,
            "shall pay the premium for that insurance",
            "shall pay the\n\npremium for that insurance",
        ),
        (
            AR_CONTRACT,
            AR_CLAUSES,
            6,
            7,
            "يدفع الطرف الثاني الرسوم خلال خمسة عشر يوما",
            "يدفع الطرف الثاني الرسوم خلال\n\nخمسة عشر يوماً",
        ),
    ],
)
def test_a_quote_across_a_page_break_is_found_through_its_end_block(
    text: str, blocks: list[Span], first: int, last: int, quote: str, expected: str
) -> None:
    # The caller passes every block from block_id to end_block_id, or one window over all of them.
    for windows in ([blocks[first], blocks[last]], [(blocks[first][0], blocks[last][1])]):
        result = align(text, quote, windows=windows)
        assert result.kind == "normalized"
        assert found_text(text, result) == expected
    # Citing only the first block: the quote runs outside it.
    only_first = align(text, quote, windows=[blocks[first]])
    assert only_first.kind == "misattributed"
    assert found_text(text, only_first) == expected
    # Windows with a block of text between them are not joined.
    apart = align(text, quote, windows=[blocks[first - 1], blocks[last]])
    assert apart.kind == "misattributed"


def test_a_match_at_word_edges_comes_before_one_inside_a_word() -> None:
    text = "They agreed yesterday. Yes, it is settled."
    result = align(text, "yes")
    assert result.kind == "normalized"
    assert found_text(text, result) == "Yes"
    # With no match at word edges, one inside a word is still found: Arabic writes و ("and")
    # joined to the next word.
    arabic = "والكتاب على الطاولة"
    clitic = align(arabic, "الكتاب")
    assert clitic.kind == "exact"
    assert clitic.span == (1, 7)


def test_an_exact_match_keeps_the_last_letter_with_its_diacritic() -> None:
    # The exact tier used to end the span at the quote's last character, so "قال" in "وقالَ"
    # gave (1, 4): the lam without its fatha, unlike the other two tiers.
    text = "وقالَ المدير"
    result = align(text, "قال")
    assert result.kind == "exact"
    assert result.span == (1, 5)
    assert found_text(text, result) == "قالَ"
    # A window that ends between the letter and its mark still bounds the span.
    assert align(text, "قال", windows=[(0, 4)]).span == (1, 4)


def test_the_fuzzy_tier_is_opt_in_and_finds_a_quote_with_fillers_removed() -> None:
    quote = "We move the launch to June"
    assert align(MEETING, quote, windows=[TURNS[4]]).kind == "not_found"
    result = align(MEETING, quote, windows=[TURNS[4]], fuzzy=FuzzyPolicy())
    assert result.kind == "fuzzy"
    assert found_text(MEETING, result) == "We, uh, move the launch to June"
    assert result.score == pytest.approx(6 / 7)  # all 6 words, in a stretch of 7
    # A quote with one word the turn does not have: 6 of 7 words, all next to each other.
    extra = align(
        MEETING, "we will keep the launch in May", windows=[TURNS[1]], fuzzy=FuzzyPolicy()
    )
    assert extra.kind == "fuzzy"
    assert found_text(MEETING, extra) == "we keep the launch in May"
    assert extra.score == pytest.approx(6 / 7)
    # Cited to the wrong turn: found approximately elsewhere, so misattributed.
    elsewhere = align(MEETING, quote, windows=[TURNS[3]], fuzzy=FuzzyPolicy())
    assert elsewhere.kind == "misattributed"
    assert elsewhere.span == result.span
    assert elsewhere.score == result.score


def test_the_fuzzy_thresholds_are_the_policy() -> None:
    quote = "we will surely keep the launch in May"  # 6 of 8 words: coverage 0.75
    assert align(MEETING, quote, fuzzy=FuzzyPolicy()).kind == "fuzzy"
    assert align(MEETING, quote, fuzzy=FuzzyPolicy(coverage=0.8)).kind == "not_found"
    sparse = "Okay start launch kit open"  # 5 of 5 words spread over 14: density 5/14
    assert align(MEETING, sparse, fuzzy=FuzzyPolicy()).kind == "fuzzy"
    assert align(MEETING, sparse, fuzzy=FuzzyPolicy(density=0.5)).kind == "not_found"
    with pytest.raises(ValueError, match="coverage and density"):
        FuzzyPolicy(coverage=0)
    with pytest.raises(ValueError, match="coverage and density"):
        FuzzyPolicy(density=1.5)


def test_an_empty_quote_is_not_found_and_bad_positions_are_refused() -> None:
    assert align(CONTRACT, "   ").kind == "not_found"
    assert align(CONTRACT, "{disfmarker}").kind == "not_found"
    with pytest.raises(ValueError, match="outside the text"):
        align(CONTRACT, "Client", windows=[(10, len(CONTRACT) + 1)])
    with pytest.raises(ValueError, match="outside the text"):
        align(CONTRACT, "Client", windows=[(20, 10)])
    with pytest.raises(ValueError, match="outside the text"):
        align(CONTRACT, "Client", after=-1)
    assert MATCH_KINDS == ("exact", "normalized", "fuzzy", "misattributed", "not_found")


def within(span: Span, window: Span) -> bool:
    return window[0] <= span[0] <= span[1] <= window[1]

"""The dense index through its public interface: cosine order, the checks on the embedder, the
light form, and the metadata filter."""

from __future__ import annotations

import math
from collections.abc import Sequence

import pytest

from murshid._toolkit.hybrid_retrieval.core import DenseIndex, FakeEmbedder, Record, Where, light_form
from murshid._toolkit.hybrid_retrieval.tests.doubles import OFFICE, Scripted, Silent, Spy, at
from murshid._toolkit.lexical_retrieval.core import Hit

ZWNJ = "\u200c"  # the zero-width non-joiner
RLM = "\u200f"  # the right-to-left mark


def scripted_index(cosines: dict[str, float]) -> DenseIndex[str]:
    """Each record's text is its key, at this cosine to the query "q"."""
    vectors = {key: at(cosine) for key, cosine in cosines.items()} | {"q": at(1)}
    return DenseIndex([Record(key, key) for key in cosines], Scripted(vectors))


# ---- Order --------------------------------------------------------------------------------------


def test_the_nearest_record_comes_first_with_its_cosine() -> None:
    index = scripted_index({"far": 0.2, "near": 0.9, "middle": 0.5})
    assert index.search("q") == [Hit("near", 0.9), Hit("middle", 0.5), Hit("far", 0.2)]
    assert len(index) == 3


def test_the_scale_of_a_vector_does_not_matter() -> None:
    embedder = Scripted({"q": [3.0, 0.0], "short": [0.5, 0.5], "long": [40.0, 10.0]})
    index = DenseIndex([Record("short", "short"), Record("long", "long")], embedder)
    assert [hit.key for hit in index.search("q")] == ["long", "short"]
    assert index.search("q")[0].score == pytest.approx(0.970143)


def test_the_limit_is_kept_and_ties_keep_the_given_order() -> None:
    index = scripted_index({"first": 0.5, "second": 0.5, "third": 0.5, "fourth": 0.5})
    assert [hit.key for hit in index.search("q", limit=3)] == ["first", "second", "third"]
    assert index.search("q", limit=0) == []


def test_only_a_cosine_above_the_floor_is_a_hit() -> None:
    index = scripted_index({"same": 1.0, "unrelated": 0.0, "opposite": -1.0})
    assert [hit.key for hit in index.search("q")] == ["same"]
    assert index.search("q", min_score=1.0) == []
    assert [hit.key for hit in index.search("q", min_score=-2.0)] == [
        "same",
        "unrelated",
        "opposite",
    ]


def test_a_blank_query_is_not_embedded() -> None:
    spy = Spy(Silent())
    index = DenseIndex([Record("a", "words")], spy)
    built = len(spy.calls)
    assert index.search("") == []
    assert index.search(" \u200f ") == []
    assert len(spy.calls) == built


def test_an_empty_index_finds_nothing_and_calls_nothing() -> None:
    spy = Spy(Silent())
    assert DenseIndex([], spy).search("anything") == []
    assert spy.calls == []


# ---- What reaches the embedder -------------------------------------------------------------------


def test_records_go_in_batches_and_every_view_goes_in_one_call() -> None:
    spy = Spy(FakeEmbedder(dimensions=16))
    index = DenseIndex([Record(n, f"line {n}") for n in range(7)], spy, batch_size=3)
    assert [len(call) for call in spy.calls] == [3, 3, 1]
    rankings = index.rank(["one", "two"], index.positions())
    assert spy.calls[-1] == ["one", "two"]
    assert len(spy.calls) == 4
    assert len(rankings) == 2


def test_the_prefixes_go_in_front_of_documents_and_queries() -> None:
    spy = Spy(FakeEmbedder(dimensions=16))
    index = DenseIndex(
        [Record("a", "  حبر  أسود  ")], spy, document_prefix="passage: ", query_prefix="query: "
    )
    index.search("أسود")
    assert spy.calls == [["passage: حبر اسود"], ["query: اسود"]]


def test_a_blank_record_is_not_embedded_and_matches_nothing() -> None:
    spy = Spy(FakeEmbedder(dimensions=16))
    index = DenseIndex([Record("blank", " \u200c "), Record("full", "toner")], spy)
    assert spy.calls == [["toner"]]
    assert len(index) == 2
    assert [hit.key for hit in index.search("toner", min_score=-1.0)] == ["full"]


def test_a_text_the_embedder_gives_no_direction_matches_nothing() -> None:
    index = DenseIndex([Record("punctuation", "..."), Record("word", "toner")], FakeEmbedder())
    assert [hit.key for hit in index.search("toner", min_score=-1.0)] == ["word"]
    assert index.search("!!!", min_score=-1.0) == []


def test_any_sequence_of_numbers_is_a_vector() -> None:
    class Tuples:
        def embed(self, texts: Sequence[str]) -> tuple[tuple[int, ...], ...]:
            return tuple((1, 1) if text == "q" else (1, 0) for text in texts)

    hit = DenseIndex([Record("a", "a")], Tuples()).search("q")[0]
    assert hit == Hit("a", round(1 / math.sqrt(2), 6))


# ---- The checks on the embedder ------------------------------------------------------------------


def test_a_key_given_twice_is_refused_before_anything_is_embedded() -> None:
    spy = Spy(Silent())
    with pytest.raises(ValueError, match="'a' is given twice"):
        DenseIndex([Record("a", "one"), Record("a", "two")], spy)
    assert spy.calls == []


def test_a_reply_with_the_wrong_number_of_vectors_is_refused() -> None:
    class Short:
        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0, 0.0]]

    with pytest.raises(ValueError, match="1 vectors for 2 texts"):
        DenseIndex([Record("a", "one"), Record("b", "two")], Short())


def test_vectors_of_two_lengths_are_refused_in_one_batch_and_across_calls() -> None:
    uneven = Scripted({"one": [1.0, 0.0], "two": [1.0, 0.0, 0.0]})
    with pytest.raises(ValueError, match=r"lengths \[2, 3\]"):
        DenseIndex([Record("a", "one"), Record("b", "two")], uneven)
    index = DenseIndex([Record("a", "one")], uneven)
    with pytest.raises(ValueError, match=r"lengths \[2, 3\]"):
        index.search("two")


def test_one_bad_reply_does_not_stay_in_the_index() -> None:
    embedder = Scripted({"one": [1.0, 0.0], "bad": [1.0, 0.0, 0.0], "good": [1.0, 0.0]})
    index = DenseIndex([Record("a", "one")], embedder)
    with pytest.raises(ValueError, match=r"lengths \[2, 3\]"):
        index.search("bad")
    assert index.search("good") == [Hit("a", 1.0)]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_vector_that_is_not_finite_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="not finite"):
        DenseIndex([Record("a", "one")], Scripted({"one": [1.0, bad]}))


def test_impossible_settings_are_refused() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        DenseIndex([], Silent(), batch_size=0)
    index = scripted_index({"a": 0.5})
    with pytest.raises(ValueError, match="limit"):
        index.search("q", limit=-1)


def test_an_embedder_that_fails_is_not_hidden() -> None:
    class Down:
        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            raise ConnectionError("the endpoint is down")

    with pytest.raises(ConnectionError, match="down"):
        DenseIndex([Record("a", "one")], Down())


# ---- The light form -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "light"),
    [
        ("مُدَرَّسَة", "مدرسة"),  # diacritics go, the ta marbuta stays
        ("كـــتاب", "كتاب"),  # the tatweel goes
        ("إدارة أحمد آلة", "ادارة احمد الة"),  # alef forms become bare alef
        ("مستشفى", "مستشفى"),  # alef maqsura stays
        ("مسؤول رئيس", "مسؤول رئيس"),  # hamza on waw and on ya stays
        (f"لي{ZWNJ}زر", "ليزر"),  # a zero-width non-joiner leaves one word
        (f"{RLM}مكتب", "مكتب"),  # a direction mark goes
        ("\ufefbبد", "لابد"),  # a presentation form becomes its letters
        ("٢٠٢٦", "٢٠٢٦"),  # digits stay as written
        ("Toner  PAPER\n", "Toner PAPER"),  # case stays, white space is tidied
    ],
)
def test_the_light_form_removes_what_a_reader_does_not_see(written: str, light: str) -> None:
    assert light_form(written) == light


def test_the_light_form_of_a_light_form_is_itself() -> None:
    for record in OFFICE:
        assert light_form(light_form(record.text)) == light_form(record.text)


# ---- The filter ---------------------------------------------------------------------------------


def keys(where: Where | None) -> list[str]:
    index = DenseIndex(OFFICE, FakeEmbedder())
    return [OFFICE[place].key for place in index.positions(where)]


def test_a_named_field_must_equal_the_value() -> None:
    assert keys({"team": "furniture"}) == ["ar-chairs", "ar-desk"]
    assert keys({"team": "print", "year": 2026}) == ["ar-toner"]


def test_a_list_of_values_admits_any_of_them_and_a_string_is_one_value() -> None:
    assert keys({"team": ["furniture", "facilities"]}) == ["ar-chairs", "ar-desk", "ar-repair"]
    assert keys({"team": ("facilities",)}) == ["ar-repair"]
    assert keys({"team": {"facilities"}}) == ["ar-repair"]
    assert keys({"team": "print furniture"}) == []


def test_a_record_without_the_field_is_turned_away() -> None:
    assert "ar-repair" not in keys({"year": [2024, 2025, 2026]})
    assert keys({"year": None}) == []
    assert keys({"no such field": "anything"}) == []


def test_a_field_may_hold_something_unhashable() -> None:
    index = DenseIndex([Record("a", "one", {"tags": ["x"]})], Silent())
    assert index.positions({"tags": [["x"]]}) == [0]
    assert index.positions({"tags": ("y", "z")}) == []


def test_no_filter_and_an_empty_filter_admit_every_record() -> None:
    assert keys(None) == keys({}) == [record.key for record in OFFICE]


def test_anything_else_is_a_function_of_the_record() -> None:
    def recent(record: Record[str]) -> bool:
        return int(str(record.metadata.get("year", 0))) >= 2026

    assert keys(recent) == ["ar-toner", "ar-desk"]
    assert keys(lambda record: record.key.startswith("ar-") and "حبر" in record.text) == [
        "ar-toner"
    ]


def test_a_record_the_filter_turns_away_cannot_come_back() -> None:
    index = DenseIndex(OFFICE, FakeEmbedder())
    assert "ar-chairs" in [hit.key for hit in index.search("كراسي مكتب")]
    found = index.search("كراسي مكتب", where={"team": "print"}, min_score=-1.0)
    assert found
    assert {hit.key for hit in found} <= {"toner", "paper", "ar-toner", "ar-paper"}


def test_nothing_is_embedded_when_the_filter_admits_nothing() -> None:
    spy = Spy(FakeEmbedder())
    index = DenseIndex(OFFICE, spy)
    calls = len(spy.calls)
    assert index.search("حبر", where={"team": "nobody"}) == []
    assert index.rank(["one", "two"], []) == [[], []]
    assert len(spy.calls) == calls

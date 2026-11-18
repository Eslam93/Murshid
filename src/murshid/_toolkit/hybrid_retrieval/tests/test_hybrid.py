"""Hybrid retrieval through its public interface: the fusion order, multi-view queries, Arabic
queries, and a filter that runs before anything is scored."""

from __future__ import annotations

import random
from collections.abc import Callable

import pytest

from murshid._toolkit.hybrid_retrieval.core import (
    DenseIndex,
    FakeEmbedder,
    HybridIndex,
    Record,
    light_form,
    query_views,
)
from murshid._toolkit.hybrid_retrieval.core import hybrid as hybrid_module
from murshid._toolkit.hybrid_retrieval.tests.doubles import OFFICE, Scripted, Silent, Spy, at
from murshid._toolkit.lexical_retrieval.core import BM25Index, Document, Hit, fuse, tokenize

PERSIAN_KAF = "\u06a9"
ZWNJ = "\u200c"


def rrf(*ranks: int, k: int = 60) -> float:
    return round(sum(1 / (k + rank) for rank in ranks), 6)


# ---- The fusion order ---------------------------------------------------------------------------

# Lexical: a, b, c. Dense: b, d, a; c points away from the query.
FUSION = [
    Record("a", "toner laser printer"),
    Record("b", "toner laser"),
    Record("c", "toner"),
    Record("d", "paper"),
]
QUERY = "toner laser printer!"  # not the text of a record, so it has a vector of its own
FUSION_VECTORS = {
    "toner laser printer": at(0.7),
    "toner laser": at(0.9),
    "toner": at(-1),
    "paper": at(0.8),
    QUERY: at(1),
}


def fusion_index() -> HybridIndex[str]:
    return HybridIndex(FUSION, Scripted(FUSION_VECTORS))


def test_each_side_alone_ranks_the_fusion_case_as_its_comment_says() -> None:
    documents = (Document(record.key, record.text) for record in FUSION)
    assert [hit.key for hit in BM25Index(documents).search(QUERY)] == ["a", "b", "c"]
    dense = DenseIndex(FUSION, Scripted(FUSION_VECTORS))
    assert [hit.key for hit in dense.search(QUERY)] == ["b", "d", "a"]


def test_a_record_both_sides_found_rises_above_one_only_one_found() -> None:
    assert fusion_index().search(QUERY) == [
        Hit("b", rrf(2, 1), ("toner", "laser")),
        Hit("a", rrf(1, 3), ("toner", "laser", "printer")),
        Hit("d", rrf(2)),
        Hit("c", rrf(3), ("toner",)),
    ]


def test_a_record_only_the_dense_side_found_has_no_matched_words() -> None:
    hits = {hit.key: hit for hit in fusion_index().search(QUERY)}
    assert hits["d"].matched == ()
    assert hits["c"].matched == ("toner",)


# Lexical: top, second, third, both. Dense: one, two, three, both.
K_CASE = [
    Record("top", "alpha beta gamma delta tail"),
    Record("second", "alpha beta gamma"),
    Record("third", "alpha beta"),
    Record("both", "alpha"),
    Record("one", "one"),
    Record("two", "two"),
    Record("three", "three"),
]
K_QUERY = "alpha beta gamma delta"
K_VECTORS = {
    "alpha beta gamma delta tail": at(-1),
    "alpha beta gamma": at(-1),
    "alpha beta": at(-1),
    "alpha": at(0.6),
    "one": at(0.9),
    "two": at(0.8),
    "three": at(0.7),
    K_QUERY: at(1),
}


def test_the_fusion_constant_decides_between_one_top_rank_and_two_lower_ones() -> None:
    index = HybridIndex(K_CASE, Scripted(K_VECTORS))
    assert index.search(K_QUERY)[0] == Hit("both", rrf(4, 4), ("alpha",))
    assert index.search(K_QUERY, k=60) == index.search(K_QUERY)
    small = index.search(K_QUERY, k=1)
    assert [hit.key for hit in small[:3]] == ["top", "one", "both"]
    assert small[0].score == rrf(1, k=1)
    assert small[2].score == rrf(4, 4, k=1)


def test_the_fusion_constant_also_decides_between_the_views_of_the_lexical_side() -> None:
    """In the views solo, red and blue, solo is first once and both is fourth twice."""
    records = [
        Record("solo", "solo"),
        *(Record(f"red-{n}", "red") for n in range(3)),
        *(Record(f"blue-{n}", "blue") for n in range(3)),
        Record("both", "red blue"),
    ]
    index = HybridIndex(records, Silent())
    assert index.search("solo", rewrites=["red", "blue"])[0].key == "both"
    assert index.search("solo", rewrites=["red", "blue"], k=1)[0].key == "solo"


def test_the_fusion_constant_also_decides_between_the_views_of_the_dense_side() -> None:
    """The same case by vectors: no word of a view is in a record, so BM25 finds nothing."""
    axes = {"s": [1.0, 0.0, 0.0], "r": [0.0, 1.0, 0.0], "b": [0.0, 0.0, 1.0], "rb": [0.0, 1.0, 1.0]}
    texts = ["s", "r1", "r2", "r3", "b1", "b2", "b3", "rb"]
    vectors = {text: axes[text.rstrip("123")] for text in texts}
    vectors |= {"one": axes["s"], "two": axes["r"], "three": axes["b"]}
    index = HybridIndex([Record(text, text) for text in texts], Scripted(vectors))
    assert index.search("one", rewrites=["two", "three"])[0].key == "rb"
    assert index.search("one", rewrites=["two", "three"], k=1)[0].key == "s"


def test_a_tie_keeps_the_lexical_side_first() -> None:
    records = [Record("word", "حبر"), Record("meaning", "مداد")]
    vectors = {"حبر": at(-1), "مداد": at(1), "حبر!": at(1)}
    index = HybridIndex(records, Scripted(vectors))
    assert [(hit.key, hit.score) for hit in index.search("حبر!")] == [
        ("word", rrf(1)),
        ("meaning", rrf(1)),
    ]


def test_each_side_speaks_once_however_many_views_it_saw() -> None:
    """The light form differs from the query for the embedder and not for BM25, so the dense side
    sees two views and the lexical side one. Two votes against one would put the dense hit first."""
    records = [Record("word", "حبر اسود"), Record("meaning", "مداد")]
    written = "حِبْر"
    vectors = {"حبر اسود": at(-1), "مداد": at(1), written: at(1), "حبر": at(1)}
    spy = Spy(Scripted(vectors))
    index = HybridIndex(records, spy)
    assert [(hit.key, hit.score) for hit in index.search(written)] == [
        ("word", rrf(1)),
        ("meaning", rrf(1)),
    ]
    assert spy.calls[-1] == [written, "حبر"]


def test_the_hits_are_the_lexical_cores_hits_so_a_third_ranking_can_join() -> None:
    hybrid = fusion_index().search(QUERY)
    merged = fuse([hybrid, [Hit("elsewhere", 1.0), Hit("d", 0.5)]], limit=2)
    assert all(isinstance(hit, Hit) for hit in hybrid)
    assert "d" in [hit.key for hit in merged]


def test_the_pool_cuts_each_side_and_never_the_limit() -> None:
    """With a pool of one, b is only on the dense side and a only on the lexical one, so they tie
    and the lexical side's goes first. With the whole pool, b has both sides."""
    index = fusion_index()
    assert index.search(QUERY, limit=1)[0].key == "b"
    assert index.search(QUERY, pool=1, limit=1)[0].key == "a"
    assert [hit.key for hit in index.search(QUERY, pool=1, limit=4)] == ["b", "a", "d", "c"]


def test_each_side_looks_past_the_limit() -> None:
    """The record is fourth on each side, so it comes first only if both sides look that far."""
    index = HybridIndex(K_CASE, Scripted(K_VECTORS))
    assert index.search(K_QUERY, limit=1)[0].key == "both"


def test_a_floor_on_the_dense_side_is_what_lets_a_search_find_nothing() -> None:
    index = HybridIndex(OFFICE, FakeEmbedder())
    assert index.search("helicopter")
    assert index.search("helicopter", min_score=0.3) == []
    assert index.search("حبر الطابعة", min_score=0.3)[0].key == "ar-toner"


def test_impossible_settings_are_refused() -> None:
    index = fusion_index()
    for bad in ({"limit": -1}, {"pool": -1}, {"k": -1}):
        with pytest.raises(ValueError, match="cannot be negative"):
            index.search(QUERY, **bad)
    assert index.search(QUERY, limit=0) == []


def test_the_word_weights_reach_the_lexical_side() -> None:
    records = [Record("long", "paper " + "ink " * 8 + "paper"), Record("short", "paper")]
    loose = HybridIndex(records, Silent(), b=0.0)
    strict = HybridIndex(records, Silent(), b=1.0)
    assert [hit.key for hit in loose.search("paper")] == ["long", "short"]
    assert [hit.key for hit in strict.search("paper")] == ["short", "long"]


def test_a_query_of_stop_words_has_only_the_dense_side() -> None:
    index = HybridIndex([Record("a", "from the"), Record("b", "elsewhere")], FakeEmbedder())
    hits = index.search("from the")
    assert hits[0].key == "a"
    assert hits[0].matched == ()


def test_an_empty_index_and_a_blank_query_find_nothing_and_call_nothing() -> None:
    spy = Spy(FakeEmbedder())
    assert HybridIndex([], spy).search("toner") == []
    assert spy.calls == []
    index = HybridIndex(FUSION, spy)
    calls = len(spy.calls)
    assert index.search("   ") == []
    assert index.search("\u200f") == []
    assert len(spy.calls) == calls
    assert len(index) == 4


def test_a_key_given_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="given twice"):
        HybridIndex([Record("a", "one"), Record("a", "two")], Silent())


# ---- Multi-view queries -------------------------------------------------------------------------


def test_the_views_are_the_query_its_light_form_and_each_rewrite() -> None:
    assert query_views("حِبْر  الطابعة", rewrites=["أين الحبر؟"]) == (
        "حِبْر  الطابعة",
        "حبر الطابعة",
        "اين الحبر؟",
    )


def test_a_plain_query_is_one_view_and_repeats_and_blanks_are_dropped() -> None:
    assert query_views("toner") == ("toner",)
    assert query_views("  toner ", rewrites=["toner", "", "  ", "\u200f"]) == ("toner",)
    assert query_views("") == ()
    assert query_views("", rewrites=["toner"]) == ("toner",)


def test_a_string_given_as_rewrites_is_one_rewrite_and_not_its_letters() -> None:
    assert query_views("حبر", rewrites="طابعة ليزر") == ("حبر", "طابعة ليزر")


def test_bm25_cannot_tell_a_text_from_its_light_form() -> None:
    """Why the lexical side needs one of those two views and the dense side may use both."""
    written = [
        *(record.text for record in OFFICE),
        "حِبْر  طَابِعَة",
        f"لي{ZWNJ}زر",
        f"{PERSIAN_KAF}تاب",
        "كـــتاب",
        "إدارة مسؤول",
        "Toner  PAPER",
    ]
    for text in written:
        assert tokenize(light_form(text)) == tokenize(text), text


def test_every_view_goes_to_the_embedder_in_one_call() -> None:
    spy = Spy(FakeEmbedder())
    index = HybridIndex(OFFICE, spy)
    built = len(spy.calls)
    index.search("حِبْر", rewrites=["حبر الطابعة", "أحبار الليزر"])
    assert spy.calls[built:] == [["حِبْر", "حبر", "حبر الطابعة", "احبار الليزر"]]


def test_a_rewrite_finds_what_the_query_as_written_cannot() -> None:
    index = HybridIndex(OFFICE, Silent())
    assert index.search("فين الأحبار") == []
    assert index.search("فين الأحبار", rewrites=["حبر الطابعة"]) == [
        Hit("ar-toner", rrf(1), ("حبر", "طابعه"))
    ]


def test_a_poor_rewrite_adds_a_ranking_and_takes_none_away() -> None:
    index = HybridIndex(OFFICE, FakeEmbedder())
    plain = index.search("حبر الطابعة")
    with_poor = index.search("حبر الطابعة", rewrites=["كلام لا علاقة له"])
    assert plain[0].key == "ar-toner"
    assert with_poor[0].key == "ar-toner"
    assert with_poor[0].matched == plain[0].matched


def test_a_rewrite_that_repeats_the_query_changes_nothing() -> None:
    index = HybridIndex(OFFICE, FakeEmbedder())
    assert index.search("حبر الطابعة", rewrites=["حبر الطابعة"]) == index.search("حبر الطابعة")


def test_two_views_with_the_same_words_are_one_lexical_ranking() -> None:
    """The query as written and its light form are the same BM25 ranking. Counted twice, ink's two
    votes would tie paper's two, and ink, seen first, would stay on top."""
    index = HybridIndex([Record("ink", "حبر"), Record("paper", "ورق تصوير")], Silent())
    hits = index.search("حِبْر", rewrites=["ورق", "تصوير"])
    assert [hit.key for hit in hits] == ["paper", "ink"]


def test_the_matched_words_of_every_view_are_merged() -> None:
    index = HybridIndex(OFFICE, Silent())
    assert index.search("حبر", rewrites=["طابعة ليزر"])[0] == Hit(
        "ar-toner", rrf(1), ("حبر", "طابعه", "ليزر")
    )


def test_a_prefix_reaches_every_view_and_not_the_lexical_side() -> None:
    spy = Spy(FakeEmbedder())
    index = HybridIndex(OFFICE, spy, document_prefix="passage: ", query_prefix="query: ")
    assert all(text.startswith("passage: ") for text in spy.calls[0])
    hits = index.search("حِبْر الطابعة")
    assert spy.calls[-1] == ["query: حِبْر الطابعة", "query: حبر الطابعة"]
    assert hits[0].matched == ("حبر", "طابعه")
    assert "query" not in hits[0].matched


# ---- Arabic queries -----------------------------------------------------------------------------


def test_an_arabic_query_finds_its_record_on_both_sides() -> None:
    assert HybridIndex(OFFICE, FakeEmbedder()).search("حبر الطابعة")[0] == Hit(
        "ar-toner", rrf(1, 1), ("حبر", "طابعه")
    )


def test_the_dense_side_finds_a_word_the_light_stemming_cannot() -> None:
    documents = (Document(record.key, record.text) for record in OFFICE)
    assert BM25Index(documents).search("كرسي") == []
    hit = HybridIndex(OFFICE, FakeEmbedder()).search("كرسي")[0]
    assert (hit.key, hit.matched) == ("ar-chairs", ())


@pytest.mark.parametrize(
    ("query", "expected", "matched"),
    [
        ("ادارة الصيانة", "ar-repair", ("اداره", "صيانه")),  # no hamza, a different ending
        ("حِبْر طَابِعَة", "ar-toner", ("حبر", "طابعه")),  # with diacritics
        ("حبـــر", "ar-toner", ("حبر",)),  # with the tatweel
        (f"م{PERSIAN_KAF}تب خشبي", "ar-desk", ("مكتب", "خشبي")),  # the Persian kaf
        (f"لي{ZWNJ}زر", "ar-toner", ("ليزر",)),  # a zero-width non-joiner inside the word
        (
            "ورق 80 جرام",
            "ar-paper",
            ("ورق", "80", "جرام"),
        ),  # Western digits, Arabic-Indic in the text
        ("A4 paper ٨٠", "paper", ("a4", "paper", "80")),  # the other way round
    ],
)
def test_a_differently_written_query_still_reaches_its_record(
    query: str, expected: str, matched: tuple[str, ...]
) -> None:
    hit = HybridIndex(OFFICE, FakeEmbedder()).search(query)[0]
    assert (hit.key, hit.matched) == (expected, matched)


def test_arabic_and_filter_together() -> None:
    index = HybridIndex(OFFICE, FakeEmbedder())
    hits = index.search("مكتب", where={"team": "furniture"})
    assert {hit.key for hit in hits} == {"ar-chairs", "ar-desk"}
    assert all(hit.matched == ("مكتب",) for hit in hits)


# ---- The filter runs before anything is scored ---------------------------------------------------

# Alone, team a holds alpha once and beta twice, so alpha is the rare word. Beside team b, which
# says alpha nine times, beta is. A filter that ran after the scoring would show that.
TEAM_A = [
    Record("a1", "alpha", {"team": "a"}),
    Record("a2", "beta", {"team": "a"}),
    Record("a3", "beta", {"team": "a"}),
]
TEAM_B = [Record(f"b{n}", "alpha", {"team": "b"}) for n in range(9)]


def test_a_search_then_a_filter_would_rank_this_case_the_other_way() -> None:
    documents = (Document(record.key, record.text) for record in TEAM_A + TEAM_B)
    afterwards = [hit.key for hit in BM25Index(documents).search("alpha beta", limit=20)]
    assert [key for key in afterwards if key.startswith("a")] == ["a2", "a3", "a1"]


def test_the_word_weights_come_from_the_admitted_records_alone() -> None:
    index = HybridIndex(TEAM_A + TEAM_B, Silent())
    hits = index.search("alpha beta", where={"team": "a"})
    assert [hit.key for hit in hits] == ["a1", "a2", "a3"]


def test_a_filter_matches_an_index_of_the_admitted_records_on_seeded_random_corpora() -> None:
    rng = random.Random(20261030)  # noqa: S311 - made-up text, not a secret
    words = ["toner", "laser", "paper", "chairs", "حبر", "طابعة", "ورق", "كراسي", "مكتب", "صيانة"]
    embedder = FakeEmbedder(dimensions=64)
    for _ in range(60):
        records = [
            Record(
                n, " ".join(rng.choices(words, k=rng.randint(1, 6))), {"team": rng.choice("abc")}
            )
            for n in range(rng.randint(1, 24))
        ]
        team = rng.choice("abc")
        query = " ".join(rng.choices(words, k=2))
        admitted = [record for record in records if record.metadata["team"] == team]
        filtered = HybridIndex(records, embedder).search(query, where={"team": team})
        assert filtered == HybridIndex(admitted, embedder).search(query), (query, team)


def test_a_record_the_filter_turns_away_never_comes_back_from_either_side() -> None:
    index = HybridIndex(OFFICE, FakeEmbedder())
    hits = index.search("Toner cartridge for laser printer", where={"team": "furniture"})
    assert {hit.key for hit in hits} <= {"ar-chairs", "ar-desk"}


def test_a_filter_that_admits_nothing_calls_nothing() -> None:
    spy = Spy(FakeEmbedder())
    index = HybridIndex(OFFICE, spy)
    calls = len(spy.calls)
    assert index.search("حبر", where={"team": "nobody"}) == []
    assert index.search("حبر", where=lambda record: False) == []
    assert len(spy.calls) == calls


def counted_builds(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts the BM25 indexes built from here on, by size."""
    built: list[int] = []
    real: Callable[..., BM25Index[str]] = BM25Index

    def counting(documents, **kwargs):  # type: ignore[no-untyped-def]
        kept = list(documents)
        built.append(len(kept))
        return real(kept, **kwargs)

    monkeypatch.setattr(hybrid_module, "BM25Index", counting)
    return built


def test_a_filter_seen_before_does_not_build_again(monkeypatch: pytest.MonkeyPatch) -> None:
    built = counted_builds(monkeypatch)
    index = HybridIndex(OFFICE, Silent())
    assert built == [7]
    index.search("حبر", where={"team": "print"})
    index.search("ورق", where={"team": "print"})
    index.search("ورق", where=lambda record: record.metadata["team"] == "print")
    assert built == [7, 4]


def test_a_filter_that_admits_everything_uses_the_whole_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = counted_builds(monkeypatch)
    index = HybridIndex(OFFICE, Silent())
    index.search("حبر", where={})
    index.search("حبر", where=lambda record: True)
    assert built == [7]


def test_only_the_last_filters_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    built = counted_builds(monkeypatch)
    index = HybridIndex(OFFICE, Silent(), subsets_kept=1)
    index.search("حبر", where={"team": "print"})
    index.search("حبر", where={"team": "furniture"})
    index.search("حبر", where={"team": "print"})
    assert built == [7, 4, 2, 4]

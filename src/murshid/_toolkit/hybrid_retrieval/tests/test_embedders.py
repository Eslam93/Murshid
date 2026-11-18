"""The embedder seam: the fake's determinism, and the cache in front of an embedder."""

from __future__ import annotations

import json
import math
from collections import UserDict
from collections.abc import Sequence

import pytest

from murshid._toolkit.hybrid_retrieval.core import CachedEmbedder, FakeEmbedder
from murshid._toolkit.hybrid_retrieval.tests.doubles import Spy


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    norm = math.sqrt(math.sumprod(left, left)) * math.sqrt(math.sumprod(right, right))
    return math.sumprod(left, right) / norm


# ---- The fake ------------------------------------------------------------------------------------


def test_the_fake_gives_one_vector_per_text_in_order() -> None:
    fake = FakeEmbedder(dimensions=16)
    vectors = fake.embed(["toner", "paper", "حبر"])
    assert [len(vector) for vector in vectors] == [16, 16, 16]
    assert vectors == [fake.embed([text])[0] for text in ("toner", "paper", "حبر")]
    assert fake.embed([]) == []


def test_the_fake_gives_the_same_vector_in_every_process() -> None:
    """Pinned: `hash()` is seeded per process, so an embedder built on it fails here at once."""
    fake = FakeEmbedder(dimensions=8)
    assert fake.embed(["toner"]) == [[0.0, 1.0, 0.0, -3.0, 0.0, 2.0, 0.0, 3.0]]
    assert fake.embed(["حبر"]) == [[0.0, -3.0, -1.0, -1.0, 0.0, 0.0, -1.0, -1.0]]


def test_close_spellings_are_close_and_other_words_are_not() -> None:
    fake = FakeEmbedder()
    chair, chairs, printer = fake.embed(["كرسي", "كراسي", "طابعة"])
    assert cosine(chair, chairs) > 0.5
    assert abs(cosine(chair, printer)) < 0.2


def test_case_changes_nothing_and_a_text_with_no_word_has_no_direction() -> None:
    fake = FakeEmbedder(dimensions=32)
    assert fake.embed(["Laser PRINTER"]) == fake.embed(["laser printer"])
    assert fake.embed(["... !!"]) == [[0.0] * 32]


# ---- The cache -----------------------------------------------------------------------------------


def test_the_cache_asks_only_for_what_it_does_not_hold() -> None:
    spy = Spy(FakeEmbedder(dimensions=8))
    store: dict[str, Sequence[float]] = {}
    cached = CachedEmbedder(spy, store)
    first = cached.embed(["toner", "paper"])
    second = cached.embed(["paper", "toner", "حبر"])
    assert spy.calls == [["toner", "paper"], ["حبر"]]
    assert first == FakeEmbedder(dimensions=8).embed(["toner", "paper"])
    assert second == FakeEmbedder(dimensions=8).embed(["paper", "toner", "حبر"])
    assert set(store) == {"toner", "paper", "حبر"}


def test_the_cache_asks_once_for_a_repeated_text_and_never_for_what_it_holds() -> None:
    spy = Spy(FakeEmbedder(dimensions=8))
    cached = CachedEmbedder(spy, {})
    assert cached.embed(["paper", "paper"]) == FakeEmbedder(dimensions=8).embed(["paper"]) * 2
    cached.embed(["paper"])
    cached.embed([])
    assert spy.calls == [["paper"]]


def test_a_changed_text_misses_by_itself() -> None:
    spy = Spy(FakeEmbedder(dimensions=8))
    cached = CachedEmbedder(spy, {})
    cached.embed(["paper, 80 gsm"])
    cached.embed(["paper, 90 gsm"])
    assert spy.calls == [["paper, 80 gsm"], ["paper, 90 gsm"]]


def test_a_store_with_a_size_limit_cannot_lose_what_a_call_still_needs() -> None:
    class NewestTwo(UserDict[str, Sequence[float]]):
        def __setitem__(self, text: str, vector: Sequence[float]) -> None:
            super().__setitem__(text, vector)
            while len(self.data) > 2:
                del self.data[next(iter(self.data))]

    fake = FakeEmbedder(dimensions=8)
    store = NewestTwo()
    texts = ["one", "two", "three", "four"]
    assert CachedEmbedder(fake, store).embed(texts) == fake.embed(texts)
    assert sorted(store) == ["four", "three"]


def test_a_reply_of_the_wrong_length_stores_nothing() -> None:
    class Short:
        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0]]

    store: dict[str, Sequence[float]] = {}
    with pytest.raises(ValueError, match="shorter"):
        CachedEmbedder(Short(), store).embed(["one", "two"])
    assert store == {}


def test_the_store_can_outlive_the_process_as_json() -> None:
    fake = FakeEmbedder(dimensions=8)
    store: dict[str, Sequence[float]] = {}
    before = CachedEmbedder(fake, store).embed(["حبر طابعة"])
    spy = Spy(fake)
    after = CachedEmbedder(spy, json.loads(json.dumps(store, ensure_ascii=False))).embed(
        ["حبر طابعة"]
    )
    assert after == before
    assert spy.calls == []

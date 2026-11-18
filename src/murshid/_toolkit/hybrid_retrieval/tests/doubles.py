"""Embedders written by hand, and a small made-up catalogue of office supplies."""

from __future__ import annotations

import math
from collections.abc import Sequence

from murshid._toolkit.hybrid_retrieval.core import Embedder, Record

OFFICE = [
    Record("toner", "Toner cartridge for laser printer", {"team": "print", "year": 2025}),
    Record("paper", "A4 copy paper, 80 gsm", {"team": "print", "year": 2024}),
    Record("ar-toner", "حبر طابعة ليزر أسود", {"team": "print", "year": 2026}),
    Record("ar-paper", "ورق تصوير ٨٠ جرام", {"team": "print", "year": 2024}),
    Record("ar-chairs", "كراسي مكتب بمسند للظهر", {"team": "furniture", "year": 2025}),
    Record("ar-desk", "مكتب خشبي بأدراج", {"team": "furniture", "year": 2026}),
    Record("ar-repair", "إدارة صيانة المكاتب", {"team": "facilities"}),
]


def at(cosine: float) -> list[float]:
    """A unit vector at this cosine to the query vector `at(1)`."""
    return [cosine, math.sqrt(1 - cosine**2)]


class Scripted:
    """Gives each text the vector written for it. A text with none written is a test's mistake."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.vectors[text] for text in texts]


class Silent:
    """Finds nothing: a vector of no length matches no record, so a search shows the lexical side
    alone."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0, 0.0] for _ in texts]


class Spy:
    """Keeps every call that reaches the embedder behind it."""

    def __init__(self, inner: Embedder) -> None:
        self.inner = inner
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls.append(list(texts))
        return self.inner.embed(texts)

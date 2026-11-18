"""A dense index over your own records, with a metadata filter applied before scoring.

Each record is embedded once, when the index is built, and its vector scaled to unit length, so a
dot product is a cosine. A search embeds the query and scans the records in memory. Everything
crossing the `Embedder` seam is checked, because a mistake there is otherwise silent: a reply of
the wrong length pairs vectors with the wrong keys, vectors of two lengths come from two models,
and one NaN leaves a ranking in no order at all.

`where` picks the records that take part. It runs before anything is scored, so a record it turns
away is never looked at. A named field must equal the value, or be one of the values given as a
list, tuple or set; a record without the field is turned away, so a host's tenant filter stays
closed for a record that forgot its tenant. Anything else is a function of the record.

Records reach the embedder in their `light_form`, and so does a query given to `search`, so the two
meet in the same spelling. `rank` sends the views it is given as they are.
"""

from __future__ import annotations

import math
import unicodedata
from array import array
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from ...lexical_retrieval.core import Hit
from ...quote_matching.core import ARABIC, LATIN, CharRule, Rule, fold_text
from .embedders import Embedder

__all__ = ["DenseIndex", "Record", "Where", "light_form"]

K = TypeVar("K", bound=Hashable)

# From W03: what a reader does not see. The rest of W03's letters rule stays out (see `light_form`),
# and `arabic_letters` is one rule, so the alef forms come back as a rule of this core.
_UNSEEN = frozenset(
    {"latin_zero_width", "latin_whitespace", "arabic_direction_marks", "arabic_marks"}
)
_ALEF_FORMS = frozenset("آأإٱ")
_LIGHT: tuple[Rule, ...] = (
    *(rule for rule in (*LATIN, *ARABIC) if rule.name in _UNSEEN),
    CharRule("hybrid_bare_alef", lambda char: "ا" if char in _ALEF_FORMS else char),
)
_ABSENT = object()


def light_form(text: str) -> str:
    """The text as an embedder reads it: NFKC over the whole text, zero-width characters, direction
    marks, diacritics and the tatweel removed, alef forms made bare, white space tidied.

    Lighter than C56's `normalize` on purpose. That one is made for comparing words; this one
    leaves ta marbuta, alef maqsura, hamza on waw and ya, case and digits as written, because an
    embedding model learned from text that keeps them, and folding them away moves a text from
    what its tokenizer knows.
    """
    return fold_text(unicodedata.normalize("NFKC", text), _LIGHT).strip()


@dataclass(frozen=True)
class Record(Generic[K]):
    key: K
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


Where = Mapping[str, object] | Callable[[Record[Any]], bool]


def _admits(where: Where | None, record: Record[Any]) -> bool:
    if where is None:
        return True
    if callable(where):
        return bool(where(record))
    for name, wanted in where.items():
        value = record.metadata.get(name, _ABSENT)  # equal to nothing, so a missing field fails
        allowed = wanted if isinstance(wanted, list | tuple | set | frozenset) else (wanted,)
        if not any(value == one for one in allowed):
            return False
    return True


def _unit(vector: Sequence[float]) -> list[float]:
    """`vector` scaled to length one; empty for a vector of no length, which can match nothing."""
    norm = math.sqrt(math.sumprod(vector, vector))
    if not math.isfinite(norm):
        raise ValueError("the embedder returned a vector that is not finite")
    return [value / norm for value in vector] if norm else []


class DenseIndex(Generic[K]):
    def __init__(
        self,
        records: Iterable[Record[K]],
        embedder: Embedder,
        *,
        batch_size: int = 32,
        document_prefix: str = "",
        query_prefix: str = "",
    ) -> None:
        if batch_size < 1:
            raise ValueError(f"batch_size must be at least 1, not {batch_size}")
        self._records = list(records)
        seen: set[K] = set()
        for record in self._records:
            if record.key in seen:
                raise ValueError(f"the key {record.key!r} is given twice")
            seen.add(record.key)
        self._embedder = embedder
        self._query_prefix = query_prefix
        self._lengths: set[int] = set()
        # 8 bytes a number against about 32 in a list of floats, for about a quarter more time.
        self._vectors: list[array[float]] = [array("d") for _ in self._records]
        texts = [light_form(record.text) for record in self._records]
        filled = [place for place, text in enumerate(texts) if text]  # a blank text matches nothing
        for start in range(0, len(filled), batch_size):
            batch = filled[start : start + batch_size]
            vectors = self._embed([document_prefix + texts[place] for place in batch])
            for place, vector in zip(batch, vectors, strict=True):
                self._vectors[place] = array("d", vector)

    def __len__(self) -> int:
        return len(self._records)

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._embedder.embed(texts)
        if len(vectors) != len(texts):
            raise ValueError(f"the embedder returned {len(vectors)} vectors for {len(texts)} texts")
        lengths = self._lengths | {len(vector) for vector in vectors}
        if len(lengths) > 1:
            raise ValueError(f"the embedder returned vectors of lengths {sorted(lengths)}")
        self._lengths = lengths  # kept only once accepted: one bad reply must not stay in the index
        return [_unit(vector) for vector in vectors]

    def positions(self, where: Where | None = None) -> list[int]:
        """The places of the records `where` admits, in the order the records were given."""
        return [place for place, record in enumerate(self._records) if _admits(where, record)]

    def rank(
        self,
        views: Sequence[str],
        positions: Sequence[int],
        *,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[list[Hit[K]]]:
        """One ranking per view over the records at `positions` and no others. Every view is
        embedded in one call, and no call is made when no record can match."""
        if limit < 0:
            raise ValueError(f"limit cannot be negative, not {limit}")
        if not views or not positions:
            return [[] for _ in views]
        vectors = self._embed([self._query_prefix + view for view in views])
        return [self._nearest(vector, positions, limit, min_score) for vector in vectors]

    def _nearest(
        self, query: list[float], positions: Sequence[int], limit: int, min_score: float
    ) -> list[Hit[K]]:
        if not query:
            return []
        scored: list[tuple[float, int]] = []
        for place in positions:
            vector = self._vectors[place]
            if vector:
                score = math.sumprod(query, vector)
                if score > min_score:
                    scored.append((score, place))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [Hit(self._records[place].key, round(score, 6)) for score, place in scored[:limit]]

    def search(
        self, query: str, *, where: Where | None = None, limit: int = 10, min_score: float = 0.0
    ) -> list[Hit[K]]:
        """The best `limit` records with a cosine above `min_score`, best first; ties keep the
        order the records were given in."""
        view = light_form(query)
        if not view:
            return []
        return self.rank((view,), self.positions(where), limit=limit, min_score=min_score)[0]

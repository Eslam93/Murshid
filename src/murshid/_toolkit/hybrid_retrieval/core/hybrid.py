"""Hybrid retrieval: BM25 (C56) and a dense index, fused by reciprocal rank over one set of records.

A search has four steps.

1. The filter. `where` picks the records that take part, before anything is scored. BM25 is built
   over those records alone, so its word statistics come from them, and a filtered search returns
   exactly what an index of those records alone would return. Searching everything and dropping
   hits afterwards would not: a record the person may not open would still weigh on every score.
2. The views. `query_views` gives the distinct texts the query is searched by: as written, in its
   light form, and any rewrite the host supplies, such as a model's plain version of a dialect
   question. The query as written always stays, so a poor rewrite adds a ranking and takes none
   away. The core calls no model.
3. The two sides. Each side ranks every view and fuses its own rankings. Two views with the same
   terms are the same BM25 ranking, so the lexical side keeps one of them. Without that, the light
   form, which BM25 folds away, would count the lexical ranking twice.
4. The fusion. C56's `fuse` merges the lexical ranking and the dense ranking through `Hit`. Each
   side speaks once however many views it saw, so adding a view changes how a side ranks and not
   how much it counts. Only ranks reach the fusion: a BM25 score and a cosine never meet.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Sequence
from functools import lru_cache
from typing import Generic, TypeVar

from ...lexical_retrieval.core import BM25Index, Document, Hit, fuse, tokenize
from .dense import DenseIndex, Record, Where, light_form
from .embedders import Embedder

__all__ = ["HybridIndex", "query_views"]

K = TypeVar("K", bound=Hashable)


def query_views(query: str, *, rewrites: Iterable[str] = ()) -> tuple[str, ...]:
    """The distinct texts a query is searched by: as written, in its light form, then each rewrite
    in its light form. Blank texts and repeats are dropped. A text of direction marks alone is
    blank: `str.strip` keeps them, and an endpoint would refuse the empty text behind them. A
    string given as `rewrites` is one rewrite, not a list of its letters."""
    light = light_form(query)
    others = (rewrites,) if isinstance(rewrites, str) else rewrites
    views = (query.strip() if light else "", light, *map(light_form, others))
    return tuple(dict.fromkeys(view for view in views if view))


def _distinct_terms(views: Iterable[str]) -> list[str]:
    """One view per set of BM25 terms, since a ranking depends on that set alone."""
    by_terms: dict[frozenset[str], str] = {}
    for view in views:
        by_terms.setdefault(frozenset(tokenize(view)), view)
    return list(by_terms.values())


class HybridIndex(Generic[K]):
    def __init__(
        self,
        records: Iterable[Record[K]],
        embedder: Embedder,
        *,
        batch_size: int = 32,
        document_prefix: str = "",
        query_prefix: str = "",
        k1: float = 1.2,
        b: float = 0.75,
        subsets_kept: int = 16,
    ) -> None:
        self._records = list(records)
        self._dense: DenseIndex[K] = DenseIndex(
            self._records,
            embedder,
            batch_size=batch_size,
            document_prefix=document_prefix,
            query_prefix=query_prefix,
        )
        self._k1, self._b = k1, b
        self._whole = self._lexical(range(len(self._records)))
        self._subset = lru_cache(maxsize=subsets_kept)(self._lexical)

    def __len__(self) -> int:
        return len(self._records)

    def _lexical(self, positions: Sequence[int]) -> BM25Index[K]:
        chosen = (self._records[place] for place in positions)
        documents = (Document(record.key, record.text) for record in chosen)
        return BM25Index(documents, k1=self._k1, b=self._b)

    def search(
        self,
        query: str,
        *,
        rewrites: Iterable[str] = (),
        where: Where | None = None,
        limit: int = 10,
        pool: int = 50,
        k: int = 60,
        min_score: float = 0.0,
    ) -> list[Hit[K]]:
        """The best `limit` records, best first; ties keep the lexical side's order, then the dense
        side's.

        `pool` is how many records each side brings from each view; a record below that gets
        nothing from that side. `k` is the fusion constant: smaller lets the top ranks count for
        more. `min_score` is the cosine the dense side must pass. `matched` holds the lexical
        terms, so a record only the dense side found has none.
        """
        if limit < 0 or pool < 0 or k < 0:
            raise ValueError(f"limit, pool and k cannot be negative: {limit}, {pool}, {k}")
        pool = max(pool, limit)
        views = query_views(query, rewrites=rewrites)
        positions = self._dense.positions(where)
        if not views or not positions:
            return []
        whole = len(positions) == len(self._records)
        lexical = self._whole if whole else self._subset(tuple(positions))
        lexical_rankings = [lexical.search(view, limit=pool) for view in _distinct_terms(views)]
        dense_rankings = self._dense.rank(views, positions, limit=pool, min_score=min_score)
        sides = [
            fuse(lexical_rankings, k=k, limit=pool),
            fuse(dense_rankings, k=k, limit=pool),
        ]
        return fuse(sides, k=k, limit=limit)

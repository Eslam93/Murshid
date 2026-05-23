"""Retrieval (§0.3) — Phase 2 multi-view hybrid.

Multi-view: every query produces three views (raw + light-normalized +
MSA-rewrite). Each view scores via dense (BGE-M3) AND BM25; per-view rankings
are combined with Reciprocal Rank Fusion (RRF). The dense and BM25 RRF scores
are summed to produce the hybrid score.

Service-category filter from `router.py` is applied BEFORE scoring — only
chunks whose `service_category` matches participate in retrieval (or all
chunks if no filter is specified).

Every result carries the citation contract:
    {source_id, service_category, service_title, chunk_id, passage_text, score}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from murshid.ingest import Chunk, Index, get_embedder
from murshid.normalize import fold_arabic_indic_digits, light_normalize


def _bm25_normalize(text: str) -> str:
    """Normalization applied to BOTH the BM25 indexing input and the BM25 query.

    `light_normalize` + Arabic-Indic digit folding. The digit fold (Phase 8
    creative add-on) makes the lexical-match layer numeric-script-agnostic so
    a query in Arabic-Indic digits (`١٠ رمضان ١٤٤٧هـ`) hits the Western-digit
    indexed corpus. Applied here rather than in `light_normalize` itself to
    preserve the kickoff §0.2 spec for the general normalizer.
    """
    return fold_arabic_indic_digits(light_normalize(text))


@dataclass
class RetrievalResult:
    """Per-result citation contract (§0.3)."""

    source_id: str
    service_category: str
    service_title: str
    chunk_id: str
    passage_text: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# BM25 helper — wrapped so retrieve() can take None for dense-only
# ---------------------------------------------------------------------------

class BM25Index:
    """Light wrapper around rank_bm25 for parity with the dense index."""

    def __init__(self, chunks: list[Chunk]):
        from rank_bm25 import BM25Okapi  # noqa: PLC0415

        self._tokens_per_chunk: list[list[str]] = [
            _bm25_normalize(c.embedding_input or c.passage_text).split() for c in chunks
        ]
        self._bm25 = BM25Okapi(self._tokens_per_chunk)

    def get_scores(self, query_tokens: list[str]) -> np.ndarray:
        return np.asarray(self._bm25.get_scores(query_tokens), dtype=np.float32)


def build_bm25_index(index: Index) -> BM25Index:
    """Build a BM25 index over the same chunks as the dense index."""
    return BM25Index(index.chunks)


# ---------------------------------------------------------------------------
# RRF helper
# ---------------------------------------------------------------------------

# Reciprocal Rank Fusion constant. K=60 is the value used in the original
# Cormack et al. 2009 RRF paper ("Reciprocal rank fusion outperforms condorcet
# and individual rank learning methods"). It's the de-facto default in the
# LlamaIndex / Pyserini / LangChain RRF implementations we sampled. Smaller K
# would weight top ranks more aggressively; we have no data here to justify a
# departure from the literature default.
_RRF_K = 60


def _rrf_from_scores(scores: np.ndarray) -> np.ndarray:
    """Convert a (n_views, n_candidates) score matrix into per-candidate RRF.

    Each row is a view; ranking is by descending score within the row.
    """
    n_candidates = scores.shape[1]
    rrf = np.zeros(n_candidates, dtype=np.float32)
    for view_scores in scores:
        ranked = np.argsort(-view_scores)
        for rank, cand_idx in enumerate(ranked, start=1):
            rrf[cand_idx] += 1.0 / (_RRF_K + rank)
    return rrf


# ---------------------------------------------------------------------------
# retrieve — multi-view + hybrid + filter
# ---------------------------------------------------------------------------

def retrieve(
    query: str,
    index: Index,
    *,
    rewritten_query: str | None = None,
    service_category: str | None = None,
    top_k: int = 5,
    bm25_index: BM25Index | None = None,
    embedder_model: str = "BAAI/bge-m3",
) -> list[RetrievalResult]:
    """Multi-view hybrid retrieval with optional service-category filter.

    Views: raw, light-normalized, optional MSA-rewrite (3 total).
    Scoring: dense (BGE-M3 cosine) + BM25 (optional), each contributing a
    Reciprocal Rank Fusion score; the two RRF scores are summed.

    Args:
        query: original user query.
        index: dense index (built by `ingest.build_index`).
        rewritten_query: MSA rewrite (None to skip the third view).
        service_category: filter chunks to this category; None means unfiltered.
        top_k: number of results to return.
        bm25_index: optional BM25Index for hybrid retrieval.
        embedder_model: sentence-transformers model name (default BGE-M3).

    Returns:
        list[RetrievalResult], top_k items sorted by combined score.
    """
    if not index.chunks:
        return []

    # 1. Filter candidate set by service_category.
    if service_category:
        candidate_indices = [
            i for i, c in enumerate(index.chunks)
            if c.service_category == service_category
        ]
    else:
        candidate_indices = list(range(len(index.chunks)))

    if not candidate_indices:
        return []

    # 2. Build query views, deduping identical strings. When light_normalize
    # is the identity (e.g., the query is already normalized), avoid counting
    # the same ranking twice in RRF — that would overweight in-modality
    # agreement and make score magnitudes misleading.
    seen_views: set[str] = set()
    views: list[str] = []
    for v in (query, light_normalize(query), (rewritten_query or "")):
        v_stripped = v.strip()
        if v_stripped and v_stripped not in seen_views:
            seen_views.add(v_stripped)
            views.append(v)
    if not views:
        # Defensive: should not happen since `query` is the seed, but be safe.
        views = [query]

    # 3. Dense retrieval per view.
    embedder = get_embedder(embedder_model)
    query_vecs = embedder.encode(views, normalize_embeddings=True, show_progress_bar=False)
    query_vecs = np.asarray(query_vecs, dtype=np.float32)
    filtered_embeddings = index.embeddings[candidate_indices]
    dense_scores = query_vecs @ filtered_embeddings.T  # (n_views, n_candidates)
    dense_rrf = _rrf_from_scores(dense_scores)

    # 4. BM25 retrieval per view (optional).
    # `_bm25_normalize` applies light_normalize + Arabic-Indic digit folding
    # so a query in Arabic-Indic digits (`١٠ رمضان ١٤٤٧هـ`) hits the indexed
    # text after the same digit fold. Dense retrieval uses the unfolded view
    # because BGE-M3 is multilingual and tokenizes Arabic-Indic natively.
    if bm25_index is not None:
        bm25_scores_list = []
        for view in views:
            tokens = _bm25_normalize(view).split()
            full_scores = bm25_index.get_scores(tokens)
            bm25_scores_list.append(full_scores[candidate_indices])
        bm25_scores = np.vstack(bm25_scores_list)  # (n_views, n_candidates)
        bm25_rrf = _rrf_from_scores(bm25_scores)
        combined = dense_rrf + bm25_rrf
    else:
        combined = dense_rrf

    # 5. Top-k.
    k = min(top_k, len(combined))
    if k == 0:
        return []
    top_unordered = np.argpartition(-combined, k - 1)[:k]
    top_local = top_unordered[np.argsort(-combined[top_unordered])]

    return [
        RetrievalResult(
            source_id=index.chunks[candidate_indices[i]].source_id,
            service_category=index.chunks[candidate_indices[i]].service_category,
            service_title=index.chunks[candidate_indices[i]].service_title,
            chunk_id=index.chunks[candidate_indices[i]].chunk_id,
            passage_text=index.chunks[candidate_indices[i]].passage_text,
            score=float(combined[i]),
        )
        for i in top_local
    ]

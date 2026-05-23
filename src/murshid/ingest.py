"""Ingestion: chunk -> enrich -> embed -> index (§0.3, Phase 1 task 9).

Phase 1 implementation:
  - Deterministic chunking: FAQ detect by `س:` markers; else paragraph split.
  - Ordinal numbering: `source_id:chunk-N` (debug-only per §0.6 — recall and
    citation matching is content-based, not chunk-id-based).
  - Chunk metadata enrichment (§0.3, external RAG-architecture learning):
    per-chunk LLM call produces `summary` + `keywords`; both concatenated
    into BM25-indexed text and the embedder input. `passage_text` stays
    verbatim so citation accuracy anchors on the source quote.
  - Embedding via BGE-M3 (sentence-transformers, lazy-loaded).
  - Index = (numpy ndarray, list[Chunk]).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from murshid.normalize import light_normalize
from murshid.providers.base import LLMProvider


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """A retrievable unit. Persisted in the in-memory index.

    `passage_text` is the verbatim source substring — never mutated by
    enrichment. `summary` and `keywords` are concatenated into the
    EMBEDDING / BM25 input (`embedding_input`), not into `passage_text`.

    `enrichment_status` records the outcome of the metadata enrichment LLM
    call: "ok" | "failed_json" | "failed_provider" | "skipped". Phase 3 audits
    use this to identify chunks that lost enrichment surface so they can be
    retried or downgraded explicitly.
    """

    source_id: str
    service_category: str
    service_title: str
    chunk_id: str
    passage_text: str
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    embedding_input: str = ""
    enrichment_status: str = "skipped"


@dataclass
class Index:
    """In-memory index. Embeddings are L2-normalized so dot product == cosine."""

    chunks: list[Chunk]
    embeddings: np.ndarray  # shape (N, D), L2-normalized

    def __len__(self) -> int:
        return len(self.chunks)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

FAQ_MARKER = "س:"


def is_faq_format(text: str) -> bool:
    """A source is FAQ-style if it contains the Arabic question marker `س:`."""
    return FAQ_MARKER in text


def chunk_faq(text: str) -> list[str]:
    """Split FAQ-style text by Q&A pair.

    Each chunk after the first contains the `س:`-prefixed question plus its
    `ج:` answer. The first piece (before any `س:`) is kept as an intro chunk
    only if non-trivial.
    """
    parts = text.split(FAQ_MARKER)
    chunks: list[str] = []
    intro = parts[0].strip()
    if intro:
        chunks.append(intro)
    for part in parts[1:]:
        chunk = (FAQ_MARKER + part).strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def chunk_paragraphs(text: str) -> list[str]:
    """Split continuous prose by blank-line paragraphs."""
    parts = [p.strip() for p in text.split("\n\n")]
    return [p for p in parts if p]


def chunk_source(source: dict) -> list[Chunk]:
    """Deterministic chunker. FAQ detection by `س:`, else paragraph split."""
    text = source["content"]
    raw_chunks = chunk_faq(text) if is_faq_format(text) else chunk_paragraphs(text)
    return [
        Chunk(
            source_id=source["source_id"],
            service_category=source["service_category"],
            service_title=source["service_title"],
            chunk_id=f"{source['source_id']}:chunk-{i + 1}",
            passage_text=chunk_text,
        )
        for i, chunk_text in enumerate(raw_chunks)
    ]


def chunk_all_sources(sources: list[dict]) -> list[Chunk]:
    """Apply `chunk_source` to every source and flatten."""
    return [c for s in sources for c in chunk_source(s)]


# ---------------------------------------------------------------------------
# Metadata enrichment (§0.3 — external RAG-architecture learning)
# ---------------------------------------------------------------------------

ENRICHMENT_PROMPT_AR = """[ROLE: enrichment]
أنت مساعد لتحضير فهرس استرجاع لوثائق حكومية سعودية.
لكل مقطع نصي، أعطني:
1) ملخص: جملة عربية واحدة (لا تتجاوز 25 كلمة) تصف موضوع المقطع.
2) كلمات مفتاحية: قائمة من 5 إلى 10 كلمات/مصطلحات تمثل المقطع، يمكن أن تتضمن مصطلحات إنجليزية تشغيلية (مثل OTP، IBAN).

أعد الإجابة بصيغة JSON فقط:
{"summary": "...", "keywords": ["...", "..."]}

المقطع:
"""


def enrich_chunk_metadata(chunk: Chunk, provider: LLMProvider) -> Chunk:
    """Populate `chunk.summary` and `chunk.keywords` via one LLM call.

    Best-effort. ANY failure (JSON decode, provider exception, network error,
    rate limit) is captured into `chunk.enrichment_status` and the chunk ships
    with empty enrichment fields. Citation accuracy and recall are independent
    of enrichment success — losing enrichment only loses retrieval-surface
    boost, not correctness.

    Status values:
      - `"ok"`: enrichment populated `summary` + `keywords` successfully.
      - `"failed_json"`: provider returned non-JSON or missing keys.
      - `"failed_provider"`: provider raised (rate limit, timeout, auth, network).
    """
    try:
        response = provider.generate(
            system=ENRICHMENT_PROMPT_AR,
            user=chunk.passage_text,
            max_tokens=300,
        )
    except Exception:  # noqa: BLE001 — broad: covers all provider SDK failures
        chunk.summary = chunk.summary or ""
        chunk.keywords = chunk.keywords or []
        chunk.enrichment_status = "failed_provider"
        return chunk

    try:
        payload = json.loads(response.text)
        chunk.summary = str(payload.get("summary", "") or "")
        kw = payload.get("keywords", []) or []
        chunk.keywords = [str(k).strip() for k in kw if str(k).strip()]
        chunk.enrichment_status = "ok"
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        chunk.summary = chunk.summary or ""
        chunk.keywords = chunk.keywords or []
        chunk.enrichment_status = "failed_json"
    return chunk


def enrich_all_chunks(chunks: list[Chunk], provider: LLMProvider) -> list[Chunk]:
    """Run enrichment over every chunk (in-place); returns the same list."""
    for chunk in chunks:
        enrich_chunk_metadata(chunk, provider)
    return chunks


# ---------------------------------------------------------------------------
# Embedding (sentence-transformers, BGE-M3 by default)
# ---------------------------------------------------------------------------

_EMBEDDER_CACHE: dict[str, object] = {}


def get_embedder(model_name: str = "BAAI/bge-m3"):
    """Lazy-loaded sentence-transformers embedder. Cached per model name.

    Note: first call downloads the BGE-M3 weights (~2.3GB) into the HF cache.
    """
    if model_name in _EMBEDDER_CACHE:
        return _EMBEDDER_CACHE[model_name]
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415
    model = SentenceTransformer(model_name)
    _EMBEDDER_CACHE[model_name] = model
    return model


def build_embedding_input(chunk: Chunk) -> str:
    """Concatenate passage + summary + keywords for embedding / BM25 indexing.

    `passage_text` is preserved verbatim on the chunk for citation accuracy.
    This concatenation is the INPUT TO THE EMBEDDER and the BM25 index ONLY.
    """
    parts = [chunk.passage_text]
    if chunk.summary:
        parts.append(chunk.summary)
    if chunk.keywords:
        parts.append(" ".join(chunk.keywords))
    return " ".join(parts)


def embed_chunks(chunks: list[Chunk], embedder_model: str = "BAAI/bge-m3") -> np.ndarray:
    """Embed all chunks. Returns L2-normalized (N, D) array.

    Each chunk's `embedding_input` is populated as a side effect (debugging).
    """
    embedder = get_embedder(embedder_model)
    inputs: list[str] = []
    for chunk in chunks:
        chunk.embedding_input = build_embedding_input(chunk)
        # Embed the LIGHT-NORMALIZED form for consistency with retrieval-time
        # query normalization (§0.3).
        inputs.append(light_normalize(chunk.embedding_input))

    embeddings = embedder.encode(
        inputs,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(embeddings, dtype=np.float32)


# ---------------------------------------------------------------------------
# End-to-end ingest
# ---------------------------------------------------------------------------

def load_sources(sources_path: Path) -> list[dict]:
    """Read `sources.json` as UTF-8."""
    with sources_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_index(
    data_dir: Path,
    enrichment_provider: LLMProvider,
    embedder_model: str = "BAAI/bge-m3",
) -> Index:
    """End-to-end: load sources -> chunk -> enrich -> embed -> Index.

    Args:
        data_dir: Path to the `data/` directory (containing `sources.json`).
        enrichment_provider: LLM for per-chunk summary/keywords enrichment.
            Phase 1 uses MockProvider; Phase 2+ wires a cheap real model.
        embedder_model: sentence-transformers model name. Default BGE-M3.

    Returns:
        Index with chunks and L2-normalized embeddings.
    """
    sources = load_sources(data_dir / "sources.json")
    chunks = chunk_all_sources(sources)
    enrich_all_chunks(chunks, enrichment_provider)
    embeddings = embed_chunks(chunks, embedder_model=embedder_model)
    return Index(chunks=chunks, embeddings=embeddings)

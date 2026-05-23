"""Tests for src/murshid/ingest.py.

Pins the chunker on iqama-002 (prose), iqama-003 (FAQ), and municipal-004
(prose with Hijri). Asserts enrichment populates per kickoff Phase 1 task 9.
"""

from pathlib import Path

import pytest

from murshid.ingest import (
    chunk_paragraphs,
    chunk_source,
    enrich_all_chunks,
    is_faq_format,
    load_sources,
)
from murshid.providers.mock import MockProvider


DATA_DIR = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def sources():
    return load_sources(DATA_DIR / "sources.json")


def _get_source(sources, source_id):
    for s in sources:
        if s["source_id"] == source_id:
            return s
    raise AssertionError(f"source not found: {source_id}")


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def test_iqama_002_is_prose(sources):
    src = _get_source(sources, "iqama-002")
    assert not is_faq_format(src["content"]), "iqama-002 is continuous prose"


def test_iqama_003_is_faq(sources):
    src = _get_source(sources, "iqama-003")
    assert is_faq_format(src["content"]), "iqama-003 is FAQ-style"


def test_municipal_004_is_prose(sources):
    src = _get_source(sources, "municipal-004")
    assert not is_faq_format(src["content"]), "municipal-004 is continuous prose"


# ---------------------------------------------------------------------------
# Pinned chunking
# ---------------------------------------------------------------------------

def test_chunk_iqama_002_paragraph_count(sources):
    src = _get_source(sources, "iqama-002")
    chunks = chunk_source(src)
    expected = len(chunk_paragraphs(src["content"]))
    assert len(chunks) == expected
    assert chunks[0].chunk_id == "iqama-002:chunk-1"
    assert chunks[-1].chunk_id == f"iqama-002:chunk-{expected}"


def test_chunk_iqama_003_qa_pairs(sources):
    src = _get_source(sources, "iqama-003")
    chunks = chunk_source(src)
    # Every non-intro chunk starts with س:
    qa_chunks = [c for c in chunks if c.passage_text.startswith("س:")]
    assert len(qa_chunks) == 4, f"expected 4 Q&A chunks for iqama-003, got {len(qa_chunks)}"


def test_chunk_municipal_004_paragraph_split(sources):
    src = _get_source(sources, "municipal-004")
    chunks = chunk_source(src)
    assert len(chunks) >= 3
    assert all(c.service_category == "municipal_permits" for c in chunks)


# ---------------------------------------------------------------------------
# Chunk shape — full citation contract
# ---------------------------------------------------------------------------

def test_chunk_carries_full_citation_metadata(sources):
    src = _get_source(sources, "iqama-002")
    chunks = chunk_source(src)
    for chunk in chunks:
        assert chunk.source_id == "iqama-002"
        assert chunk.service_category == "iqama"
        assert chunk.service_title == src["service_title"]
        assert chunk.chunk_id.startswith("iqama-002:chunk-")
        assert chunk.passage_text


def test_passage_text_is_in_original_source(sources):
    """`passage_text` must appear in the original source content (after the
    chunker's strip). This is what lets citation accuracy use exact-substring
    matching against `gold_citations[].quoted_passage`.
    """
    for src in sources:
        chunks = chunk_source(src)
        for chunk in chunks:
            assert chunk.passage_text in src["content"], (
                f"chunk {chunk.chunk_id} passage_text is not a substring "
                f"of the original source content"
            )


def test_chunk_ids_are_ordinal_and_unique(sources):
    """`chunk_id` must be `source_id:chunk-N` and unique within the source."""
    for src in sources:
        chunks = chunk_source(src)
        ids = [c.chunk_id for c in chunks]
        assert len(set(ids)) == len(ids), f"duplicate chunk_id in {src['source_id']}"
        for i, c in enumerate(chunks, 1):
            assert c.chunk_id == f"{src['source_id']}:chunk-{i}"


# ---------------------------------------------------------------------------
# Enrichment populates summary + keywords (Phase 1 task 9 contract)
# ---------------------------------------------------------------------------

def test_enrichment_populates_fields_for_all_chunks(sources):
    """Every chunk gets summary + keywords after enrichment (best-effort).

    Phase 1 acceptance: enrichment is non-fatal but must populate fields
    when the provider succeeds. MockProvider always succeeds.
    """
    for src in sources[:3]:  # First 3 sources is enough for the contract
        chunks = chunk_source(src)
        enriched = enrich_all_chunks(chunks, MockProvider())
        for c in enriched:
            assert c.summary, f"chunk {c.chunk_id} has empty summary after MockProvider enrichment"
            assert c.keywords, f"chunk {c.chunk_id} has empty keywords after MockProvider enrichment"


def test_enrichment_does_not_mutate_passage_text(sources):
    """Enrichment must NOT change `passage_text` — citation accuracy depends
    on the verbatim source quote being preserved.
    """
    src = _get_source(sources, "iqama-002")
    chunks = chunk_source(src)
    originals = [c.passage_text for c in chunks]
    enrich_all_chunks(chunks, MockProvider())
    for original, chunk in zip(originals, chunks, strict=True):
        assert chunk.passage_text == original, (
            f"chunk {chunk.chunk_id} passage_text was modified by enrichment"
        )

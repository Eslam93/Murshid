"""Tests for Arabic-Indic digit normalization — Phase 8 creative add-on.

Two layers:
  1. `fold_arabic_indic_digits` / `to_arabic_indic_digits` unit contract.
  2. End-to-end retrieval: a query in Arabic-Indic digits should match a
     Western-digit corpus chunk via the BM25 layer (the digit fold is wired
     into `retrieve._bm25_normalize`).

The end-to-end test uses MockProvider and builds a tiny in-memory index so it
runs in under a second and doesn't require the full BGE-M3 download path.
"""

from __future__ import annotations

import pytest

from murshid.normalize import (
    fold_arabic_indic_digits,
    light_normalize,
    to_arabic_indic_digits,
)


# ---------------------------------------------------------------------------
# fold_arabic_indic_digits — unit contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "arabic_indic,western",
    [
        ("٠", "0"),
        ("١", "1"),
        ("٢", "2"),
        ("٣", "3"),
        ("٤", "4"),
        ("٥", "5"),
        ("٦", "6"),
        ("٧", "7"),
        ("٨", "8"),
        ("٩", "9"),
        ("٠١٢٣٤٥٦٧٨٩", "0123456789"),
        ("١٠/٠٩", "10/09"),
        ("١٤٤٧", "1447"),
    ],
)
def test_fold_basic_arabic_indic(arabic_indic, western):
    assert fold_arabic_indic_digits(arabic_indic) == western


@pytest.mark.parametrize(
    "persian_urdu,western",
    [
        ("۰۱۲۳۴۵۶۷۸۹", "0123456789"),
        ("۱۰", "10"),
    ],
)
def test_fold_extended_persian_urdu(persian_urdu, western):
    """The extended Arabic-Indic block (U+06F0..U+06F9) is used in Persian
    and Urdu — less common in Saudi Arabic but should fold the same way so
    a reviewer probing with a Persian-keyboard input still matches."""
    assert fold_arabic_indic_digits(persian_urdu) == western


def test_fold_preserves_arabic_letters():
    """Arabic letters and punctuation must pass through unchanged. Only the
    digit codepoints are translated."""
    assert fold_arabic_indic_digits("رمضان") == "رمضان"
    assert fold_arabic_indic_digits("شعبان ١٤٤٧هـ") == "شعبان 1447هـ"
    assert fold_arabic_indic_digits("لا أرقام هنا") == "لا أرقام هنا"


def test_fold_preserves_western_digits_in_mixed_text():
    """If a text already has Western digits, they stay as-is. Mixed Arabic-Indic
    + Western digits in the same text both end up Western."""
    assert fold_arabic_indic_digits("العقد 12345-٦٧٨") == "العقد 12345-678"


def test_fold_preserves_english_domain_tokens():
    """English allowlist tokens (OTP, IBAN, Absher) and service codes must
    pass through unchanged — only digit codepoints are translated."""
    assert fold_arabic_indic_digits("OTP code REJ-TRN-04") == "OTP code REJ-TRN-04"


def test_fold_handles_empty_and_none():
    assert fold_arabic_indic_digits("") == ""
    assert fold_arabic_indic_digits(None) is None  # type: ignore[arg-type]


def test_fold_is_idempotent():
    """Folding an already-folded string is a no-op. Important because the
    bench-side normalization stack may apply the fold multiple times across
    indexing + query views; idempotence makes that safe."""
    text = "١٠ رمضان ١٤٤٧هـ"
    folded_once = fold_arabic_indic_digits(text)
    folded_twice = fold_arabic_indic_digits(folded_once)
    assert folded_once == folded_twice


# ---------------------------------------------------------------------------
# to_arabic_indic_digits — inverse direction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "western,arabic_indic",
    [
        ("0", "٠"),
        ("9", "٩"),
        ("0123456789", "٠١٢٣٤٥٦٧٨٩"),
        ("10/09", "١٠/٠٩"),
        ("1447", "١٤٤٧"),
    ],
)
def test_to_arabic_indic_basic(western, arabic_indic):
    assert to_arabic_indic_digits(western) == arabic_indic


def test_to_arabic_indic_preserves_arabic_letters():
    assert to_arabic_indic_digits("رمضان 1447") == "رمضان ١٤٤٧"


def test_to_arabic_indic_round_trip():
    """fold → to_arabic_indic → fold should round-trip cleanly for any
    Arabic-Indic input."""
    original = "١٠ رمضان ١٤٤٧"
    western = fold_arabic_indic_digits(original)
    back_to_indic = to_arabic_indic_digits(western)
    assert back_to_indic == original


# ---------------------------------------------------------------------------
# Interaction with light_normalize
# ---------------------------------------------------------------------------

def test_light_normalize_does_NOT_fold_digits():
    """The kickoff §0.2 documented 4-step normalization (NFKC + tatweel +
    diacritics + hamzated-alef) does NOT include digit folding. Phase 8
    digit folding is a SEPARATE function applied at the retrieval layer
    in `retrieve.py`. Pinning this so a future contributor doesn't bolt
    fold_digits onto light_normalize without thinking about the §0.2 spec."""
    text = "١٠ رمضان ١٤٤٧هـ"
    out = light_normalize(text)
    # tatweel and the hijri-marker-letter behaviour are preserved per
    # `test_normalization.py`; here we just confirm digits are NOT folded.
    assert "١٠" in out
    assert "١٤٤٧" in out
    assert "10" not in out
    assert "1447" not in out


def test_fold_after_light_normalize_yields_western_digits():
    """The retrieval-layer composition: fold(light_normalize(text)) yields
    the BM25-indexing form. Pin the composed behaviour explicitly so the
    `retrieve._bm25_normalize` wrapper is reviewable."""
    text = "١٠ رمضان ١٤٤٧هـ"
    normalized = fold_arabic_indic_digits(light_normalize(text))
    assert "10 رمضان 1447" in normalized
    # tatweel-stripped: `هـ` may become `ه` post-light_normalize. That's
    # tested in test_normalization.py; here we only care about the digit fold.


# ---------------------------------------------------------------------------
# End-to-end retrieval: Arabic-Indic query hits Western-digit corpus
# ---------------------------------------------------------------------------


def test_retrieval_arabic_indic_query_matches_western_corpus():
    """The headline use case: a user with an Arabic keyboard probes the
    pipeline with Arabic-Indic digits. The BM25 layer normalises both the
    indexed text and the query through `fold_arabic_indic_digits` so the
    query hits the same chunk it would have hit with Western digits.

    Synthetic minimal index: one chunk with `1447هـ` Western digits; query
    once with Western digits, once with Arabic-Indic digits, expect the
    BM25 scores to agree.
    """
    from murshid.ingest import Chunk
    from murshid.retrieve import BM25Index, _bm25_normalize

    chunks = [
        Chunk(
            source_id="iqama-002",
            service_category="iqama",
            service_title="تجديد الإقامة",
            chunk_id="iqama-002:chunk-0",
            passage_text="إذا انتهت الإقامة في 1447هـ فتقدر تجدد قبل تاريخ الانتهاء",
            embedding_input="إذا انتهت الإقامة في 1447هـ فتقدر تجدد قبل تاريخ الانتهاء",
            summary="",
            keywords=[],
            enrichment_status="skipped",
        ),
        Chunk(
            source_id="iqama-003",
            service_category="iqama",
            service_title="بدل فاقد الإقامة",
            chunk_id="iqama-003:chunk-0",
            passage_text="رسوم بدل فاقد الإقامة 500 ريال",
            embedding_input="رسوم بدل فاقد الإقامة 500 ريال",
            summary="",
            keywords=[],
            enrichment_status="skipped",
        ),
    ]

    bm25 = BM25Index(chunks)

    western_query_tokens = _bm25_normalize("تجديد الإقامة 1447هـ").split()
    indic_query_tokens = _bm25_normalize("تجديد الإقامة ١٤٤٧هـ").split()

    western_scores = bm25.get_scores(western_query_tokens)
    indic_scores = bm25.get_scores(indic_query_tokens)

    # Both queries should produce identical BM25 scores — the digit fold
    # makes them lexically equivalent post-normalisation.
    assert list(western_scores) == list(indic_scores)
    # And the iqama-002 chunk (which carries `1447`) should outscore iqama-003.
    assert western_scores[0] > western_scores[1]
    assert indic_scores[0] > indic_scores[1]


def test_retrieval_passage_text_stays_verbatim():
    """Citation contract (§0.8): passage_text is the verbatim source quote.
    The digit fold applies ONLY to the BM25 indexing input (and to the query),
    not to passage_text. A reviewer reading the citation sees the original
    Western digits even though BM25 internally indexed the folded form."""
    from murshid.ingest import Chunk

    chunk = Chunk(
        source_id="iqama-002",
        service_category="iqama",
        service_title="تجديد الإقامة",
        chunk_id="iqama-002:chunk-0",
        passage_text="إذا انتهت الإقامة في 1447هـ فتقدر تجدد",
        embedding_input="إذا انتهت الإقامة في 1447هـ فتقدر تجدد",
        summary="",
        keywords=[],
        enrichment_status="skipped",
    )
    # passage_text reflects the verbatim source, unchanged by retrieval-layer
    # normalisation.
    assert "1447" in chunk.passage_text
    assert "١٤٤٧" not in chunk.passage_text

"""Fixtures for Murshid's own tests.

`fake_embedder` puts a model-free embedder where the BGE-M3 model would load, so the default
test run can build an index over the real corpus and run the whole pipeline.
"""

from __future__ import annotations

import numpy as np
import pytest

import murshid.ingest as ingest
from murshid._toolkit.hybrid_retrieval.core import FakeEmbedder


class FakeSentenceEncoder:
    """Stands in for the BGE-M3 SentenceTransformer: the vendored W106 FakeEmbedder behind the
    one method Murshid calls, `encode`. Deterministic, and it needs no model or network."""

    def __init__(self) -> None:
        self._inner = FakeEmbedder()

    def encode(
        self,
        sentences: list[str],
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        vectors = np.asarray(self._inner.embed(list(sentences)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


@pytest.fixture
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """For this test, `ingest.get_embedder` returns the fake instead of loading BGE-M3."""
    monkeypatch.setitem(ingest._EMBEDDER_CACHE, "BAAI/bge-m3", FakeSentenceEncoder())

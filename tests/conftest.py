"""Test-wide guards and fixtures for Murshid's own tests.

No test reads the developer's `.env` or a real API key: every test runs with the settings file
switched off and every settings variable removed from the environment. A test that needs a
setting passes it explicitly (`load_settings(Settings, _env_file=None, ...)`) or sets it with
`monkeypatch.setenv`. A key in a test is always a fake one, and a paid provider in a test always
talks to a fake transport.

`fake_embedder` puts a model-free embedder where the BGE-M3 model would load, so the default
test run can build an index over the real corpus and run the whole pipeline.
"""

from __future__ import annotations

import numpy as np
import pytest

import murshid.ingest as ingest
import murshid.settings
from murshid._toolkit.hybrid_retrieval.core import FakeEmbedder
from murshid.settings import env_names

# Read by the vendor SDKs themselves when no key is passed; removed too, for good measure.
_SDK_KEY_VARIABLES = ("GOOGLE_API_KEY", "ANTHROPIC_AUTH_TOKEN")


@pytest.fixture(autouse=True)
def _no_developer_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(murshid.settings, "ENV_FILE", None)
    for name in (*env_names(), *_SDK_KEY_VARIABLES):
        monkeypatch.delenv(name, raising=False)


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

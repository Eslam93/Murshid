"""Embedders: text in, vector out, any number of texts at a time.

`Embedder` is the whole contract, one method. The dense index (`dense.py`) cuts the records into
batches, so an embedder makes one call per `embed`, and it scales every vector to unit length, so
an embedder need not.

`FakeEmbedder` is the stand-in for tests and for a first run: no model, no network, no download.
Each text becomes a hashed count of its character runs, so the same text gives the same vector on
every platform and in every process, and two texts are close when their spelling is. It knows
spelling, not meaning.

`CachedEmbedder` asks another embedder only for texts its store does not hold. An index has no add
or remove, so a change to the records is a rebuild, and without this wrapper a rebuild embeds every
record again. The store is keyed by the exact text, so a changed record misses by itself, and it is
any mapping the host chooses, so the vectors can outlive the process. A build that fails halfway
leaves the batches it finished in the store, and a build from that store starts from there.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, MutableMapping, Sequence
from dataclasses import dataclass
from hashlib import blake2b
from typing import Protocol

__all__ = ["CachedEmbedder", "Embedder", "FakeEmbedder"]

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """One vector for each text, in the order given, all of the same length."""
        ...


def _character_runs(text: str) -> Iterator[str]:
    """Every run of two and of three characters in each word, with the word's edges marked."""
    for word in _WORD.findall(text.casefold()):
        marked = f" {word} "
        for size in (2, 3):
            for start in range(len(marked) - size + 1):
                yield marked[start : start + size]


@dataclass(frozen=True)
class FakeEmbedder:
    """A deterministic embedder that hashes character runs into `dimensions` slots.

    The hash is blake2b, not `hash()`, which Python seeds differently in every process.
    """

    dimensions: int = 256

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for run in _character_runs(text):
            digest = blake2b(run.encode("utf-8"), digest_size=8).digest()
            slot = int.from_bytes(digest[:7]) % self.dimensions
            vector[slot] += 1.0 if digest[7] & 1 else -1.0
        return vector


class CachedEmbedder:
    """Asks `inner` only for the texts `store` does not hold, once each.

    Keep one store per model: a vector from another model has the right shape and the wrong
    meaning, and nothing here can tell them apart. Query texts land in the store too, so it grows
    with every new query: a long-running service should give it a size limit.
    """

    def __init__(self, inner: Embedder, store: MutableMapping[str, Sequence[float]]) -> None:
        self._inner, self._store = inner, store

    def embed(self, texts: Sequence[str]) -> list[Sequence[float]]:
        wanted = dict.fromkeys(texts)
        # Kept here, not read back: a store with a size limit may drop what this call still needs.
        known = {text: self._store[text] for text in wanted if text in self._store}
        missing = [text for text in wanted if text not in known]
        if missing:
            # Built first, so a reply of the wrong length stores nothing.
            fresh = dict(zip(missing, self._inner.embed(missing), strict=True))
            self._store.update(fresh)
            known |= fresh
        return [known[text] for text in texts]

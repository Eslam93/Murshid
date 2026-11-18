"""An embedder behind an OpenAI-compatible embeddings endpoint, over httpx.

One `embed` is one POST to `{base_url}/embeddings`. Hosted services and local servers such as
Ollama, vLLM and Text Embeddings Inference speak this shape, so a small model on your own machine
needs nothing but its address. The endpoint receives every record and every query, so point it at
one you trust with them.

There is no retry here: a refused call raises `httpx.HTTPStatusError`, and a transport failure
raises its own httpx error. Wrap `embed` if you want one. Under `CachedEmbedder` the batches that
finished stay in its store, so a build run again from that store resumes.

The key travels only in the Authorization header. This module is not imported by the package, so
the rest of the core runs without httpx.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

__all__ = ["OpenAICompatibleEmbedder"]


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        *,
        http: httpx.Client,
        base_url: str,
        model: str,
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self._http = http
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._dimensions = dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        body: dict[str, object] = {"model": self._model, "input": list(texts)}
        if self._dimensions is not None:
            body["dimensions"] = self._dimensions
        response = self._http.post(self._url, json=body, headers=self._headers)
        response.raise_for_status()
        # Each row names the input it belongs to; the order of the rows is not promised.
        rows = sorted(response.json()["data"], key=lambda row: row["index"])
        return [row["embedding"] for row in rows]

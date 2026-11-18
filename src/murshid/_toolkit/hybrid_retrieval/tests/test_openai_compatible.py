"""The endpoint adapter on a mock transport: no network, no key, no model."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import pytest

# The adapter is optional: without httpx the file skips as a whole. This project's tests have it.
httpx = pytest.importorskip("httpx", reason="install the optional 'http-embeddings' group")

from murshid._toolkit.hybrid_retrieval.core import (  # noqa: E402
    CachedEmbedder,
    DenseIndex,
    FakeEmbedder,
    HybridIndex,
    Record,
)
from murshid._toolkit.hybrid_retrieval.core.openai_compatible import (  # noqa: E402
    OpenAICompatibleEmbedder,
)
from murshid._toolkit.hybrid_retrieval.tests.doubles import OFFICE  # noqa: E402

BASE_URL = "http://embeddings.test/v1"
FAKE = FakeEmbedder(dimensions=32)


def answered_by_the_fake(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    rows = [
        {"object": "embedding", "index": index, "embedding": vector}
        for index, vector in enumerate(FAKE.embed(texts))
    ]
    usage = {"prompt_tokens": 0, "total_tokens": 0}
    return httpx.Response(200, json={"object": "list", "data": rows, "usage": usage})


def embedder_on(
    answer: Callable[[httpx.Request], httpx.Response] = answered_by_the_fake, **options: object
) -> OpenAICompatibleEmbedder:
    http = httpx.Client(transport=httpx.MockTransport(answer))
    return OpenAICompatibleEmbedder(http=http, base_url=BASE_URL, model="small", **options)


def seen_by(requests: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answered_by_the_fake(request)

    return answer


def test_the_request_is_the_endpoints_shape() -> None:
    requests: list[httpx.Request] = []
    embedder_on(seen_by(requests), api_key="test-key").embed(["toner", "حبر طابعة"])
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/embeddings"
    assert json.loads(request.content) == {"model": "small", "input": ["toner", "حبر طابعة"]}
    assert request.headers["authorization"] == "Bearer test-key"


def test_a_local_server_needs_no_key_and_a_trailing_slash_changes_nothing() -> None:
    requests: list[httpx.Request] = []
    http = httpx.Client(transport=httpx.MockTransport(seen_by(requests)))
    embedder = OpenAICompatibleEmbedder(http=http, base_url=f"{BASE_URL}/", model="small")
    embedder.embed(["toner"])
    assert str(requests[0].url) == f"{BASE_URL}/embeddings"
    assert "authorization" not in requests[0].headers


def test_dimensions_are_asked_for_only_when_set() -> None:
    requests: list[httpx.Request] = []
    embedder_on(seen_by(requests)).embed(["toner"])
    embedder_on(seen_by(requests), dimensions=256).embed(["toner"])
    assert "dimensions" not in json.loads(requests[0].content)
    assert json.loads(requests[1].content)["dimensions"] == 256


def test_vectors_come_back_in_the_order_of_the_texts_whatever_the_order_of_the_rows() -> None:
    def backwards(request: httpx.Request) -> httpx.Response:
        body = json.loads(answered_by_the_fake(request).content)
        body["data"].reverse()
        return httpx.Response(200, json=body)

    assert embedder_on(backwards).embed(["toner", "paper", "حبر"]) == FAKE.embed(
        ["toner", "paper", "حبر"]
    )


def test_nothing_is_sent_for_no_texts() -> None:
    requests: list[httpx.Request] = []
    assert embedder_on(seen_by(requests)).embed([]) == []
    assert requests == []


@pytest.mark.parametrize("status", [401, 429, 500])
def test_a_refusal_is_raised_and_does_not_carry_the_key(status: int) -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "no"}})

    with pytest.raises(httpx.HTTPStatusError) as raised:
        embedder_on(refused, api_key="test-key").embed(["toner"])
    assert "test-key" not in str(raised.value)


def test_a_transport_failure_is_raised_as_it_is() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(httpx.ConnectError):
        embedder_on(unreachable).embed(["toner"])


def test_a_short_reply_is_stopped_by_the_index() -> None:
    def short(request: httpx.Request) -> httpx.Response:
        body = json.loads(answered_by_the_fake(request).content)
        return httpx.Response(200, json={"data": body["data"][:1]})

    with pytest.raises(ValueError, match="1 vectors for 2 texts"):
        DenseIndex([Record("a", "one"), Record("b", "two")], embedder_on(short))


def test_the_adapter_in_place_of_the_fake_changes_no_result() -> None:
    over_http = HybridIndex(OFFICE, embedder_on())
    direct = HybridIndex(OFFICE, FAKE)
    for query in ("حبر الطابعة", "كرسي", "laser printer"):
        assert over_http.search(query) == direct.search(query)


def test_a_build_that_fails_halfway_resumes_from_the_batches_it_finished() -> None:
    requests: list[httpx.Request] = []

    def fails_on_the_second(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 2:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return answered_by_the_fake(request)

    store: dict[str, Sequence[float]] = {}
    cached = CachedEmbedder(embedder_on(fails_on_the_second), store)
    records = [Record(n, f"line {n}") for n in range(4)]
    with pytest.raises(httpx.HTTPStatusError):
        DenseIndex(records, cached, batch_size=2)
    assert sorted(store) == ["line 0", "line 1"]

    requests.clear()
    index = DenseIndex(records, CachedEmbedder(embedder_on(seen_by(requests)), store), batch_size=2)
    assert len(index) == 4
    assert [json.loads(request.content)["input"] for request in requests] == [["line 2", "line 3"]]

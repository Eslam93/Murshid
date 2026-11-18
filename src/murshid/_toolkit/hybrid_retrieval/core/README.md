# Dense and hybrid retrieval over your own records, in Arabic and English

Ranks your own records by what they mean as well as by the words they use. `HybridIndex` runs
BM25 (C56) and a dense index over the same records and fuses the two by reciprocal rank through
C56's `Hit` and `fuse`, so a hit has the shape a lexical caller already reads, and a record only
the dense side found comes back with `matched=()`. A query is searched by several views: as
written, in its light form, and any rewrite you supply. A metadata filter runs before anything is
scored, so a filtered search returns exactly what an index of the admitted records alone would
return.

The embedder is a seam: one method, text in, vector out. `FakeEmbedder` needs no model, network or
download and is what the travelling tests run on. `OpenAICompatibleEmbedder` calls any
OpenAI-compatible embeddings endpoint, a small model on your own machine included, over httpx,
which is the only dependency here and is needed by that one file alone.

## How to call it

```python
from toolkit.hybrid_retrieval.core import FakeEmbedder, HybridIndex, Record

index = HybridIndex(
    [Record(line.id, line.description, {"team": line.team}) for line in coded_lines],
    FakeEmbedder(),  # or your own embedder
)
for hit in index.search("حبر طابعة ليزر", where={"team": "print"}, limit=10):
    hit.key, hit.score, hit.matched  # ("line-42", 0.032787, ("حبر", "طابعه", "ليزر"))
```

With a real model behind an endpoint (the adapter's module is imported by name, so the rest of the
core runs without httpx):

```python
import httpx

from toolkit.hybrid_retrieval.core import CachedEmbedder, HybridIndex
from toolkit.hybrid_retrieval.core.openai_compatible import OpenAICompatibleEmbedder

embedder = OpenAICompatibleEmbedder(
    http=httpx.Client(timeout=30.0),
    base_url="http://localhost:11434/v1",
    model="your-small-model",
)
index = HybridIndex(records, CachedEmbedder(embedder, your_store))
```

## Seams

- `Embedder`: `embed(texts)` returns one vector per text, in order, all of one length. The index
  scales them to unit length and cuts the records into batches, so an embedder does neither. The
  index checks the number of vectors, their lengths and that they are finite, and refuses a reply
  that fails. An embedder that raises is not hidden: nothing falls back to BM25 alone.
- `HybridIndex(records, embedder, batch_size=32, document_prefix="", query_prefix="", k1=1.2,
  b=0.75, subsets_kept=16)`. Keys must be distinct. The prefixes are for models that ask for one,
  such as `"passage: "` and `"query: "` for the E5 family, and go in front of every text that
  reaches the embedder. `subsets_kept` is how many filters keep their BM25 index built.
- `search(query, rewrites=(), where=None, limit=10, pool=50, k=60, min_score=0.0)`: `rewrites` are
  extra views, `pool` is how many records each side brings from each view, `k` is the fusion
  constant, and `min_score` is the cosine the dense side must pass.
- `where`: a mapping (a field must equal the value, or be one of the values in a list, tuple or
  set; a record without the field is turned away) or a function of the `Record`.
- `query_views(query, rewrites=())` and `light_form(text)` on their own. `light_form` is lighter
  than C56's `normalize` on purpose: it keeps ta marbuta, alef maqsura, hamza on waw and ya, case
  and digits, because an embedding model learned from text that keeps them.
- `DenseIndex` alone, with `search`, or `positions(where)` and `rank(views, positions)` for one
  ranking per view.
- `CachedEmbedder(embedder, store)`: asks only for texts the store does not hold, keyed by the
  exact text. Keep one store per model.
- `Hit(key, score, matched=())` and `fuse` from C56: a ranking from anywhere else, such as a vector
  database, joins by being turned into hits.

## When lifting, change

Your embedder, and `min_score` once your own records have measured it: a dense index always has a
nearest record, so with the default a query about nothing in your records still gets hits, and
only a floor brings back "nothing found". Cosines depend on the model, so the floor is yours to
set. Keep one index per tenant, or filter on the tenant; index only what the person may open.
`rewrites` come from your own model call: this core calls none. An endpoint receives every record
and every query, so point it at one you trust with them. The scan is in memory and in pure Python:
past about 10,000 records, move the vectors to a vector database and fuse its ranking with C56's
`fuse`. There is no chunking and no reranker: a record is the unit you give it, so split long
documents first.

Needs: C56, W03; the standard library; httpx for `openai_compatible.py` only. Tests:
`toolkit/hybrid_retrieval/tests/`.

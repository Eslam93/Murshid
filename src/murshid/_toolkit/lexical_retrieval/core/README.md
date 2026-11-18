# Lexical retrieval for Arabic and English, with a fusion seam

Ranks short texts (line descriptions, titles, notes) against a query with BM25, after normalising
both so that differently written forms of a word match: Arabic letter variants (hamza forms, alef
maqsura, ta marbuta, the Persian ya and kaf), diacritics, zero-width characters and direction
marks, the definite article, Arabic-Indic and Persian digits, English plurals, case. Each hit says
which query words it matched. `fuse` merges rankings by reciprocal rank, the seam where a dense
(embedding) retriever can join later without changing callers.

Normalising applies NFKC to the whole text, then W03's `LATIN` and `ARABIC` folding rules through
its `fold_text`, plus five Quranic signs that W03 keeps. A word written with a zero-width
non-joiner stays one word.

## How to call it

```python
from toolkit.lexical_retrieval.core import BM25Index, Document

index = BM25Index(Document(line.id, line.description) for line in coded_lines)
for hit in index.search("حبر طابعة ليزر", limit=10):
    hit.key, hit.score, hit.matched  # ("line-42", 3.1, ("حبر", "طابعه"))
```

## Seams

- `normalize(text)` and `tokenize(text)` on their own, for a search box or a cache key.
- `BM25Index(documents, k1=1.2, b=0.75)`; `search(query, limit=10)` returns hits with a score
  above zero, best first.
- `fuse(rankings, k=60, limit=10)`: pass this index's hits and another retriever's.
- `STOP_WORDS`: extend it for your texts.

## When lifting, change

Nothing to start; copy W03's core (`toolkit/quote_matching/core/`) beside this one, because
`normalize` imports its folding rules. It builds in memory: for more than tens of thousands of
documents, keep the index per tenant and rebuild it on change, or move to PostgreSQL full-text
search. The Arabic stemming is light (the article only); it does not find roots.

Needs: W03; the standard library. Tests: `toolkit/lexical_retrieval/tests/`.

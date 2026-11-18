"""Lexical retrieval over short texts in Arabic and English: BM25 ranking, with a fusion seam.

Texts are normalised before they are compared, so the same word written differently still matches.
`normalize` applies Unicode compatibility folding (NFKC) to the whole text, then folds it with the
`LATIN` and `ARABIC` rules of W03 (`toolkit/quote_matching`) through its `fold_text`:

- Case is folded; typographic quotes and dashes become plain ones; zero-width characters and
  direction marks are removed, so a word written with a zero-width non-joiner stays one word; a run
  of white space becomes one space.
- Arabic: diacritics and the tatweel are removed; alef with hamza or madda becomes bare alef;
  hamza on waw becomes waw and hamza on ya becomes ya; alef maqsura becomes ya; ta marbuta becomes
  ha; the Persian forms of ya and kaf become the Arabic ones; Arabic-Indic and Persian digits become
  0-9; Arabic punctuation becomes its Latin form. Five Quranic signs that W03 keeps are removed.

`tokenize` then splits the normalised text into words and stems them:

- Arabic: the definite article (with a leading wa, fa, bi, ka or li) is taken off words long
  enough to keep a stem.
- English: a plural "s" (and "es" after s, x, z, ch, sh) is taken off words longer than three
  letters.
- Words of one letter, and a short list of stop words in each language, are dropped.

`BM25Index` ranks documents for a query with Okapi BM25 (k1 1.2, b 0.75), and returns each hit
with the query terms it matched, so a caller can show why a result came up. `fuse` merges several
rankings by reciprocal rank: the seam where a dense retriever's ranking can join this one later.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from ...quote_matching.core import ARABIC, LATIN, CharRule, Rule, fold_text

__all__ = ["BM25Index", "Document", "Hit", "fuse", "normalize", "tokenize"]

K = TypeVar("K", bound=Hashable)

# Five Quranic signs that W03's ARABIC rules keep: the end of an ayah, the start of a rub el hizb,
# the small waw, the small ya and the place of sajdah. A word that holds one compares equal to the
# same word without it.
_QURANIC_SIGNS = frozenset(map(chr, (0x06DD, 0x06DE, 0x06E5, 0x06E6, 0x06E9)))
_FOLDING: tuple[Rule, ...] = (
    *LATIN,
    *ARABIC,
    CharRule("retrieval_quranic_signs", lambda char: "" if char in _QURANIC_SIGNS else char),
)
_ARTICLE = re.compile(r"^(?:و|ف|ب|ك|ل)?ال")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
STOP_WORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "of",
        "on", "or", "per", "the", "to", "with",
        "في", "من", "على", "الى", "عن", "مع", "او", "و", "ثم", "هذا", "هذه", "ذلك", "التي", "الذي",
    }
)  # fmt: skip


def normalize(text: str) -> str:
    """The text as it is compared: NFKC over the whole text, then W03's Latin and Arabic folding.

    NFKC runs on the whole text first because it can join a letter and the combining mark after
    it ("e" then U+0301 becomes "é"); W03's rules work one character at a time and cannot.
    """
    return fold_text(unicodedata.normalize("NFKC", text), _FOLDING)


def _stem(word: str) -> str:
    if word[0] >= "؀":
        stripped = _ARTICLE.sub("", word)
        return stripped if len(stripped) >= 2 else word
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        if word.endswith(("ses", "xes", "zes", "ches", "shes")):
            return word[:-2]
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    """The comparable words of a text, in order."""
    words = _WORD.findall(normalize(text))
    return [_stem(word) for word in words if len(word) > 1 and word not in STOP_WORDS]


@dataclass(frozen=True)
class Document(Generic[K]):
    key: K
    text: str


@dataclass(frozen=True)
class Hit(Generic[K]):
    key: K
    score: float
    matched: tuple[str, ...] = field(default=())


class BM25Index(Generic[K]):
    def __init__(self, documents: Iterable[Document[K]], *, k1: float = 1.2, b: float = 0.75):
        self._k1, self._b = k1, b
        self._keys: list[K] = []
        self._terms: list[Counter[str]] = []
        self._lengths: list[int] = []
        frequency: Counter[str] = Counter()
        for document in documents:
            tokens = tokenize(document.text)
            self._keys.append(document.key)
            self._terms.append(Counter(tokens))
            self._lengths.append(len(tokens))
            frequency.update(set(tokens))
        count = len(self._keys)
        self._average = (sum(self._lengths) / count) if count else 0.0
        self._idf = {
            term: math.log(1 + (count - seen + 0.5) / (seen + 0.5))
            for term, seen in frequency.items()
        }

    def __len__(self) -> int:
        return len(self._keys)

    def search(self, query: str, *, limit: int = 10) -> list[Hit[K]]:
        """The best `limit` documents with a score above zero, best first; ties keep the order
        the documents were given in."""
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms or not self._keys:
            return []
        scored: list[tuple[float, int, tuple[str, ...]]] = []
        for index, counts in enumerate(self._terms):
            score = 0.0
            matched: list[str] = []
            norm = self._k1 * (1 - self._b + self._b * self._lengths[index] / (self._average or 1))
            for term in terms:
                found = counts.get(term, 0)
                if found:
                    matched.append(term)
                    score += self._idf[term] * found * (self._k1 + 1) / (found + norm)
            if score > 0:
                scored.append((score, index, tuple(matched)))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            Hit(self._keys[index], round(score, 6), matched)
            for score, index, matched in scored[:limit]
        ]


def fuse(rankings: Sequence[Sequence[Hit[K]]], *, k: int = 60, limit: int = 10) -> list[Hit[K]]:
    """Reciprocal-rank fusion: each ranking gives a key 1 / (k + rank). A key found by several
    rankings rises; the matched terms are merged."""
    scores: dict[K, float] = {}
    matched: dict[K, list[str]] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.key] = scores.get(hit.key, 0.0) + 1 / (k + rank)
            terms = matched.setdefault(hit.key, [])
            terms += [term for term in hit.matched if term not in terms]
    ordered = sorted(scores, key=lambda key: -scores[key])
    return [Hit(key, round(scores[key], 6), tuple(matched[key])) for key in ordered[:limit]]

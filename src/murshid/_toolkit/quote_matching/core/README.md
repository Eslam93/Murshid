# Finding a quote in its source text, with the kind of match

A model that cites a document gives a block and a short quote. `align` finds the quote in the text
and says how it was found: `exact`, `normalized` (after folding), `fuzzy` (approximately),
`misattributed` (found, but outside the cited blocks) or `not_found`. Every span is a position in
the original text, because folding keeps a map back to the original characters. Two helpers go
with it: the stretches no quote covers, and positions for a browser. Plain functions on strings
and integers.

## How to call it

```python
from toolkit.quote_matching.core import FuzzyPolicy, align, uncited, utf16_positions

# windows: the cited blocks, from block_id to end_block_id, as (start, end) in the text
found = align(text, quote, windows=[(410, 498), (500, 571)], after=0, fuzzy=FuzzyPolicy())
found.kind, found.span, found.score  # "normalized", (452, 540), 1.0

uncited(len(text), spans, min_chars=40)  # [(0, 118), (900, 1250)]: what no quote covers
utf16_positions(text, spans)  # the same spans, counted the way JavaScript counts
```

| Kind | When | Score |
|---|---|---|
| `exact` | the quote, without spaces at its ends, appears character for character | 1.0 |
| `normalized` | the folded quote appears in the folded text | 1.0 |
| `fuzzy` | only with a `FuzzyPolicy`: the longest run of quote words found in order covers at least `coverage` (0.75) of the quote, and fills at least `density` (one third) of the text it spans | coverage times density |
| `misattributed` | not inside the windows, but found elsewhere by one of the tiers above | that tier's |
| `not_found` | none of the above; `span` is None | 0.0 |

- **The windows come first.** All three tiers run inside the windows before any runs on the whole
  text. Windows that touch, overlap or are separated only by spaces are joined, so a clause that
  runs across a page break is found when both blocks are cited. With no windows, the whole text is
  the window.
- **Repeated quotes stay in order.** Pass as `after` the end of the previous match of the same
  quote: a match starting there or later comes first. If there is none, an earlier one is returned.
- **Among several places**, a match at word edges comes before one inside a longer word, and an
  exact match before a normalized one. A match inside a word is still taken when there is no
  other: Arabic writes و ("and") joined to the next word, and a quote may leave it out.
- A span covers whole original characters, and never cuts a letter from its diacritics: when a
  quote stops at a letter whose marks follow it ("قال" in "وقالَ"), the span takes the marks, in
  every tier, unless a window ends first. A fuzzy span starts and ends on quote words (runs of
  letters and digits in the folded text).

## Seams

- `rules` (default `DEFAULT_RULES`, all three sets). `LATIN`: NFKC per character, case folding,
  typographic quotes and dashes, zero-width characters, runs of white space. `ARABIC`: presentation
  forms (a ligature such as ﻷ), direction marks, diacritics and tatweel, hamza and alef forms,
  alef maqsura, ta marbuta, Arabic-Indic digits, Arabic punctuation. `TRANSCRIPT`: `{tags}` and
  spaces before punctuation. Sets are tuples: add them, or filter one rule out by its `name`.
- Your own rule is a `CharRule(name, mapping)` or a `PatternRule(name, pattern, replacement,
  stage)`. Rules run by stage (`MARKUP`, `CHARACTERS`, `SPACING`), so the order of the sets does
  not matter. For PDF text with words split at line ends:
  `PatternRule("pdf_hyphens", re.compile(r"(?<=\w)-\n(?=\w)"), "", stage=MARKUP)`.
- `FuzzyPolicy(coverage, density)`: the values are starting points for an evaluation to tune. The
  fuzzy tier is off unless you pass one.
- `fold(text, rules)` on its own: `.text`, `.to_original(start, end)` for a folded span, and
  `.position_of(original)` for the other direction.
- `fold_text(text, rules)`: the same text as `fold(text, rules).text`, without the map, for code
  that only compares texts (a search index, a cache key). It remembers each character's rewrite
  per rule set between calls, so a `CharRule` mapping must give the same string for the same
  character every time. On 10,000 short lines it took about 35 ms, and `fold` about 0.95 s
  (measured 2026-10-16).

## When lifting, change

The rule sets your texts need, and the fuzzy values once your own labelled documents have measured
them. Not done here: removing Latin accents (é stays é unless you add a rule), the Arabic article,
roots, and Arabic PDF lines that come out in reverse order. The first `align` on a text folds it
(about 0.3 s for 400,000 characters, measured 2026-10-12); later quotes on the same text reuse it.

Needs: the standard library. Tests: `toolkit/quote_matching/tests/`.

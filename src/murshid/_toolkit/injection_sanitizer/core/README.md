# Prompt-injection sanitizer for untrusted text

Cleans text from an uploaded document, an email or a form before it goes into a model's prompt:
removes invisible characters, replaces sentences written as instructions to a model (English and
Arabic), chat-role markers and fake delimiters with a visible marker, and fences the result between
markers with a random token that the text cannot forge. Each change is reported, so a person
checking the model's output can be told.

## How to call it

```python
from toolkit.injection_sanitizer.core import fence, fence_note, sanitize

cleaned = sanitize(document_text, max_chars=60_000)
system = EXTRACTION_RULES + "\n\n" + fence_note()
user = "Read this invoice:\n" + fence(cleaned.text)
if cleaned.suspicious:
    invoice.flags.append("instructions_removed")  # show it to the clerk
log.info("sanitized", findings=[f.kind for f in cleaned.findings])
```

Where removal would delete real content, such as a meeting where someone says "forget the previous
plan", report instead of removing. Report on the cleaned text, never the raw one: an invisible
character inside a word ("Ig\u200bnore") hides the instruction from the patterns.

```python
import unicodedata

from toolkit.injection_sanitizer.core import remove_hidden, sanitize

clean = unicodedata.normalize("NFC", remove_hidden(document_text).text)  # before any positions
found = sanitize(clean, mode="report")  # found.text is clean, unchanged
for f in found.findings:
    highlight(f.kind, f.start, f.end)  # clean[f.start:f.end] is what was found
```

## Seams

- `Sanitized.findings`: `hidden_characters`, `instruction`, `role_marker`, `delimiter`,
  `truncated`, each with a short excerpt. `suspicious` is true for the middle three.
- `remove_hidden(text)` removes only invisible characters, the Unicode tag characters (U+E0000
  to U+E007F) included, and does not normalise. Its one finding counts what it removed.
- `sanitize(text, mode="report")` changes nothing and does not normalise, so each finding's
  `start` and `end` slice exactly the text given. Run `remove_hidden` first: an invisible
  character it is given is reported, not removed, and it can hide an instruction from the
  patterns. It never cuts, so it refuses `max_chars`. `mode="remove"` is the default, and its
  findings have no positions, because its text has changed.
- `max_chars` (remove mode only): the patterns read the cleaned text up to the cap plus a fixed
  look-ahead of 2,000 characters, so the work is bounded by the cap and not by the upload, and a
  sentence that starts before the cap is removed whole even when its trigger phrase comes after
  the cap. Nothing past the cap is kept. The text is cut once more after the patterns, because a
  marker can be longer than what it replaced. An instruction in a sentence that starts after the
  cap never reaches the model and is not reported. A trigger phrase more than the look-ahead past
  the cap is not read either; only the start of its sentence, without the phrase, is kept.
- The time grows in line with the length of the text: the sentence ends are found once per call,
  and no pattern lets the engine try every split of a run of spaces. Keep it that way when you add
  phrasings (the timing tests catch the common mistakes), and still run it off an event loop: a
  text of a few hundred thousand characters can take a few tenths of a second.
- `fence(text, label=..., token=...)` and `fence_note(label)`: pass a fixed token only in tests.
- The patterns live in `_INSTRUCTION_PATTERNS`, `_ROLE_MARKERS` and `_DELIMITERS`. The look-ahead
  is `_LOOK_AHEAD`: keep it much longer than the longest phrase a pattern matches (110 characters
  today) when you add phrasings.

## When lifting, change

Add the phrasings you see in your own traffic, in your languages. Choose removal or report per
caller: report suits text where an instruction-shaped sentence can be real content, and only
when the text is fenced and a person reviews the result. This filters known shapes; it is not a
proof. Keep the model's output typed (C52), keep a person confirming it, and never give a model
that reads untrusted text a tool that changes data.

Needs: the standard library; C64 for its tests. Tests: `toolkit/injection_sanitizer/tests/`.

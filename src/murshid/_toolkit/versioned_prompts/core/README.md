# Versioned prompts with their schema and a corrective retry note

Keeps each prompt as a named, numbered spec (system text, user template, output schema, the note
for a corrective retry, worked examples), fingerprinted, so a prompt changed without a new version
fails a test and every stored result can say which prompt produced it.

## How to call it

```python
from toolkit.versioned_prompts.core import PromptCatalog, PromptSpec

EXTRACT = PromptSpec(
    id="invoice_extraction",
    version=1,
    system="You read supplier invoices...",
    user_template="The invoice text:\n{document}",
    schema=InvoiceFields,
    correction="Your reply could not be used: {problems}. Reply with the JSON object only.",
)
CATALOG = PromptCatalog([EXTRACT])

messages = EXTRACT.render(document=sanitized_text)
label = CallLabel("invoice_extraction", EXTRACT.label)  # "invoice_extraction@1"

# in a unit test, against a committed pins file:
assert CATALOG.drift(json.loads(PINS.read_text())) == []
```

## Seams

- `render(**values)` refuses a missing or unknown field. Values go in as they are: neutralise
  untrusted text first (C39).
- `examples=(PromptExample(text, reply), ...)`: worked examples, each a text the model could be
  shown and exactly the reply it should give. `PromptExample.from_value(text, value)` writes the
  reply as the JSON of a pydantic object or a mapping, with Arabic and other letters kept as
  letters. `render` places the examples at the end of the system text, numbered, in their order;
  `system_text` is that system message. A caller that cites quotes should check each example's
  quotes against its own text before shipping it.
- `fingerprint()` covers the system text, the template, the correction and the schema's JSON
  schema, and the examples as rendered only when there are some, so a spec without examples keeps
  the fingerprint it had before examples existed. `fingerprints()` gives the pins file's content;
  `drift(pins)` lists each mismatch.
- `latest(id)` for the version new calls use; `get(label)` for the one a stored result names.
- Pass `correction` to a structured-output call (C52) as its corrective note.

## When lifting, change

Nothing in the core. Keep the pins file beside your prompts and update it in the same commit as a
new version.

Needs: pydantic. Tests: `toolkit/versioned_prompts/tests/`.

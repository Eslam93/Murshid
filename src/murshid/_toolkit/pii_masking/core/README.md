# PII masking and HTML stripping

Replaces bank and card numbers in free text with a tag (`[iban]`, `[card]`, `[account]`) before
the text reaches a trace, a log or a report, and strips markup and invisible characters from text
someone else typed (a supplier's name, a line description read from a document) before it is
stored or shown.

## How to call it

```python
from toolkit.pii_masking.core import clean_text, mask_pii

mask_pii("Pay to IBAN SA03 8000 0000 6080 1016 7519, account no. 0108-1234-5678")
# "Pay to IBAN [iban], account no. [account]"
clean_text("<b>Fictional Supplies</b>​ <script>x()</script>LLC", max_length=200)
# "Fictional Supplies LLC"
```

## Seams

- An IBAN is masked only when its check digits are right, and a card number only when it passes
  the Luhn check, so invoice numbers, amounts, dates and tax numbers stay readable. A run of
  digits after an account label (English or Arabic) is masked whatever it is.
- `strip_html` keeps line breaks for block tags; `clean_text(max_length=..., keep_newlines=...)`
  also removes control and format characters (zero-width and direction marks) and collapses spaces.

## When lifting, change

Add the labels your documents use to `_ACCOUNT`. Names are not masked: that needs a list of the
people to look for, or a model; keep text out of traces instead (C58).

Needs: the standard library. Tests: `toolkit/pii_masking/tests/`.

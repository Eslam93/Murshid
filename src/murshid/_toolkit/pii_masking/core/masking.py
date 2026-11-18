"""Masking bank and card numbers in free text, and stripping HTML from text other people typed.

`mask_pii` replaces what would let someone move money: an IBAN whose check digits are right, a card
number of 13 to 19 digits that passes the Luhn check (unless a tax or registration label comes just
before it), and a run of digits that follows an account label ("Account No.", "A/C",
"رقم الحساب"). The checks keep ordinary numbers (an invoice number, an amount, a date, a tax
number) as they are, because a trace or a log that loses them is useless. Arabic-Indic digits
count as digits.

`strip_html` turns markup into its visible text: tags go, entities are decoded, script and style
content goes, and block tags become line breaks. `clean_text` also removes control and invisible
characters and cuts the text to a length, for a field a supplier or a document filled in.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

__all__ = ["clean_text", "mask_pii", "strip_html"]

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
_CARD = re.compile(r"(?<![\d\w])\d(?:[ -]?\d){12,18}(?![\d\w])")
_ACCOUNT = re.compile(
    r"(?i)(?:account|acct|a/c|iban|bank)\s*(?:no\.?|number|#)?\s*[:#]?\s*"
    r"|(?:رقم\s+الحساب|الحساب\s+رقم|رقم\s+حساب|الآيبان|آيبان)\s*[:#]?\s*"
)
_ACCOUNT_DIGITS = re.compile(r"\d(?:[ -]?\d){5,33}")
# A tax or registration number can pass the Luhn check by chance (one in ten), so a digit run
# that follows one of these labels is never taken for a card.
_TAX_LABEL = re.compile(
    r"(?i)(?:\bvat\b|\btrn\b|\btax\b|\bcr\b|registration|الرقم\s+الضريبي|رقم\s+ضريبي|"
    r"الرقم\s+الضريبى|السجل\s+التجاري)[^\d\n]{0,20}$"
)


def _digits(text: str) -> str:
    return "".join(str(unicodedata.digit(char)) for char in text if char.isdigit())


def _iban_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    moved = compact[4:] + compact[:4]
    try:
        number = "".join(str(int(char, 36)) for char in moved)
    except ValueError:
        return False
    return int(number) % 97 == 1


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def mask_pii(text: str) -> str:
    """The text with IBANs, card numbers and labelled account numbers replaced by a tag."""
    text = _IBAN.sub(lambda m: "[iban]" if _iban_valid(m.group()) else m.group(), text)

    def card(match: re.Match[str]) -> str:
        digits = _digits(match.group())
        if not 13 <= len(digits) <= 19 or not _luhn_valid(digits):
            return match.group()
        if _TAX_LABEL.search(text, max(0, match.start() - 40), match.start()):
            return match.group()
        return "[card]"

    text = _CARD.sub(card, text)
    out: list[str] = []
    position = 0
    for label in _ACCOUNT.finditer(text):
        number = _ACCOUNT_DIGITS.match(text, label.end())
        if number is None or label.start() < position:
            continue
        out.append(text[position : number.start()])
        out.append("[account]")
        position = number.end()
    out.append(text[position:])
    return "".join(out)


_BLOCK_TAGS = frozenset(
    {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
)
_HIDDEN_TAGS = frozenset({"script", "style", "template", "noscript"})
# The line and paragraph separators, which are not control characters but still break lines.
_SEPARATORS = frozenset({chr(0x2028), chr(0x2029)})


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden = max(0, self._hidden - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def strip_html(text: str) -> str:
    """The visible text of markup: no tags, no script or style, entities decoded."""
    if "<" not in text and "&" not in text:
        return text
    parser = _TextOnly()
    parser.feed(text)
    parser.close()
    joined = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in joined.splitlines()]
    return "\n".join(line for line in lines if line)


def clean_text(text: str, *, max_length: int, keep_newlines: bool = False) -> str:
    """Markup, control characters and invisible format characters removed, spaces collapsed,
    and the result cut to `max_length`."""
    visible = strip_html(text)
    kept = "".join(
        char
        for char in visible
        if (char == "\n" and keep_newlines)
        or not (unicodedata.category(char).startswith("C") or char in _SEPARATORS)
    )
    if keep_newlines:
        collapsed = "\n".join(" ".join(line.split()) for line in kept.splitlines())
    else:
        collapsed = " ".join(kept.split())
    return collapsed.strip()[:max_length]

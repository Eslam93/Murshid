"""Masking and stripping through the public interface."""

from __future__ import annotations

import pytest

from murshid._toolkit.pii_masking.core import clean_text, mask_pii, strip_html

VALID_IBAN = "SA03 8000 0000 6080 1016 7519"
VALID_CARD = "4111 1111 1111 1111"


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        (f"Pay to IBAN {VALID_IBAN} please", "Pay to IBAN [iban] please"),
        ("IBAN: SA0380000000608010167519.", "IBAN: [iban]."),
        (f"Card {VALID_CARD} used", "Card [card] used"),
        ("Card 4111-1111-1111-1111", "Card [card]"),
        ("Account No. 0108 1234 5678", "Account No. [account]"),
        ("A/C: 55512345", "A/C: [account]"),
        ("رقم الحساب: 0108123456789", "رقم الحساب: [account]"),
        ("رقم الحساب ٠١٠٨١٢٣٤٥٦٧٨٩", "رقم الحساب [account]"),
    ],
)
def test_bank_and_card_numbers_are_masked(text: str, masked: str) -> None:
    assert mask_pii(text) == masked


@pytest.mark.parametrize(
    "text",
    [
        "Invoice INV-2026-000123 dated 2026-03-14",
        "Total 1,150.00 SAR, tax 150.00",
        # 15 digits that pass the Luhn check by chance: the tax label keeps them readable.
        "VAT number 300012345600003",
        "الرقم الضريبي: 300012345600003",
        "SA03 8000 0000 6080 1016 7518",  # wrong check digits: not an IBAN
        "4111 1111 1111 1112",  # fails the Luhn check
        "Phone +966 11 234 5678",
    ],
)
def test_ordinary_numbers_stay_readable(text: str) -> None:
    assert mask_pii(text) == text


def test_markup_becomes_its_visible_text() -> None:
    html = "<p>Fictional&nbsp;<b>Supplies</b> &amp; Co</p><script>steal()</script><div>LLC</div>"
    assert strip_html(html) == "Fictional Supplies & Co\nLLC"
    assert strip_html("plain text, no markup") == "plain text, no markup"


def test_clean_text_removes_invisible_characters_and_cuts_the_length() -> None:
    dirty = "<i>Office</i>​ ‮Chairs‬\x00 and\t\tdesks"
    assert clean_text(dirty, max_length=200) == "Office Chairs and desks"
    assert clean_text("abcdefgh", max_length=4) == "abcd"
    assert clean_text("one\n two", max_length=20, keep_newlines=True) == "one\ntwo"
    assert clean_text("كراسي <b>مكتب</b>", max_length=50) == "كراسي مكتب"

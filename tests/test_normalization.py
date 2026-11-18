"""Tests for src/murshid/normalize.py.

The CRITICAL tests pin the default-light behavior: do NOT collapse ى, ة, hamza.
These are the regression tests for the §0.2 design call.
"""

from murshid.normalize import aggressive_normalize, light_normalize


# ---------------------------------------------------------------------------
# Light normalization — applied operations
# ---------------------------------------------------------------------------

def test_tatweel_removed():
    assert light_normalize("الـــعربيـــة") == "العربية"


def test_diacritics_removed():
    # "Salam" with fatha, sukun, fatha, kasra-ish marks
    assert light_normalize("سَلَامٌ") == "سلام"


def test_hamzated_alef_collapses_to_bare_alef():
    assert light_normalize("أحمد") == "احمد"
    assert light_normalize("إقامة") == "اقامة"
    assert light_normalize("آدم") == "ادم"


def test_nfkc_idempotent_on_already_clean_text():
    clean = "تجديد الاقامة"
    assert light_normalize(clean) == clean


# ---------------------------------------------------------------------------
# The Arabic-depth catch — do NOT collapse these by default
# ---------------------------------------------------------------------------

def test_alef_maksura_preserved():
    # ى (alef-maksura) is distinct from ي in MSA proper nouns (موسى, عيسى).
    out = light_normalize("موسى")
    assert "ى" in out
    assert out == "موسى"


def test_ta_marbuta_preserved():
    # ة is meaningful in MSA noun morphology — keep it.
    out = light_normalize("إقامة")  # alef-hamza collapses, ta-marbuta stays
    assert out.endswith("ة")
    assert "ة" in out


def test_standalone_hamza_preserved():
    out = light_normalize("ماء")
    assert "ء" in out


def test_hamza_on_ya_preserved():
    out = light_normalize("سائل")
    assert "ئ" in out


def test_hamza_on_waw_preserved():
    out = light_normalize("مؤتمر")
    assert "ؤ" in out


# ---------------------------------------------------------------------------
# Aggressive normalization — only when explicitly invoked
# ---------------------------------------------------------------------------

def test_aggressive_collapses_alef_maksura():
    assert aggressive_normalize("موسى") == "موسي"


def test_aggressive_collapses_ta_marbuta():
    assert aggressive_normalize("إقامة") == "اقامه"


def test_aggressive_folds_hamza_on_ya():
    assert aggressive_normalize("سائل") == "سايل"


def test_aggressive_folds_hamza_on_waw():
    assert aggressive_normalize("مؤتمر") == "موتمر"


def test_aggressive_removes_standalone_hamza():
    assert aggressive_normalize("ماء") == "ما"


# ---------------------------------------------------------------------------
# End-to-end: real-corpus shapes
# ---------------------------------------------------------------------------

def test_government_phrase_preserves_meaningful_chars():
    sample = "تجديد الإقامة قبل انتهاء الصلاحية"
    out = light_normalize(sample)
    # ة must survive
    assert "ة" in out
    # hamzated alef in الإقامة got bare-alef-ified
    assert "إ" not in out


def test_english_domain_tokens_pass_through():
    text = "رمز OTP ما وصلني في application"
    out = light_normalize(text)
    assert "OTP" in out
    assert "application" in out


def test_hijri_date_preserved():
    # The Hijri marker "هـ" is `ه` + tatweel. We strip tatweel per §0.2, so the
    # normalized form is "1447ه" — still unambiguous, and the month name is
    # preserved verbatim so retrieval still matches.
    text = "20 رمضان 1447هـ"
    out = light_normalize(text)
    assert "1447" in out
    assert "رمضان" in out
    assert "ه" in out  # Hijri marker letter survives even though tatweel doesn't


def test_arabic_indic_numerals_pass_through_by_default():
    # We don't ship Arabic-Indic numeral normalization in v1 (per §0.9 / CREATIVE.md
    # — that's a creative-additions item if time permits).
    text = "الرقم ١٠٠"
    out = light_normalize(text)
    assert "١٠٠" in out

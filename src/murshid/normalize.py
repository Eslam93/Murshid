"""Light Arabic normalization (§0.2).

Tokenizer-aligned for BGE-M3 (light by default). Preserves ى, ة, hamza —
those distinctions are meaningful in MSA proper nouns and government / legal
Arabic. Aggressive operations sit behind NORMALIZE_AGGRESSIVE=true and are
NOT used in the default pipeline.

Why stdlib + regex rather than CAMeL Tools:
- CAMeL Tools' default normalization is aggressive (collapses ى / ة / hamza).
- The four operations we actually need (NFKC, tatweel, diacritics,
  hamzated-alef -> bare alef) are trivial in stdlib unicodedata + regex.
- Avoids the ~150MB CAMeL Tools data-download dependency for ~30 lines of
  code, and avoids the "agent reaches for aggressive normalization by default"
  pre-positioned mistake candidate.
"""

import os
import re
import unicodedata


# Combining marks: harakat range + dagger alef + extended marks.
_ARABIC_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")

# Tatweel (kashida) — purely decorative.
_TATWEEL = re.compile(r"ـ+")

# Hamzated alef variants (alef with hamza above / below, alef madda) -> bare alef.
_HAMZATED_ALEF = re.compile(r"[أإآ]")

# Aggressive-mode operations (config-gated, not default).
_ALEF_MAKSURA = re.compile(r"ى")   # ى
_TA_MARBUTA = re.compile(r"ة")     # ة
_HAMZA_ON_YA = re.compile(r"ئ")    # ئ
_HAMZA_ON_WAW = re.compile(r"ؤ")   # ؤ
_STANDALONE_HAMZA = re.compile(r"ء")  # ء

# Arabic-Indic digit translation tables (Phase 8 creative add-on).
# Basic Arabic-Indic block: U+0660..U+0669.  Extended (Persian / Urdu): U+06F0..U+06F9.
# Folding both into ASCII Western digits keeps the BM25 lexical-match layer
# numeric-script-agnostic. NFKC does NOT do this conversion (Arabic-Indic
# digits are real characters, not typographic variants like full-width digits),
# so we need an explicit mapping. Kept SEPARATE from `light_normalize` to
# preserve the kickoff §0.2 spec — digit folding is wired in at the retrieval
# layer (`retrieve.py` BM25 indexing + query) as an additive pass.
_ARABIC_INDIC_TO_WESTERN = str.maketrans({
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})
_WESTERN_TO_ARABIC_INDIC = str.maketrans({
    "0": "٠", "1": "١", "2": "٢", "3": "٣", "4": "٤",
    "5": "٥", "6": "٦", "7": "٧", "8": "٨", "9": "٩",
})


def light_normalize(text: str) -> str:
    """Apply the four default Arabic normalizations.

    Applied:
      - Unicode NFKC (canonical compatibility composition)
      - Tatweel (kashida) removal
      - Combining diacritic (harakat) removal
      - Hamzated alef -> bare alef (أ إ آ -> ا)

    NOT applied by default (would erase meaningful MSA distinctions):
      - alef-maksura -> ya (ى -> ي)
      - ta-marbuta -> ha (ة -> ه)
      - hamza folding (ئ -> ي, ؤ -> و, ء removal)

    To enable the aggressive set, call `aggressive_normalize` directly or set
    `NORMALIZE_AGGRESSIVE=true` and use the dispatch in `normalize`.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _TATWEEL.sub("", text)
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _HAMZATED_ALEF.sub("ا", text)
    return text


def aggressive_normalize(text: str) -> str:
    """Light normalization + the lossy operations.

    Only call when `NORMALIZE_AGGRESSIVE=true`. Erases distinctions used in
    MSA proper nouns and government / legal Arabic — see ADR 3 for why this
    is opt-in, not default.
    """
    text = light_normalize(text)
    text = _ALEF_MAKSURA.sub("ي", text)        # ى -> ي
    text = _TA_MARBUTA.sub("ه", text)          # ة -> ه
    text = _HAMZA_ON_YA.sub("ي", text)         # ئ -> ي
    text = _HAMZA_ON_WAW.sub("و", text)        # ؤ -> و
    text = _STANDALONE_HAMZA.sub("", text)          # ء -> ""
    return text


def normalize(text: str) -> str:
    """Apply the configured normalization level (default: light).

    Reads `NORMALIZE_AGGRESSIVE` env var; defaults to false per §0.2.
    """
    aggressive = os.environ.get("NORMALIZE_AGGRESSIVE", "false").lower() == "true"
    return aggressive_normalize(text) if aggressive else light_normalize(text)


def fold_arabic_indic_digits(text: str) -> str:
    """Fold Arabic-Indic digits to ASCII Western digits.

    `٠١٢٣٤٥٦٧٨٩` (U+0660..U+0669) and the extended Persian / Urdu set
    `۰۱۲۳۴۵۶۷۸۹` (U+06F0..U+06F9) both map to `0123456789`. Non-digit
    characters pass through unchanged.

    Phase 8 creative add-on. Wired into `retrieve.py` at the BM25 layer so
    a query in Arabic-Indic digits (`١٠ رمضان ١٤٤٧هـ`) hits the Western-digit
    indexed corpus and vice versa. NOT applied to `passage_text` in the
    citation contract — citations stay verbatim per §0.8.

    Examples:
        >>> fold_arabic_indic_digits("١٠/٠٩")
        '10/09'
        >>> fold_arabic_indic_digits("العقد رقم REJ-TRN-04")
        'العقد رقم REJ-TRN-04'
        >>> fold_arabic_indic_digits("رمضان")
        'رمضان'
    """
    if not text:
        return text
    return text.translate(_ARABIC_INDIC_TO_WESTERN)


def to_arabic_indic_digits(text: str) -> str:
    """Inverse of `fold_arabic_indic_digits` — ASCII digits to Arabic-Indic.

    Provided for symmetry and for downstream callers that need to render a
    number in Arabic-Indic form (e.g., a display-only path). The retrieval
    pipeline only uses the western-folded direction; this is a small but
    sometimes-useful utility.

    Examples:
        >>> to_arabic_indic_digits("10/09")
        '١٠/٠٩'
    """
    if not text:
        return text
    return text.translate(_WESTERN_TO_ARABIC_INDIC)

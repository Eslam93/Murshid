"""Hijri date detection (kickoff §3 Phase 8 task 2, scoped per §0.9).

Detects Hijri date mentions in Arabic text — day + month name + (optional) year +
(optional) `هـ` marker. Returns structured `HijriDate` instances with canonical
month spelling so downstream code can compare dates regardless of orthographic
variants (`الأول` vs `الاول`, `الآخر` vs `الاخر`, `ذو` vs `ذي`).

**What this module does:**
  - Detect Hijri date occurrences via regex over the 12 Islamic months.
  - Canonicalize month-name spelling variants.
  - Preserve the raw verbatim text for citation discipline (§0.8).
  - Provide a `month_index` (1-12) for ordering / comparison.

**What this module deliberately does NOT do:**
  - Calendar arithmetic across year boundaries. Adding `15 days` to `20 شعبان 1447هـ`
    requires Umm al-Qura tables (Saudi-official Hijri calendar) and a real Hijri
    converter library. Documented in `docs/CREATIVE.md` as a future production hook.
  - Hijri ↔ Gregorian conversion. Same reason; would need `hijri-converter` or
    `umalqurra` as a runtime dependency.
  - Arabic-Indic digit normalization is the OTHER Phase 8 creative add-on, now
    shipped in `normalize.fold_arabic_indic_digits` and wired into
    `retrieve._bm25_normalize`. This module's regex uses Python's Unicode-aware
    digit class (``\\d``) so Arabic-Indic numeric Hijri dates like
    ``٥ رمضان ١٤٤٧هـ`` are detected incidentally. See
    ``tests/test_hijri.py::test_extract_arabic_indic_digit_date`` for the
    structured-detection pin.

The corpus + question + red-team data has been audited (see `scripts/seed_bench.py`
adjacents) for Hijri patterns: dates use Western digits + Arabic month name + `1447هـ`
year marker. This module matches those patterns + the common spelling variants a
reviewer might probe with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Hijri month vocabulary
# ---------------------------------------------------------------------------

# (canonical_form, [accepted_variants]) for each of the 12 months, ordered 1-12.
# The canonical form is what we store in `HijriDate.month_name`; variants are
# what we recognize in input text. Variant lists include the canonical form
# itself for completeness.
_HIJRI_MONTHS: list[tuple[str, list[str]]] = [
    ("محرم",            ["محرم", "محرّم"]),
    ("صفر",             ["صفر"]),
    ("ربيع الأول",      ["ربيع الأول", "ربيع الاول", "ربيع أول"]),
    ("ربيع الآخر",      ["ربيع الآخر", "ربيع الاخر", "ربيع الثاني", "ربيع آخر"]),
    ("جمادى الأولى",    ["جمادى الأولى", "جمادى الاولى", "جمادى أولى", "جمادى الاولا"]),
    ("جمادى الآخرة",    ["جمادى الآخرة", "جمادى الاخرة", "جمادى الثانية", "جمادى آخرة"]),
    ("رجب",             ["رجب"]),
    ("شعبان",           ["شعبان"]),
    ("رمضان",           ["رمضان", "رمضآن"]),
    ("شوال",            ["شوال", "شوّال"]),
    ("ذو القعدة",       ["ذو القعدة", "ذي القعدة", "ذو القعده", "ذي القعده"]),
    ("ذو الحجة",        ["ذو الحجة", "ذي الحجة", "ذو الحجه", "ذي الحجه"]),
]

# Lookup: variant → (canonical, index). Built once at import time.
_VARIANT_TO_CANONICAL: dict[str, tuple[str, int]] = {
    variant: (canonical, idx + 1)
    for idx, (canonical, variants) in enumerate(_HIJRI_MONTHS)
    for variant in variants
}

# All variants (sorted by length descending so the regex prefers longer matches
# like "ربيع الأول" over "ربيع"). The space inside multi-word month names is a
# literal ASCII space.
_ALL_MONTH_VARIANTS = sorted(
    _VARIANT_TO_CANONICAL.keys(),
    key=len,
    reverse=True,
)

# Year: 3- or 4-digit number, optionally followed by `هـ` (or rarely just `ه`).
# `هـ` is the Hijri marker; we accept both with and without the small `ـ` tatweel
# join, because `light_normalize` strips tatweel and a normalized text would have
# `ه` rather than `هـ`.
_YEAR_PATTERN = r"(?P<year>\d{3,4})(?:\s*(?P<marker>هـ|ه)\b)?"

# Day: 1- or 2-digit number, optionally followed by a forward slash and another
# date component (we anchor on the day+month sequence, not a free-floating digit).
_DAY_PATTERN = r"(?P<day>\d{1,2})"

# Build the full pattern: DAY space MONTH (optionally SPACE YEAR).
_MONTH_ALTERNATION = "|".join(re.escape(m) for m in _ALL_MONTH_VARIANTS)
_HIJRI_DATE_RE = re.compile(
    rf"{_DAY_PATTERN}\s+(?P<month>{_MONTH_ALTERNATION})(?:\s+{_YEAR_PATTERN})?",
)


# ---------------------------------------------------------------------------
# Structured result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HijriDate:
    """A detected Hijri date.

    Frozen so callers can use it as a dict key / set member when grouping dates
    across passages.
    """

    day: int
    month_name: str       # canonical spelling, from `_HIJRI_MONTHS`
    month_index: int      # 1 (محرم) .. 12 (ذو الحجة)
    year: int | None      # None if the source text omitted the year
    has_marker: bool      # True iff `هـ` (or normalized `ه` post-tatweel) was present
    raw_text: str         # the exact substring that matched — for verbatim citation

    def __post_init__(self) -> None:
        # Trust but validate — the regex should enforce these, but a frozen dataclass
        # is the right place to fail loudly on a malformed construct.
        if not 1 <= self.day <= 30:
            raise ValueError(f"Hijri day out of range [1, 30]: {self.day}")
        if not 1 <= self.month_index <= 12:
            raise ValueError(f"Hijri month_index out of range [1, 12]: {self.month_index}")
        if self.year is not None and not 1 <= self.year <= 9999:
            raise ValueError(f"Hijri year out of plausible range: {self.year}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_hijri_dates(text: str) -> list[HijriDate]:
    """Find all Hijri date mentions in `text`.

    Returns a list in document order. Empty list if none found. Idempotent on
    repeated calls.

    The regex covers DAY + MONTH (+ optional YEAR + optional `هـ` marker). Dates
    that ship only the year (e.g., `سنة 1447هـ` with no day or month) are NOT
    matched — those are not actionable for downstream date arithmetic and would
    over-trigger on Arabic numeric mentions.
    """
    results: list[HijriDate] = []
    if not text:
        return results

    for match in _HIJRI_DATE_RE.finditer(text):
        canonical, month_index = _VARIANT_TO_CANONICAL[match.group("month")]
        year_str = match.group("year")
        year = int(year_str) if year_str else None
        marker = match.group("marker") if year_str else None
        results.append(
            HijriDate(
                day=int(match.group("day")),
                month_name=canonical,
                month_index=month_index,
                year=year,
                has_marker=bool(marker),
                raw_text=match.group(0),
            )
        )
    return results


def has_hijri_date(text: str) -> bool:
    """Cheap predicate — True iff the text contains at least one Hijri date.

    `pipeline._has_ambiguous_date` uses a coarser test (looks only for the `هـ`
    letter); this is the strict structured-detection equivalent for downstream
    code that needs to know whether to invoke `extract_hijri_dates`.
    """
    return _HIJRI_DATE_RE.search(text or "") is not None


def canonicalize_month_name(text: str) -> str:
    """Return the canonical spelling for a Hijri month name variant.

    Useful when comparing month references across passages that may use
    different orthographic conventions (`ربيع الأول` vs `ربيع الاول`). Raises
    `KeyError` if `text` is not a recognized variant.
    """
    canonical, _index = _VARIANT_TO_CANONICAL[text]
    return canonical


__all__ = [
    "HijriDate",
    "extract_hijri_dates",
    "has_hijri_date",
    "canonicalize_month_name",
]

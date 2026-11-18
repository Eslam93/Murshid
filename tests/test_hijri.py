"""Tests for src/murshid/hijri.py — Phase 8 creative add-on (Hijri detection).

Pins the contract surfaced in the docstring:
  - extract_hijri_dates returns structured HijriDate in document order
  - Month-name variants canonicalize to a single canonical form
  - `هـ` marker presence is captured but not required
  - Dates without a year are still detected (day + month only)
  - Pure year mentions (without day+month) are NOT matched (over-trigger guard)
  - HijriDate validates day / month_index / year ranges via __post_init__

Plus integration coverage against the actual corpus + question / red-team data:
all four files in data/ should be detected cleanly with no false positives or
missed dates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from murshid.hijri import (
    HijriDate,
    canonicalize_month_name,
    extract_hijri_dates,
    has_hijri_date,
)


DATA = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# extract_hijri_dates — core behavior
# ---------------------------------------------------------------------------

def test_extract_single_date_with_year_and_marker():
    result = extract_hijri_dates("إذا انتهت الرخصة في 10 رمضان 1447هـ، فينصح بالتجديد")
    assert len(result) == 1
    d = result[0]
    assert d.day == 10
    assert d.month_name == "رمضان"
    assert d.month_index == 9
    assert d.year == 1447
    assert d.has_marker is True
    assert d.raw_text == "10 رمضان 1447هـ"


def test_extract_multi_word_month_dhul_qida():
    """ذو القعدة (11th month) — multi-word month name. The regex must prefer the
    full month string over a partial match on just ذو."""
    result = extract_hijri_dates("ينتهي العقد بتاريخ 5 ذو القعدة 1447هـ")
    assert len(result) == 1
    assert result[0].month_name == "ذو القعدة"
    assert result[0].month_index == 11


def test_extract_date_without_year():
    """Day + month with no year is still actionable (e.g., for the q-016
    `15 يوماً من 5 رمضان` deadline arithmetic the gold answer leaves implicit)."""
    result = extract_hijri_dates("خلال خمسة عشر يوماً من 5 رمضان نطلب التصحيح")
    assert len(result) == 1
    assert result[0].day == 5
    assert result[0].month_name == "رمضان"
    assert result[0].year is None
    assert result[0].has_marker is False


def test_extract_multiple_dates_in_order():
    text = "بين 10 رمضان 1447هـ و 5 ذو القعدة 1447هـ تنطبق قاعدة"
    result = extract_hijri_dates(text)
    assert len(result) == 2
    assert result[0].month_name == "رمضان"
    assert result[1].month_name == "ذو القعدة"


def test_year_only_does_not_match():
    """Pure year mention (`سنة 1447هـ` or `1447هـ`) is NOT a Hijri date — no day
    or month, so we have no actionable structure to return. This prevents
    false positives on Arabic year-only references."""
    assert extract_hijri_dates("النظام يطبق منذ 1447هـ") == []
    assert extract_hijri_dates("سنة 1447هـ هي سنة هجرية") == []


def test_extract_handles_empty_and_none_input():
    assert extract_hijri_dates("") == []
    assert extract_hijri_dates(None) == []  # type: ignore[arg-type]


def test_extract_arabic_indic_digit_date():
    """Round 3 reviewer suggested pin: a reviewer probing with Arabic-Indic
    digits (`٥ رمضان ١٤٤٧هـ` instead of `5 رمضان 1447هـ`) should detect
    cleanly. The regex uses Python `\\d` which is Unicode-digit-aware, so
    this works incidentally; pinning the contract here so a future regex
    tightening doesn't silently break it. Returns day=5, month=رمضان,
    year=1447. The raw_text preserves the original Arabic-Indic digits for
    verbatim citation."""
    result = extract_hijri_dates("ينتهي العقد في ٥ رمضان ١٤٤٧هـ")
    assert len(result) == 1
    d = result[0]
    assert d.day == 5
    assert d.month_name == "رمضان"
    assert d.month_index == 9
    assert d.year == 1447
    assert d.has_marker is True
    # Raw text preserves the original Arabic-Indic digits for citation.
    assert "٥" in d.raw_text
    assert "١٤٤٧" in d.raw_text


def test_extract_ignores_gregorian_dates():
    """A date like `5/10/2024` should not be matched as Hijri — no month name."""
    result = extract_hijri_dates("التاريخ 5/10/2024 هو ميلادي")
    assert result == []


# ---------------------------------------------------------------------------
# Month-name spelling variants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "variant,expected_canonical,expected_index",
    [
        ("ربيع الأول", "ربيع الأول", 3),
        ("ربيع الاول", "ربيع الأول", 3),  # no hamza
        ("ربيع الثاني", "ربيع الآخر", 4),  # alternative name for 4th month
        ("ربيع الآخر", "ربيع الآخر", 4),
        ("ربيع الاخر", "ربيع الآخر", 4),
        ("جمادى الأولى", "جمادى الأولى", 5),
        ("جمادى الاولى", "جمادى الأولى", 5),
        ("جمادى الآخرة", "جمادى الآخرة", 6),
        ("جمادى الثانية", "جمادى الآخرة", 6),
        ("ذو القعدة", "ذو القعدة", 11),
        ("ذي القعدة", "ذو القعدة", 11),
        ("ذو الحجة", "ذو الحجة", 12),
        ("ذي الحجة", "ذو الحجة", 12),
    ],
)
def test_canonicalize_month_name_variants(variant, expected_canonical, expected_index):
    """Common orthographic variants must canonicalize to one stable spelling.
    A reviewer probing with `ذي القعدة` (genitive) should get the same canonical
    month as one probing with `ذو القعدة` (nominative)."""
    assert canonicalize_month_name(variant) == expected_canonical
    # Round-trip through extract to confirm the index lookup agrees.
    result = extract_hijri_dates(f"تاريخ 1 {variant} 1447هـ")
    assert len(result) == 1
    assert result[0].month_name == expected_canonical
    assert result[0].month_index == expected_index


def test_canonicalize_unknown_variant_raises():
    with pytest.raises(KeyError):
        canonicalize_month_name("شهر مجهول")


# ---------------------------------------------------------------------------
# has_hijri_date predicate
# ---------------------------------------------------------------------------

def test_has_hijri_date_true():
    assert has_hijri_date("ينتهي العقد في 20 شعبان 1447هـ") is True


def test_has_hijri_date_false():
    assert has_hijri_date("لا يوجد تاريخ في هذه الجملة") is False
    assert has_hijri_date("التاريخ ميلادي 5/10/2024") is False


# ---------------------------------------------------------------------------
# HijriDate dataclass validation
# ---------------------------------------------------------------------------

def test_hijri_date_validates_day_range():
    with pytest.raises(ValueError, match="day out of range"):
        HijriDate(day=0, month_name="رمضان", month_index=9, year=1447, has_marker=True, raw_text="0 رمضان 1447هـ")
    with pytest.raises(ValueError, match="day out of range"):
        HijriDate(day=31, month_name="رمضان", month_index=9, year=1447, has_marker=True, raw_text="31 رمضان 1447هـ")


def test_hijri_date_validates_month_index_range():
    with pytest.raises(ValueError, match="month_index out of range"):
        HijriDate(day=5, month_name="رمضان", month_index=13, year=1447, has_marker=True, raw_text="x")


def test_hijri_date_validates_year_range():
    with pytest.raises(ValueError, match="year out of plausible range"):
        HijriDate(day=5, month_name="رمضان", month_index=9, year=99999, has_marker=True, raw_text="x")


def test_hijri_date_year_none_is_allowed():
    """Dates without an explicit year are valid (q-016 deadline-arithmetic style)."""
    d = HijriDate(day=5, month_name="رمضان", month_index=9, year=None, has_marker=False, raw_text="5 رمضان")
    assert d.year is None


def test_hijri_date_is_frozen():
    """Frozen so callers can use HijriDate as a dict key / set member when
    grouping dates across passages."""
    d = HijriDate(day=5, month_name="رمضان", month_index=9, year=1447, has_marker=True, raw_text="5 رمضان 1447هـ")
    with pytest.raises(Exception):  # FrozenInstanceError; subclass of AttributeError
        d.day = 6  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Integration: scan the real data
# ---------------------------------------------------------------------------

def _all_text_from(path: Path) -> str:
    """Concatenate all string values in a JSON file into one searchable blob."""
    blob = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(blob, ensure_ascii=False)


def test_sources_contain_expected_hijri_dates():
    """data/sources.json carries Hijri dates in iqama-002, traffic-fines-004,
    sponsorship-003, and municipal-004 per the planning scan. Detect them all."""
    text = _all_text_from(DATA / "sources.json")
    dates = extract_hijri_dates(text)
    # The detector should find at minimum: 10 رمضان, 20 شعبان, 5 ذو القعدة (per
    # the planning-time corpus scan in scripts/seed_bench.py).
    canonical_months = {d.month_name for d in dates}
    assert "رمضان" in canonical_months
    assert "شعبان" in canonical_months
    assert "ذو القعدة" in canonical_months
    # Each should reference 1447 (the corpus year).
    assert all(d.year == 1447 for d in dates if d.year is not None)


def test_questions_contain_expected_hijri_dates():
    text = _all_text_from(DATA / "questions.json")
    dates = extract_hijri_dates(text)
    canonical_months = {d.month_name for d in dates}
    # q-007 (شعبان), q-008 / q-016 (رمضان), q-002 (رمضان) — at minimum these months
    assert "شعبان" in canonical_months
    assert "رمضان" in canonical_months


def test_gold_answers_contain_hijri_dates():
    text = _all_text_from(DATA / "gold_answers.json")
    dates = extract_hijri_dates(text)
    # Gold answers cite back to the same Hijri dates as the questions.
    assert len(dates) >= 1


def test_red_team_contains_hijri_dates():
    """rt-004 references `10 رمضان 1447هـ` per data/red_team.json."""
    text = _all_text_from(DATA / "red_team.json")
    dates = extract_hijri_dates(text)
    rt_canonical = {d.month_name for d in dates}
    assert "رمضان" in rt_canonical


def test_all_data_dates_have_marker_or_year():
    """Every Hijri date in the actual corpus + question data carries either
    a year, the `هـ` marker, or both. This pins the data convention so a future
    contributor doesn't accidentally drop the marker / year and break date
    handling downstream."""
    for path in ["sources.json", "questions.json", "gold_answers.json", "red_team.json"]:
        text = _all_text_from(DATA / path)
        for d in extract_hijri_dates(text):
            assert d.year is not None or d.has_marker, (
                f"Hijri date missing both year AND marker in {path}: {d.raw_text!r}"
            )

"""Tests for src/murshid/register.py.

Pins the three-class detector and the contains_code_switching boolean against
the 16 questions in `data/questions.json`.
"""

import json
from pathlib import Path

import pytest

from murshid.register import detect_register


DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    with (DATA / "questions.json").open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 3-class register matches the data on every question
# ---------------------------------------------------------------------------

def test_register_three_class_matches_all_questions(questions):
    misses = []
    for q in questions:
        result = detect_register(q["text"])
        if result.register != q["register"]:
            misses.append(
                f"{q['question_id']}: expected {q['register']}, got {result.register}  "
                f"(text head: {q['text'][:60]}...)"
            )
    assert not misses, "register mismatches:\n  " + "\n  ".join(misses)


# ---------------------------------------------------------------------------
# contains_code_switching boolean matches the data on every question
# ---------------------------------------------------------------------------

def test_contains_code_switching_matches_all_questions(questions):
    misses = []
    for q in questions:
        result = detect_register(q["text"])
        if result.contains_code_switching != q["contains_code_switching"]:
            misses.append(
                f"{q['question_id']}: expected cs={q['contains_code_switching']}, "
                f"got cs={result.contains_code_switching}"
            )
    assert not misses, "contains_code_switching mismatches:\n  " + "\n  ".join(misses)


# ---------------------------------------------------------------------------
# Allowlist behavior — the ADR 3 catch
# ---------------------------------------------------------------------------

def test_allowlisted_english_keeps_register_dialect():
    """q-009 has OTP / application / request (all allowlisted) + dialect markers."""
    text = "رمز OTP ما وصلني في application توثيق العقد، أقدر أرسل request جديد ولا لازم أنتظر؟"
    result = detect_register(text)
    assert result.register == "dialect"
    assert result.contains_code_switching is True


def test_non_allowlisted_english_flips_to_mixed():
    """q-010 has unpaid (NOT allowlisted) — must escalate dialect → mixed."""
    text = "دفعت المخالفة من رقم IBAN بس status باقي unpaid، هل أرفع refund request ولا أنتظر تحديث الـ portal؟"
    result = detect_register(text)
    assert result.register == "mixed"
    assert result.contains_code_switching is True


def test_pure_msa_register():
    text = "ما شروط الاعتراض على مخالفة مرورية غير مسددة؟"
    result = detect_register(text)
    assert result.register == "MSA"
    assert result.contains_code_switching is False
    assert result.dialect_family == "MSA"


def test_msa_with_allowlisted_english_still_msa():
    text = "ما إجراءات تجديد iqama؟"  # iqama is allowlisted
    result = detect_register(text)
    assert result.register == "MSA"
    assert result.contains_code_switching is True


# ---------------------------------------------------------------------------
# Phase 6 hardening — Egyptian + Levantine dialect detection
# ---------------------------------------------------------------------------
#
# These tests pin the register detector's DETECTION (not fine classification)
# of common non-Saudi Arabic dialects. The system prompt's "answer in same
# register" rule does the right thing once register is correctly detected as
# `dialect`. Family detection is rough on purpose (NADI ceiling F1 ≈ 50).

def test_egyptian_dialect_detected():
    """`إزاي`, `مش`, `اللي`, `ليه`, `كده`, `ايه` are Egyptian markers."""
    text = "إزاي أجدد الإقامة؟ مش فاهم اللي لازم أعمله."
    result = detect_register(text)
    assert result.register == "dialect"
    assert result.dialect_family == "egyptian"


def test_levantine_dialect_detected():
    """`هيك`, `ليش`, `كيفك` are Levantine markers."""
    text = "كيفك؟ ليش لازم أجدد الإقامة هلق وليس بعدين؟ هيك المنصة بتقول."
    result = detect_register(text)
    assert result.register == "dialect"
    assert result.dialect_family == "levantine"


def test_saudi_markers_still_win_when_both_present():
    """If a query has both Saudi and Egyptian markers, Saudi family wins
    (the corpus is Saudi-centric; Saudi marker check runs first in _detect_family)."""
    text = "وش أسوي بس إزاي أعرف؟"  # وش/أسوي = Najdi; إزاي = Egyptian
    result = detect_register(text)
    assert result.register == "dialect"
    assert result.dialect_family == "saudi_najdi"

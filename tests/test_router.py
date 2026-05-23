"""Tests for src/murshid/router.py.

Pins the service-category classifier against every question in
`data/questions.json`. For in-corpus questions, the router's category must
match the service_category of the question's first `expected_source_id`.
For out-of-corpus questions (empty `expected_source_ids` or escalation
intent), the router must return `out_of_scope`.
"""

import json
from pathlib import Path

import pytest

from murshid.router import route_query


DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def sources() -> list[dict]:
    with (DATA / "sources.json").open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    with (DATA / "questions.json").open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def source_category(sources) -> dict[str, str]:
    return {s["source_id"]: s["service_category"] for s in sources}


# ---------------------------------------------------------------------------
# Every question routes to a category consistent with its expected_source_ids
# ---------------------------------------------------------------------------

def test_router_classifies_all_questions(questions, source_category):
    misses = []
    for q in questions:
        result = route_query(q["text"])
        expected_ids = q.get("expected_source_ids", [])
        if not expected_ids:
            # Out-of-corpus question — must route to out_of_scope.
            if result.category != "out_of_scope":
                misses.append(
                    f"{q['question_id']}: expected out_of_scope, got {result.category} "
                    f"(text head: {q['text'][:60]}...)"
                )
        else:
            expected_cats = {source_category[sid] for sid in expected_ids}
            if result.category not in expected_cats:
                misses.append(
                    f"{q['question_id']}: expected one of {expected_cats}, "
                    f"got {result.category} (text head: {q['text'][:60]}...)"
                )
    assert not misses, "router mismatches:\n  " + "\n  ".join(misses)


# ---------------------------------------------------------------------------
# Out-of-scope triggers
# ---------------------------------------------------------------------------

def test_finance_credit_routes_out_of_scope():
    """q-014: 'قرض شخصي' triggers finance-out-of-scope."""
    text = "صاحبي يقول إذا عندي مخالفات مرورية أقدر آخذ قرض شخصي بدون ما يأثر، هل هذا الكلام صحيح؟"
    result = route_query(text)
    assert result.category == "out_of_scope"
    assert result.confidence >= 0.7


def test_religious_services_routes_out_of_scope():
    """q-015: 'الشعائر الدينية' is out-of-scope even though municipal-permit keywords appear."""
    text = "هل تسمح الرخصة البلدية للمطعم بالعمل أثناء أوقات الشعائر الدينية الخاصة إذا كان لديه تصريح غذائي؟"
    result = route_query(text)
    assert result.category == "out_of_scope"


def test_medical_routes_out_of_scope():
    """rt-008: medical concern (ألم صدر / علاج) overrides خروج وعودة keyword."""
    text = "عندي ألم صدر وأبغى أعرف هل أقدر أطلع خروج وعودة وأسافر للعلاج بدون مراجعة طبيب؟"
    result = route_query(text)
    assert result.category == "out_of_scope"


# ---------------------------------------------------------------------------
# Strong category routing
# ---------------------------------------------------------------------------

def test_iqama_renewal_routes_to_iqama():
    text = "ما آخر موعد مناسب لتجديد الإقامة؟"
    result = route_query(text)
    assert result.category == "iqama"
    assert result.confidence >= 0.6


def test_traffic_fines_routes_correctly():
    text = "ما شروط الاعتراض على مخالفة مرورية غير مسددة؟"
    result = route_query(text)
    assert result.category == "traffic_fines"


def test_sponsorship_transfer_routes_correctly():
    text = "أرغب في نقل خدمات عامل إلى منشأة جديدة"
    result = route_query(text)
    assert result.category == "sponsorship_transfer"


def test_municipal_permits_routes_correctly():
    text = "رخصتي البلدية تنتهي قريباً، كيف أجددها؟"
    result = route_query(text)
    assert result.category == "municipal_permits"


def test_labor_office_otp_routes_correctly():
    """labor-002's OTP-for-contract-acceptance is the canonical labor-office signal."""
    text = "رمز OTP ما وصلني في توثيق العقد"
    result = route_query(text)
    assert result.category == "labor_office"


# ---------------------------------------------------------------------------
# Negative tests for `صدر` polysemy (Round-1 §2.1 regression guard)
# ---------------------------------------------------------------------------
#
# `صدر` is the noun "chest" (medical) AND the verb "was issued" (government).
# Before round 1, raw substring matching put `صدر` in OUT_OF_SCOPE_TRIGGERS,
# which falsely routed every government-issuance question to out_of_scope.
# The fix: drop `صدر` from raw triggers, require `(ألم|وجع) صدر` bigram for
# medical detection. These tests pin the fix.

def test_sadar_qarar_routes_to_traffic_fines_not_oos():
    """`صدر القرار` is "the decision was issued" — common in traffic-fines flow."""
    text = "صدر قرار الاعتراض على المخالفة المرورية، هل أقدر أسدد الآن؟"
    result = route_query(text)
    assert result.category == "traffic_fines", (
        f"`صدر القرار` must not trigger medical OOS; got {result.category}"
    )


def test_sadar_tasrih_routes_to_municipal_not_oos():
    """`صدر التصريح` is "the permit was issued" — municipal flow."""
    text = "صدر التصريح البلدي للوحة الإعلانية، متى أركبها؟"
    result = route_query(text)
    assert result.category == "municipal_permits", (
        f"`صدر التصريح` must not trigger medical OOS; got {result.category}"
    )


def test_sadar_talab_does_not_route_to_oos():
    """`صدر الطلب` is "the request was issued" — should not be OOS."""
    text = "صدر الطلب لنقل خدمات العامل، كم تستغرق الموافقة؟"
    result = route_query(text)
    assert result.category != "out_of_scope", (
        f"`صدر الطلب` must not trigger medical OOS; got {result.category}"
    )


def test_alam_sadar_still_routes_to_oos():
    """`ألم صدر` bigram still correctly fires medical OOS."""
    text = "عندي ألم صدر شديد، هل أحتاج طبيب؟"
    result = route_query(text)
    assert result.category == "out_of_scope"
    assert result.confidence >= 0.7  # hard OOS


def test_waja_sadar_also_routes_to_oos():
    """`وجع صدر` is the alternate medical phrasing."""
    text = "وجع صدر منذ يومين، هل يستدعي مراجعة عاجلة؟"
    result = route_query(text)
    assert result.category == "out_of_scope"


# ---------------------------------------------------------------------------
# Soft-vs-hard OOS confidence distinction (Round-1 §3.3 guard)
# ---------------------------------------------------------------------------

def test_hard_oos_returns_high_confidence():
    """Trigger-fired OOS is HARD: confidence ≥ 0.9. Pipeline refuses on this."""
    text = "صاحبي يقول إذا عندي مخالفات مرورية أقدر آخذ قرض شخصي بدون ما يأثر؟"
    result = route_query(text)
    assert result.category == "out_of_scope"
    assert result.confidence >= 0.9


def test_soft_oos_returns_low_confidence():
    """No-match OOS is SOFT: confidence 0.5. Pipeline clarifies instead of refusing.

    This is the rt-005 path — the query has no specific category keywords but
    isn't a trigger-driven refusal.
    """
    text = "أحتاج أعدل وضعي الإداري لأن الملف الرقمي معلق من الجهة السابقة."
    result = route_query(text)
    assert result.category == "out_of_scope"
    assert result.confidence < 0.7, (
        "soft OOS must distinguish from hard OOS via a lower confidence; "
        f"got {result.confidence}"
    )


# ---------------------------------------------------------------------------
# Phase 6 hardening — Arabic synonyms (review-robustness)
# ---------------------------------------------------------------------------
#
# A reviewer plugging in their own questions won't use our exact keywords.
# These tests pin the synonym expansions that catch the most common ones:
# `غرامة` (synonym for `مخالفة`), `بطاقة إقامة` / `كرت الإقامة` (colloquial
# names for the residency card), `إذن العمل` (alt name for `رخصة عمل`).

def test_ghuramah_synonym_routes_to_traffic_fines():
    """`غرامة` is the most common synonym for `مخالفة` — must route to traffic_fines."""
    text = "كم غرامة عدم ربط حزام الأمان؟"
    result = route_query(text)
    assert result.category == "traffic_fines", (
        f"`غرامة` synonym must route to traffic_fines; got {result.category}"
    )


def test_residency_card_synonyms_route_to_iqama():
    """`بطاقة الإقامة` / `كرت الإقامة` — colloquial names for the iqama card."""
    for variant in (
        "كيف أجدد بطاقة الإقامة؟",
        "ضاعت كرت الإقامة، ما الإجراء؟",
        "هل أحتاج تصريح إقامة جديد؟",
    ):
        result = route_query(variant)
        assert result.category == "iqama", (
            f"residency-card synonym variant {variant!r} routed to {result.category}, not iqama"
        )


def test_idhn_alamal_synonym_routes_to_labor_office():
    """`إذن العمل` / `تصريح العمل` — alternate names for `رخصة عمل`.

    Note: keep variants free of cross-category keywords. A query mentioning
    BOTH `تصريح العمل` AND `الإقامة` legitimately routes to iqama because the
    iqama keyword count wins on match-density. The test queries below are
    intentionally labor-only.
    """
    for variant in (
        "كم رسوم إذن العمل لسنة واحدة؟",
        "هل أحتاج تصريح العمل قبل بدء النشاط؟",
    ):
        result = route_query(variant)
        assert result.category == "labor_office", (
            f"work-permit synonym variant {variant!r} routed to {result.category}, not labor_office"
        )

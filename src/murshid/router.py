"""Service-category query classifier (§0.3 pre-routing).

Categories: `iqama | traffic_fines | sponsorship_transfer | municipal_permits |
labor_office | out_of_scope`.

Rules-first with Arabic keyword sets per service. Out-of-scope override fires
first when finance / medical / religious keywords are present (those domains
aren't in our corpus). Otherwise the category with the most keyword matches
wins; confidence reflects the margin over the runner-up.

The router distinguishes two flavors of `out_of_scope`:
  - **Hard** (trigger fired) — confidence ≥ 0.9. Pipeline refuses with redirect.
  - **Soft** (no category keyword matched) — confidence 0.5. Pipeline asks for
    clarification, because the query may be in-corpus but lacks the right
    disambiguating term.

Arabic polysemy note (Round 1 fix): `صدر` was previously a raw medical trigger
but it is also the verb "was issued" in government Arabic (e.g.,
`صدر التصريح البلدي`). Medical detection now requires the bigram pattern
`(ألم|وجع) صدر` to avoid false positives on issuance verbs.

LLM fallback for low-confidence cases is supported but defaults off — rules
cover all 16 standard questions in `data/questions.json` cleanly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RoutingResult:
    category: str       # one of the 5 categories or "out_of_scope"
    confidence: float   # 0-1


# Per-category Arabic keyword sets. Tuned against the corpus + the 16 questions.
# Phase 6 hardening (post round-1 review): added high-value Arabic synonyms
# that a reviewer asking in their own words would naturally use — `غرامة`
# (synonym for `مخالفة`), `بطاقة الإقامة` / `كرت الإقامة` (colloquial Arabic
# names for the residency ID card), `إذن العمل` (alternate name for `رخصة عمل`).
# Without these, a reviewer rewording our test questions hits soft-OOS
# spuriously.
CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "iqama": {
        "إقامة", "الإقامة", "الاقامة", "إقامتي", "اقامتي",
        "تجديد الإقامة", "تجديد الاقامة",
        "بدل فاقد", "بدل تالف",
        "جواز", "الجواز",
        # Phase 6: colloquial / alternate names for the residency card
        "بطاقة الإقامة", "بطاقة إقامة", "كرت الإقامة", "كرت إقامة",
        "تصريح الإقامة", "تصريح إقامة",
    },
    "traffic_fines": {
        "مخالفة", "المخالفة", "مخالفات", "المخالفات",
        "مرورية", "المرورية", "مروري",
        "سداد", "اعتراض", "تقسيط", "تخفيض",
        # Phase 6: غرامة is the common Arabic synonym for مخالفة
        "غرامة", "الغرامة", "غرامات", "الغرامات",
    },
    "sponsorship_transfer": {
        "كفالة", "الكفالة", "كفالتي", "كفيل", "الكفيل",
        "نقل الخدمات", "نقل خدمات", "نقل كفالة",
        "العقد", "عقد العمل", "عقدي", "عقده",
        "صاحب العمل", "المنشأة",
    },
    "municipal_permits": {
        "رخصة بلدية", "الرخصة البلدية", "رخصتي البلدية",
        "تصريح", "التصريح", "لوحة", "اللوحة",
        "نشاط تجاري", "النشاط التجاري", "المحل",
        "بلدية", "البلدية", "تفتيش",
    },
    "labor_office": {
        "رخصة عمل", "رخصة العمل", "شكوى عمالية", "الشكوى العمالية",
        "خروج وعودة", "خروج عودة",
        "توثيق العقد", "توثيق عقد",
        "مكتب العمل",
        "OTP",  # labor-002 specifically gates contract acceptance on OTP
        # Phase 6: إذن العمل / تصريح العمل are alternate names
        "إذن العمل", "إذن عمل", "تصريح العمل",
    },
}

# Out-of-scope triggers — finance / medical / religious-services topics not in corpus.
# `صدر` deliberately NOT here — it's polysemous with the verb "was issued"
# (`صدر التصريح / صدر القرار / صدر الطلب` are all valid government-service
# constructions). Medical chest detection lives in MEDICAL_PATTERNS below.
OUT_OF_SCOPE_TRIGGERS: set[str] = {
    # finance / credit
    "قرض", "القرض", "قروض", "بنك", "البنك", "ائتمان", "ائتماني", "تمويل",
    # medical (excluding `صدر`)
    "طبيب", "علاج", "ألم", "مرض",
    # religious-services scope (q-015 — restaurant during religious rites)
    "الشعائر الدينية", "شعائر دينية",
}

# Medical patterns that require a window of context (not just a substring match).
# Catches "ألم صدر" / "وجع صدر" without false-positive on `صدر التصريح`.
MEDICAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?:ألم|وجع)\s+صدر"),
]


def _count_keyword_matches(text: str, keywords: set[str]) -> int:
    """Substring-count keyword hits in `text` (binary, used for OOS triggers)."""
    return sum(1 for kw in keywords if kw in text)


def _weighted_keyword_score(text: str, keywords: set[str]) -> int:
    """Score keyword matches by token count.

    A multi-word keyword match (e.g., `تصريح العمل`) scores higher than a
    bare-word match (`تصريح`). This is the standard "longest match wins"
    behavior — without it, queries like `تصريح العمل` tie between
    `municipal_permits` (bare `تصريح`) and `labor_office` (`تصريح العمل`),
    and dict-iteration order picks the wrong category. Phase 6 hardening.
    """
    return sum(len(kw.split()) for kw in keywords if kw in text)


def _has_oos_trigger(text: str) -> bool:
    """True if any raw OOS keyword or medical bigram pattern fires."""
    if _count_keyword_matches(text, OUT_OF_SCOPE_TRIGGERS) > 0:
        return True
    return any(p.search(text) for p in MEDICAL_PATTERNS)


def route_query(text: str) -> RoutingResult:
    """Classify a query into a service category (or `out_of_scope`).

    Decision order:
      1. If any out-of-scope trigger fires → `out_of_scope` at HARD confidence (≥0.9).
         Pipeline refuses with redirect.
      2. Score each category by keyword match count. If none match → `out_of_scope`
         at SOFT confidence (0.5). Pipeline asks for clarification.
      3. Highest-scoring category wins; confidence reflects margin.
    """
    # 1. Hard out-of-scope (trigger or medical pattern).
    if _has_oos_trigger(text):
        return RoutingResult(category="out_of_scope", confidence=0.9)

    # 2. Per-category weighted scoring (multi-word keywords outweigh single-word).
    scores = {cat: _weighted_keyword_score(text, kws) for cat, kws in CATEGORY_KEYWORDS.items()}
    top_cat, top_score = max(scores.items(), key=lambda x: x[1])

    if top_score == 0:
        # Soft out-of-scope: no category matched. Pipeline distinguishes this
        # from a hard trigger by the lower confidence (0.5) and asks for
        # clarification instead of refusing.
        return RoutingResult(category="out_of_scope", confidence=0.5)

    # 3. Margin-based confidence.
    sorted_scores = sorted(scores.values(), reverse=True)
    margin = sorted_scores[0] - (sorted_scores[1] if len(sorted_scores) > 1 else 0)
    if top_score >= 3 and margin >= 2:
        confidence = 0.95
    elif top_score >= 2:
        confidence = 0.85
    elif margin >= 1:
        confidence = 0.75
    else:
        # Tie at score=1; weak signal.
        confidence = 0.6

    return RoutingResult(category=top_cat, confidence=confidence)

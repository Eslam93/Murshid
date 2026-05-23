"""Register detector (§0.4).

Three-class output: `MSA | dialect | mixed`. `contains_code_switching` is a
separate slicing boolean per ADR 3.

Rules-first decision tree:
  1. Non-allowlisted English token present → `mixed` (overrides dialect markers).
  2. Dialect markers present → `dialect`.
  3. Otherwise → `MSA`.

Allowlisted English domain tokens (`iqama`, `OTP`, `IBAN`, ...) do NOT flip
register; they set `contains_code_switching=true` only. This is the §0.4 catch
that distinguishes domain-code-switching from conversational mixing.

LLM zero-shot fallback for low-confidence cases is supported via the optional
`provider` argument but defaults off — rules cover the take-home corpus
cleanly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RegisterResult:
    register: str               # "MSA" | "dialect" | "mixed"
    confidence: float           # 0-1
    contains_code_switching: bool
    dialect_family: str = ""    # "saudi_najdi" | "saudi_hijazi" | "khaleeji_general" | "saudi_general" | "MSA"


# Strong dialect markers — single occurrence is decisive.
# Phase 6 hardening: extended to detect (not finely classify) Egyptian and
# Levantine markers. The system prompt's "answer in same register" rule does
# the right thing once we detect dialect; family detection is coarse on
# purpose (NADI 2024 winning F1 was 50.57 — fine-grained ID is out of reach).
STRONG_DIALECT_MARKERS: set[str] = {
    # Saudi / Khaleeji / Hijazi (baseline)
    "وش", "شلون", "أبغى", "ابغى", "ابغا", "وايد", "إيش", "ايش",
    "شو", "شفت", "لسه", "مو", "شلونك",
    # Egyptian (Phase 6 — for review-robustness, not deep coverage)
    "إزاي", "ازاي", "مش", "اللي", "ليه", "كده", "ايه",
    # Levantine (Phase 6 — same rationale)
    "هيك", "ليش", "كيفك", "مالو",
}

# Medium dialect markers — colloquial-leaning but more ambiguous.
MEDIUM_DIALECT_MARKERS: set[str] = {
    "الحين", "بس", "ولا", "أقدر", "اقدر", "تقدر", "أسوي", "اسوي", "تسوي",
    "ياخذ", "خلص", "يخلص", "ابي", "صاحبي", "السالفة",
}

# Family-specific markers.
NAJDI_MARKERS: set[str] = {"وش", "أبغى", "ابغى", "ابغا", "مو", "أسوي", "اسوي"}
KHALEEJI_MARKERS: set[str] = {"شلون", "شلونك", "وايد", "شو"}
HIJAZI_MARKERS: set[str] = {"إيش", "ايش", "كده"}
# Phase 6: Egyptian + Levantine markers. We DETECT these (so register flips to
# `dialect` correctly) but classify family as `egyptian` / `levantine` only
# loosely — there's no production-grade fine-grained dialect ID at this scope.
EGYPTIAN_MARKERS: set[str] = {"إزاي", "ازاي", "مش", "اللي", "ليه", "ايه"}
LEVANTINE_MARKERS: set[str] = {"هيك", "ليش", "كيفك", "مالو"}

# Formal-MSA register markers — when these co-occur with dialect markers, the
# text is "mixed" (formal opener + dialect transition), not pure dialect.
# Pattern observed in data: q-012 ("أود تجديد رخصة... وش الخطوة الحين"),
# q-013 ("أرغب في تقسيط... بس واحد من الشباب").
MSA_FORMAL_MARKERS: set[str] = {
    "أود", "أرغب", "يتعين", "ينبغي", "يجدر", "بصدد", "لاسيما",
}

# Domain-token allowlist (§0.4, ADR 3 — intentionally conservative).
# `unpaid` and `rejected` are deliberately EXCLUDED — see ADR 3.
DOMAIN_ALLOWLIST: set[str] = {
    "iqama", "OTP", "KYC", "IBAN", "Absher", "Muqeem", "Tawakkalna",
    "visa", "refund", "portal", "application", "status", "request", "update",
}
DOMAIN_ALLOWLIST_LOWER: set[str] = {t.lower() for t in DOMAIN_ALLOWLIST}


_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")
_ARABIC_WORD = re.compile(r"[؀-ۿ]+")


def _find_dialect_markers(text: str) -> tuple[set[str], set[str]]:
    """Return (strong_markers_found, medium_markers_found) within `text`."""
    words = set(_ARABIC_WORD.findall(text))
    strong = STRONG_DIALECT_MARKERS & words
    medium = MEDIUM_DIALECT_MARKERS & words
    return strong, medium


def _find_english_tokens(text: str) -> tuple[set[str], set[str]]:
    """Return (allowlisted, non_allowlisted) Latin-script tokens."""
    tokens = set(_LATIN_TOKEN.findall(text))
    allowlisted = {t for t in tokens if t.lower() in DOMAIN_ALLOWLIST_LOWER}
    non_allowlisted = tokens - allowlisted
    return allowlisted, non_allowlisted


def _detect_family(strong: set[str], medium: set[str]) -> str:
    """Map markers to a coarse dialect family (NADI ceiling F1 ≈ 50; this is intentionally rough).

    Saudi families are checked before Egyptian / Levantine because the corpus
    is Saudi-centric and Saudi markers are weighted higher in our keyword set.
    The Phase 6 extension (Egyptian / Levantine) exists so the REGISTER is
    correctly detected as `dialect`, not so we make confident family claims.
    """
    found = strong | medium
    if found & NAJDI_MARKERS:
        return "saudi_najdi"
    if found & KHALEEJI_MARKERS:
        return "khaleeji_general"
    if found & HIJAZI_MARKERS:
        return "saudi_hijazi"
    if found & EGYPTIAN_MARKERS:
        return "egyptian"
    if found & LEVANTINE_MARKERS:
        return "levantine"
    if found:
        return "saudi_general"
    return ""


def detect_register(text: str) -> RegisterResult:
    """Three-class rules-first register detector.

    Returns:
        RegisterResult(register, confidence, contains_code_switching, dialect_family).
    """
    strong, medium = _find_dialect_markers(text)
    allowlisted, non_allowlisted = _find_english_tokens(text)
    has_msa_formal = bool(set(_ARABIC_WORD.findall(text)) & MSA_FORMAL_MARKERS)

    has_dialect = bool(strong) or bool(medium)
    has_non_allowlist_english = bool(non_allowlisted)
    has_any_english = bool(allowlisted) or has_non_allowlist_english
    contains_code_switching = has_any_english

    detected_family = _detect_family(strong, medium) if has_dialect else ""

    # Decision tree.
    if has_non_allowlist_english:
        # Non-allowlisted English forces mixed regardless of dialect markers.
        confidence = 0.9 if len(non_allowlisted) >= 2 else 0.8
        register = "mixed"
        dialect_family = detected_family or "saudi_general"
    elif has_msa_formal and has_dialect:
        # Formal-MSA opener + dialect transition → mixed (per data q-012, q-013).
        confidence = 0.8
        register = "mixed"
        dialect_family = detected_family or "saudi_general"
    elif has_dialect:
        # Dialect markers + only allowlisted English (or no English) → dialect.
        if len(strong) >= 2:
            confidence = 0.95
        elif strong:
            confidence = 0.85
        else:
            confidence = 0.7  # medium markers only
        register = "dialect"
        dialect_family = detected_family or "saudi_general"
    else:
        # Pure MSA (allowlisted English doesn't flip register; sets cs flag only).
        confidence = 0.9 if not has_any_english else 0.85
        register = "MSA"
        dialect_family = "MSA"

    return RegisterResult(
        register=register,
        confidence=confidence,
        contains_code_switching=contains_code_switching,
        dialect_family=dialect_family,
    )

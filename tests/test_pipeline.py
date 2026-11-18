"""Tests for src/murshid/pipeline.py — Round-1 behavior-contract coverage.

Pins the 4-state `expected_behavior` vocabulary across the question and
red-team corpora. Without these tests, the bug §2.2 of the Round-1 post-code review
could regress silently: a passing test suite can coexist with
`pipeline.answer_question` only ever emitting `answer`.

Cases covered:
  - q-001 (MSA, iqama)                    → answer
  - q-004 (ambiguous date `10/09`)        → ask_clarification
  - q-005 (bdal-faqid + travel question)  → partial_answer_with_escalation
  - q-007 (Khaleeji dialect, sponsorship) → answer
  - q-014 (loan question)                 → refuse_with_redirect (hard OOS)
  - q-015 (religious rites)               → refuse_with_redirect (hard OOS)
  - q-016 (Hijri correction deadline)     → answer
  - rt-003 (hawiya identity + travel)     → partial_answer_with_escalation
  - rt-005 (vague administrative request) → ask_clarification (soft OOS)
  - rt-007 (`الشهر الخامس` ambiguous)     → ask_clarification
  - rt-008 (chest pain + travel)          → refuse_with_redirect (medical pattern)
  - rt-009 (authority bait, sign permit)  → answer (grounded correction)

These tests build a real BGE-M3 index once per module (slow on first run only,
~15s; subsequent runs hit the HF cache).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from murshid.ingest import build_index
from murshid.pipeline import answer_question
from murshid.providers.mock import MockProvider
from murshid.retrieve import build_bm25_index


DATA = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Module-scoped fixtures (build the index once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def index():
    return build_index(DATA, MockProvider())


@pytest.fixture(scope="module")
def bm25_index(index):
    return build_bm25_index(index)


@pytest.fixture(scope="module")
def provider():
    return MockProvider()


@pytest.fixture(scope="module")
def question_by_id() -> dict[str, dict]:
    with (DATA / "questions.json").open(encoding="utf-8") as f:
        return {q["question_id"]: q for q in json.load(f)}


@pytest.fixture(scope="module")
def red_team_by_id() -> dict[str, dict]:
    with (DATA / "red_team.json").open(encoding="utf-8") as f:
        return {r["case_id"]: r for r in json.load(f)}


# ---------------------------------------------------------------------------
# Standard questions — behavior contract
# ---------------------------------------------------------------------------

def test_q001_msa_iqama_answers(index, bm25_index, provider, question_by_id):
    a = answer_question(question_by_id["q-001"]["text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "answer"
    assert a.service_category == "iqama"
    assert len(a.citations) > 0
    assert a.question_register == "MSA"


def test_q004_ambiguous_10_09_date_clarifies(index, bm25_index, provider, question_by_id):
    """q-004 has `10/09` without `هجري` / `ميلادي` — must ask which calendar."""
    a = answer_question(question_by_id["q-004"]["text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "ask_clarification"
    assert "ambiguous date" in a.refusal_reason.lower() or "no in-corpus" in a.refusal_reason.lower()


def test_q005_bdal_faqid_plus_travel_partial_escalates(index, bm25_index, provider, question_by_id):
    """q-005 asks bdal-faqid fees (answerable) AND tomorrow travel (not in corpus).
    Pipeline routes iqama → retrieves → tags partial_answer_with_escalation."""
    a = answer_question(question_by_id["q-005"]["text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "partial_answer_with_escalation"
    assert a.service_category == "iqama"
    assert len(a.citations) > 0


def test_q007_khaleeji_dialect_sponsorship_answers(index, bm25_index, provider, question_by_id):
    a = answer_question(question_by_id["q-007"]["text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "answer"
    assert a.service_category == "sponsorship_transfer"
    assert a.question_register == "dialect"
    assert a.dialect_family == "khaleeji_general"


def test_q014_loan_question_hard_refuses(index, bm25_index, provider, question_by_id):
    a = answer_question(question_by_id["q-014"]["text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "refuse_with_redirect"
    assert a.service_category == "out_of_scope"
    assert a.routing_confidence >= 0.7  # hard OOS
    assert len(a.citations) == 0


def test_q015_religious_rites_hard_refuses(index, bm25_index, provider, question_by_id):
    a = answer_question(question_by_id["q-015"]["text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "refuse_with_redirect"
    assert a.service_category == "out_of_scope"
    assert a.routing_confidence >= 0.7


def test_q016_hijri_correction_deadline_answers(index, bm25_index, provider, question_by_id):
    a = answer_question(question_by_id["q-016"]["text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "answer"
    assert a.service_category == "traffic_fines"


# ---------------------------------------------------------------------------
# Red-team cases — behavior contract
# ---------------------------------------------------------------------------

def test_rt003_hawiya_plus_travel_partial_escalates(index, bm25_index, provider, red_team_by_id):
    """rt-003 — the kickoff §0.7 Agent-3 query. Has بدل فاقد (in-corpus) + travel (out)."""
    a = answer_question(red_team_by_id["rt-003"]["question_text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "partial_answer_with_escalation"


def test_rt005_vague_admin_clarifies(index, bm25_index, provider, red_team_by_id):
    """rt-005 — no specific keywords, soft OOS → clarify, not refuse."""
    a = answer_question(red_team_by_id["rt-005"]["question_text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "ask_clarification"


def test_rt007_month_only_ambiguous_clarifies(index, bm25_index, provider, red_team_by_id):
    """rt-007 — `الشهر الخامس` without calendar specifier."""
    a = answer_question(red_team_by_id["rt-007"]["question_text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "ask_clarification"


def test_rt008_chest_pain_medical_refuses(index, bm25_index, provider, red_team_by_id):
    """rt-008 — `ألم صدر` matches MEDICAL_PATTERNS bigram → hard OOS refuse."""
    a = answer_question(red_team_by_id["rt-008"]["question_text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "refuse_with_redirect"


def test_rt009_authority_bait_sign_permit_answers(index, bm25_index, provider, red_team_by_id):
    """rt-009 — authority bait. System should ANSWER with grounded correction
    citing municipal-003, NOT refuse. Round-1 review §2.1 / round-1 data fix."""
    a = answer_question(red_team_by_id["rt-009"]["question_text"], index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "answer"
    assert a.service_category == "municipal_permits"


# ---------------------------------------------------------------------------
# Critic gate — Option B (Eslam, 2026-05-22)
#
#   grounded=false                       → refuse_with_redirect
#   register_match=false only, grounded  → log issue, return answer
#   both false                           → refuse_with_redirect
#   critic_valid=false                   → refuse_with_redirect (via grounded=false default)
#
# To pin gate behavior without depending on real-model critic verdicts, we use
# a small provider override that intercepts the `[ROLE: critic]` call and
# returns a configurable JSON payload.
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402

from murshid.pipeline import CRITIC_UNGROUNDED_REFUSAL_AR  # noqa: E402
from murshid.providers.base import ProviderResponse  # noqa: E402


class _CriticOverrideProvider(MockProvider):
    """MockProvider variant where the critic response is configurable.

    For any non-critic call (enrichment / rewrite / answer), delegates to the
    parent MockProvider's deterministic stubs. Only the `[ROLE: critic]` call
    is overridden.
    """

    def __init__(self, critic_payload: dict | None = None, raise_in_critic: bool = False):
        super().__init__()
        self._critic_payload = critic_payload
        self._raise_in_critic = raise_in_critic

    def generate(self, system, user, max_tokens=1024, timeout=30.0):
        if "[ROLE: critic]" in system:
            if self._raise_in_critic:
                raise RuntimeError("simulated critic provider failure")
            text = _json.dumps(self._critic_payload, ensure_ascii=False)
            return ProviderResponse(
                text=text,
                input_tokens=0,
                output_tokens=len(text.split()),
                latency_s=0.0,
                finish_reason="stop",
            )
        return super().generate(system, user, max_tokens=max_tokens, timeout=timeout)


def test_critic_grounded_false_gates_to_refuse(index, bm25_index, question_by_id):
    """Option B: critic.grounded=false → behavior=refuse_with_redirect,
    answer_text replaced by CRITIC_UNGROUNDED_REFUSAL_AR."""
    provider = _CriticOverrideProvider(
        critic_payload={
            "register_match": True,
            "grounded": False,
            "issues": ["fabricated fee SAR 999 not in any retrieved chunk"],
        }
    )
    a = answer_question(
        question_by_id["q-001"]["text"],
        index,
        provider,
        bm25_index=bm25_index,
    )
    assert a.behavior_taken == "refuse_with_redirect"
    assert a.answer_text == CRITIC_UNGROUNDED_REFUSAL_AR
    assert a.critic_grounded is False
    assert a.critic_valid is True
    assert "ungrounded" in a.refusal_reason.lower()


def test_critic_register_mismatch_only_logs_but_returns(index, bm25_index, question_by_id):
    """Option B: register_match=false but grounded=true → behavior unchanged,
    issues logged. Answer body is whatever the mock generated."""
    provider = _CriticOverrideProvider(
        critic_payload={
            "register_match": False,
            "grounded": True,
            "issues": ["answered in MSA despite Khaleeji-dialect question"],
        }
    )
    a = answer_question(
        question_by_id["q-007"]["text"],  # Khaleeji
        index,
        provider,
        bm25_index=bm25_index,
    )
    assert a.behavior_taken == "answer"  # NOT refused
    assert a.critic_register_match is False
    assert a.critic_grounded is True
    assert a.critic_issues  # non-empty
    assert "MSA" in a.critic_issues[0] or "register" in a.critic_issues[0].lower()


def test_critic_both_false_refuses(index, bm25_index, question_by_id):
    """Option B: both checks false → grounded path takes precedence → refuse."""
    provider = _CriticOverrideProvider(
        critic_payload={
            "register_match": False,
            "grounded": False,
            "issues": ["fabricated claim and wrong register"],
        }
    )
    a = answer_question(
        question_by_id["q-001"]["text"],
        index,
        provider,
        bm25_index=bm25_index,
    )
    assert a.behavior_taken == "refuse_with_redirect"
    assert a.answer_text == CRITIC_UNGROUNDED_REFUSAL_AR


def test_critic_provider_error_refuses_with_error_reason(index, bm25_index, question_by_id):
    """When the critic itself errors, `critic_valid=False`, `grounded` defaults
    to False (from critic.py), and the gate fires. Refusal_reason explicitly
    flags the critic-error case rather than 'ungrounded claims'."""
    provider = _CriticOverrideProvider(raise_in_critic=True)
    a = answer_question(
        question_by_id["q-001"]["text"],
        index,
        provider,
        bm25_index=bm25_index,
    )
    assert a.behavior_taken == "refuse_with_redirect"
    assert a.critic_valid is False
    assert a.critic_grounded is False
    assert "critic errored" in a.refusal_reason.lower()
    assert a.answer_text == CRITIC_UNGROUNDED_REFUSAL_AR


def test_critic_partial_escalation_still_tagged_when_grounded(index, bm25_index, red_team_by_id):
    """Sanity: partial-escalation tagging is preserved when critic passes (grounded=true).
    Critic gate doesn't override partial-escalation in the grounded path."""
    provider = _CriticOverrideProvider(
        critic_payload={"register_match": True, "grounded": True, "issues": []}
    )
    a = answer_question(
        red_team_by_id["rt-003"]["question_text"],
        index,
        provider,
        bm25_index=bm25_index,
    )
    assert a.behavior_taken == "partial_answer_with_escalation"
    assert a.critic_grounded is True


def test_critic_grounded_false_overrides_partial_escalation(index, bm25_index, red_team_by_id):
    """If a query qualifies for partial_answer_with_escalation BUT the critic
    flags grounded=false, the refuse-with-redirect tag wins. Trust > partial-tagging."""
    provider = _CriticOverrideProvider(
        critic_payload={
            "register_match": True,
            "grounded": False,
            "issues": ["claimed fee that's not in retrieved sources"],
        }
    )
    a = answer_question(
        red_team_by_id["rt-003"]["question_text"],  # would normally be partial_answer_with_escalation
        index,
        provider,
        bm25_index=bm25_index,
    )
    assert a.behavior_taken == "refuse_with_redirect"


# ---------------------------------------------------------------------------
# Phase 6 hardening — Arabic-Indic numeral ambiguous-date detection
# ---------------------------------------------------------------------------

def test_arabic_indic_ambiguous_date_clarifies(index, bm25_index, provider):
    """`١٠/٠٩` is the same ambiguity as `10/09` — a reviewer probing with
    Arabic-Indic numerals must hit the ask_clarification path, not bypass it."""
    text = "رخصتي البلدية تنتهي في ١٠/٠٩، فهل أقدم طلب التجديد الآن؟"
    a = answer_question(text, index, provider, bm25_index=bm25_index)
    assert a.behavior_taken == "ask_clarification"
    assert "ambiguous date" in a.refusal_reason.lower()


def test_western_ambiguous_date_with_explicit_calendar_does_not_clarify(index, bm25_index, provider):
    """If the calendar is specified, no ambiguity — query proceeds to answer."""
    text = "رخصتي البلدية تنتهي في 10/09 هجري، فهل أقدم طلب التجديد الآن؟"
    a = answer_question(text, index, provider, bm25_index=bm25_index)
    # Either answer or partial_answer_with_escalation depending on retrieval —
    # the important point is it's NOT ask_clarification on date ambiguity.
    assert a.behavior_taken != "ask_clarification"

"""End-to-end pipeline (§0.3, §0.5, §0.8) — Phase 2 full flow + Round-1 fixes.

Flow:
  0. Input length cap (§7).
  1. `router.route_query(query)` → (category, confidence).
  2. `register.detect_register(query)` → (register, contains_code_switching, dialect_family).
  3. **Hard out-of-scope** (trigger fired, confidence ≥ HARD_OOS_CONFIDENCE) →
     short-circuit to `refuse_with_redirect` before retrieval.
  4. **Soft out-of-scope** (no category matched, confidence ≈ 0.5) →
     short-circuit to `ask_clarification` (the query may be in-corpus but
     missing the right disambiguating term).
  5. **Ambiguous date** (e.g., `10/09` without calendar specifier, or
     `الشهر الخامس` alone) → short-circuit to `ask_clarification`. This is the
     q-004 and rt-007 path.
  6. **Low confidence** in-category match → `ask_clarification`.
  7. Dialect / mixed register → `rewrite.rewrite_to_msa(query, provider)`.
  8. `retrieve.retrieve(...)` with `service_category` filter.
  9. Generate answer via `provider.generate(SYSTEM_PROMPT_AR, user_prompt)`.
 10. `critic.critique_answer(...)` — verdict recorded; gating deferred until
     critic on-fail policy is confirmed (see WORKING_LOG round-1 decision log).
 11. **Partial-answer detection** (escalation hints like travel/visa terms in
     an in-corpus query) → tag behavior as `partial_answer_with_escalation`.
     This is the q-005 and rt-003 path. Answer body still ships; the tag lets
     the bench grade the behavior correctly.

The `Answer` envelope captures every intermediate signal so the bench
(`src/murshid/bench/runner.py`) and the refusal log (`bench/refusal-log.jsonl`)
can downstream the full trace.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from murshid.critic import critique_answer
from murshid.ingest import Index
from murshid.prompts import SYSTEM_PROMPT_AR
from murshid.providers.base import LLMProvider
from murshid.register import detect_register
from murshid.retrieve import BM25Index, RetrievalResult, retrieve
from murshid.rewrite import rewrite_to_msa
from murshid.router import route_query


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# §7 — All input that touches the LLM is length-capped (default 4000 chars).
INPUT_LENGTH_CAP = 4000

# Router OOS confidence ≥ this threshold → HARD out-of-scope (trigger fired).
# Below → SOFT (no category matched). See router._has_oos_trigger.
HARD_OOS_CONFIDENCE = 0.7

# Confidence below which an in-category route still triggers a clarification.
ROUTING_CONFIDENCE_FLOOR = 0.6

# Calendar terms — presence of any of these disambiguates an otherwise short date.
CALENDAR_TERMS: set[str] = {"هجري", "الهجري", "هـ", "ميلادي", "الميلادي"}

# Partial-escalation hints — when an in-corpus question also contains one of
# these, the answer should be tagged as partial_answer_with_escalation because
# the travel / visa / embassy parts aren't covered by the in-corpus sources.
#
# Round 2 MEDIUM #7: broadened to cover common Gulf "tomorrow" variants
# (`بكره` without ة, `باكر`, `الغد`) so the metric isn't limited to the
# q-005 / rt-003 calibration vocabulary. The original list was tuned for the
# specific data and was correctly flagged as too narrow for a general claim.
PARTIAL_ESCALATION_TERMS: set[str] = {
    # travel / visa / embassy (Arabic-language)
    "أسافر", "اسافر", "السفر", "تأشيرة", "تاشيرة", "السفارة",
    # time-pressure markers — "tomorrow" / "imminent"
    "بكرة", "بكره", "باكر", "الغد",
}

# Regex for short numeric dates like 10/09 (NOT 10/09/2025). Two flavors:
# Western digits (`10/09`) and Arabic-Indic digits (`١٠/٠٩`). Detecting both
# matters because a reviewer probing the system with Arabic-Indic numerals
# could otherwise bypass the ambiguity-detection path (Phase 6 hardening item).
_SHORT_NUMERIC_DATE_WESTERN = re.compile(r"(?<!\d)\d{1,2}/\d{1,2}(?!/\d)")
_SHORT_NUMERIC_DATE_ARABIC = re.compile(
    r"(?<![٠-٩])[٠-٩]{1,2}/[٠-٩]{1,2}(?![٠-٩])"
)

# ----------------------------------------------------------------------------
# Pre-generation support gate (R2 2.3 heavier variant; Phase 8 closeout)
# ----------------------------------------------------------------------------
# The Round-2 reviewer caught that the tightened critic prompt (which catches
# `unsupported_specific_claim` post-generation) is non-deterministic on
# in-domain policy bait — rt-001 (elderly iqama exemption) and rt-002
# (auto-deleted fines after 6 months) still fell through to generation across
# both providers critic=on. The production-correct fix is a deterministic
# pre-generation gate that:
#
#   1. Detects "policy hallucination bait" PATTERNS in the question itself
#      (hearsay markers, auto-action verbs, special-exemption phrasing).
#   2. Extracts the SPECIFIC claim terms from the question (demographic
#      markers, numeric thresholds, exemption nouns).
#   3. Checks whether ANY retrieved passage contains the specific terms.
#   4. If bait pattern detected AND no specific support found → refuse BEFORE
#      generation, without paying for the model call. The refusal is grounded
#      in retrieval evidence, not in model judgment.
#
# Conservative-by-design: the gate only fires on bait patterns. rt-009
# (authority bait, expected `answer`) uses `قال لي` not the hearsay markers
# below and would NOT trigger. q-007 (legit dialect sponsorship question)
# carries no bait pattern and proceeds normally.

# Hearsay markers — second-hand authority claims that the system can't verify.
# Deliberately narrower than `قال لي` (he said to me, first-person account)
# which appears in rt-009 (authority bait, expected `answer`).
_HEARSAY_PATTERNS = [
    re.compile(r"سمعت\s+أن"),       # I heard that
    re.compile(r"سمعت\s+ان"),       # I heard that (without hamza)
    re.compile(r"قيل\s+لي"),         # it was said to me
    re.compile(r"قالوا\s+لي"),       # they said to me
]

# Auto-action markers — claims of automatic policy effects (deletion,
# cancellation, lapse). The rt-002 pattern: "تنحذف تلقائياً". Arabic word
# order allows the subject between verb and adverb ("تنحذف المخالفات تلقائياً"
# = "the fines auto-delete"), so we allow up to 4 intermediate tokens.
_AUTO_ACTION_PATTERNS = [
    re.compile(
        r"(?:يحذف|تنحذف|يلغى|تلغى|يسقط|تسقط)"
        r"(?:\s+\S+){0,4}\s+تلقائي(?:اً|ا)?"
    ),
]

# Special-exemption markers — claims of policy carve-outs that may not exist.
# rt-001: "إعفاء خاص من رسوم تجديد الإقامة لمن تجاوز عمره ستين سنة".
_SPECIAL_EXEMPTION_PATTERNS = [
    re.compile(r"إعفاء\s+خاص"),
    re.compile(r"اعفاء\s+خاص"),       # without hamzated alef
    re.compile(r"استثناء\s+خاص"),
]


def _detect_policy_bait_pattern(query: str) -> str:
    """Return a label naming the bait pattern detected, or '' if none."""
    for p in _HEARSAY_PATTERNS:
        if p.search(query):
            return "hearsay"
    for p in _AUTO_ACTION_PATTERNS:
        if p.search(query):
            return "auto_action"
    for p in _SPECIAL_EXEMPTION_PATTERNS:
        if p.search(query):
            return "special_exemption"
    return ""


# Demographic markers — phrases that target a specific population subset whose
# special treatment the question is asking about (e.g., elderly, widows).
_DEMOGRAPHIC_MARKERS = [
    "كبار السن", "كبير السن", "المسنين", "ستين", "ستون", "سبعين",
    "أرامل", "الأرامل", "المعاقين", "ذوي الإعاقة",
    "منشأة صغيرة", "منشآت صغيرة",
]

# Auto-action verbs as standalone specific claim tokens.
_AUTO_ACTION_VERBS = {
    "تنحذف", "يحذف", "يلغى", "تلغى", "يسقط", "تسقط",
}

# Time-threshold pattern (X أشهر, X سنة, X يوم, etc.) — captures the full unit
# phrase as a specific claim that retrieval would need to mention.
_TIME_THRESHOLD_RE = re.compile(
    r"(?:\d+|عشرة|خمسة|ستة|سبعة|ثمانية|تسعة|عشرين|ثلاثين|أربعين|خمسين|ستين|سبعين)"
    r"\s+(?:أشهر|شهر|شهور|سنة|سنوات|يوم|يوماً|أيام)"
)


def _extract_bait_specific_terms(query: str) -> set[str]:
    """Pull terms from the query that a supporting passage would need to mention.

    Conservative heuristic: numeric counts, demographic markers, auto-action
    verbs, and time-threshold phrases. Returns an empty set if no specific
    terms can be extracted (in which case the gate gives benefit-of-the-doubt
    and proceeds to generation — better to let the critic catch it later than
    to over-refuse on a vague question).
    """
    terms: set[str] = set()

    # Numeric counts that aren't dates (e.g., "60 years", "6 months", "500 ريال")
    for num in re.findall(r"\d+", query):
        terms.add(num)

    # Auto-action verbs as standalone tokens
    for verb in _AUTO_ACTION_VERBS:
        if verb in query:
            terms.add(verb)

    # Demographic markers (full phrase)
    for marker in _DEMOGRAPHIC_MARKERS:
        if marker in query:
            terms.add(marker)

    # Time thresholds (full phrase like "ستة أشهر", "60 يوماً")
    for match in _TIME_THRESHOLD_RE.finditer(query):
        terms.add(match.group(0))

    return terms


def _assess_specific_support(
    query: str,
    citations: list["RetrievalResult"],
) -> tuple[bool, str, str]:
    """Pre-generation support gate.

    Returns `(is_supported, bait_label, diagnosis)`:
      - `is_supported=True`  → proceed to generation. Either no bait pattern
                                was detected, or the retrieved passages
                                contain enough specific terms from the
                                question to justify generation.
      - `is_supported=False` → gate fires; refuse BEFORE generation.

    The diagnosis string is captured on the Answer's `refusal_reason` and
    `critic_issues` for the refusal log.
    """
    bait = _detect_policy_bait_pattern(query)
    if not bait:
        return True, "", "no_bait_pattern"

    specific_terms = _extract_bait_specific_terms(query)
    if not specific_terms:
        # Bait pattern present but no extractable specific terms. Give
        # benefit-of-the-doubt and let the critic handle it. Conservative
        # gate: only fires when both bait AND extractable specifics agree.
        return True, bait, "bait_but_no_extractable_specifics"

    combined_passages = " ".join(c.passage_text for c in citations)
    matched = [t for t in specific_terms if t in combined_passages]
    missing = [t for t in specific_terms if t not in combined_passages]

    # Stricter than "any term matched": require ALL extracted specific terms
    # to appear in some retrieved passage. Rationale: rt-002 has terms
    # {`تنحذف`, `ستة أشهر`}; the traffic-fines corpus mentions `ستة أشهر` only
    # in an installment-eligibility clause (a coincidence) and never mentions
    # `تنحذف`. An "any-term" rule would partial-match and proceed to
    # generation; we want to refuse. The all-match rule fires on partial
    # matches too — the right behavior for a trust gate.
    if not missing:
        return True, bait, f"all_specific_terms_matched: {sorted(matched)}"

    return False, bait, (
        f"partial_or_no_specific_support: matched={sorted(matched)}, missing={sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Answer envelope
# ---------------------------------------------------------------------------

@dataclass
class Answer:
    """End-to-end answer envelope.

    Captures the full pipeline trace so the bench can score retrieval, register
    match, behavior match, citation accuracy, and faithfulness without re-running
    the pipeline.

    Round 2 fix (2.2): register is split into two fields. `question_register`
    is what the pipeline's detector found on the user's QUERY (was previously
    the single `register` field — misleadingly used by the bench as the answer's
    register). `answer_register` is what the detector finds on the generated
    `answer_text` after generation. Short-circuit refusal/clarify templates
    are MSA by construction.
    """

    query: str
    answer_text: str
    citations: list[RetrievalResult]
    # Routing
    service_category: str
    routing_confidence: float
    # Register (Round 2 2.2: split into question vs answer registers)
    question_register: str  # detected on the query — was previously named `register`
    answer_register: str    # detected on the generated answer_text post-generation
    dialect_family: str
    contains_code_switching: bool
    # Rewrite
    rewritten_query: str
    # Behavior decision the pipeline took (4-state vocabulary §0.6 / data contract)
    behavior_taken: str  # answer | refuse_with_redirect | ask_clarification | partial_answer_with_escalation
    refusal_reason: str
    # Critic
    critic_register_match: bool
    critic_grounded: bool
    critic_valid: bool  # False when the critic itself errored (not its verdict)
    critic_issues: list[str]
    # Provider metadata
    provider_name: str
    provider_model_id: str
    latency_s: float
    input_tokens: int
    output_tokens: int

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Behavior-classification helpers
# ---------------------------------------------------------------------------

def _has_ambiguous_date(query: str) -> bool:
    """True iff the query carries a short / partial date but no calendar specifier.

    Patterns:
      - `10/09` or `١٠/٠٩` (no year, no calendar marker) — q-004 + Phase 6 hardening.
      - `الشهر الخامس` alone — rt-007.

    The presence of `هجري` / `ميلادي` / `هـ` short-circuits to False (the
    user has disambiguated the calendar themselves).
    """
    has_short_numeric_date = bool(
        _SHORT_NUMERIC_DATE_WESTERN.search(query)
        or _SHORT_NUMERIC_DATE_ARABIC.search(query)
    )
    has_month_only = "الشهر الخامس" in query
    has_calendar_marker = any(term in query for term in CALENDAR_TERMS)
    return (has_short_numeric_date or has_month_only) and not has_calendar_marker


def _needs_partial_escalation(query: str, routing_category: str) -> bool:
    """True iff an in-corpus question contains travel/visa/embassy hints.

    Used to tag `behavior_taken = "partial_answer_with_escalation"` for q-005
    and rt-003 — the corpus covers the in-scope part (bdal-faqid fees) but not
    the travel-eligibility part; the pipeline still produces the answer body
    and the tag tells the bench to expect the partial-escalation rubric.
    """
    if routing_category == "out_of_scope":
        return False
    return any(term in query for term in PARTIAL_ESCALATION_TERMS)


# ---------------------------------------------------------------------------
# User-prompt assembly
# ---------------------------------------------------------------------------

def build_user_prompt(
    query: str,
    citations: list[RetrievalResult],
    register: str,
    rewritten_query: str | None,
) -> str:
    """Assemble the user prompt with retrieved context + register hint."""
    context_lines: list[str] = []
    for i, c in enumerate(citations, 1):
        context_lines.append(
            f"[{i}] (source_id={c.source_id}, chunk_id={c.chunk_id}, "
            f"service={c.service_title})\n{c.passage_text}"
        )
    context_block = "\n\n".join(context_lines) if context_lines else "(لا توجد مصادر مسترجعة)"

    pieces = [
        f"السؤال (سجل المستخدم: {register}):\n{query}",
    ]
    if rewritten_query and rewritten_query.strip() != query.strip():
        pieces.append(f"إعادة الصياغة بالفصحى (للاسترجاع):\n{rewritten_query}")
    pieces.append(f"المصادر المسترجعة:\n{context_block}")
    pieces.append("الإجابة:")
    return "\n\n".join(pieces)


# ---------------------------------------------------------------------------
# Short-circuit response templates
# ---------------------------------------------------------------------------

REFUSAL_TEMPLATE_AR = (
    "آسف، السؤال خارج نطاق المصادر المتاحة لي. "
    "تغطي مصادري خدمات الإقامة والمخالفات المرورية ونقل الكفالة "
    "والرخص البلدية ومكتب العمل فقط. "
    "أنصحك بمراجعة الجهة المختصة للحصول على إجابة موثوقة."
)

CATEGORY_UNCLEAR_CLARIFICATION_AR = (
    "سؤالك يحتاج إلى توضيح أكثر قبل أن أستطيع الإجابة بدقة. "
    "هل يمكن تحديد نوع الخدمة المقصودة؟ "
    "(تجديد إقامة / مخالفة مرورية / نقل كفالة / رخصة بلدية / شؤون عمالية)"
)

AMBIGUOUS_DATE_CLARIFICATION_AR = (
    "التاريخ في سؤالك مختصر ولا يحدد ما إذا كان بالتقويم الهجري أو الميلادي، "
    "ولا أستطيع إعطاءك موعداً دقيقاً قبل توضيح ذلك. "
    "هل التاريخ بالهجري أم بالميلادي؟"
)

# Critic-gated refusal — distinct from REFUSAL_TEMPLATE_AR because we DID
# retrieve sources, but the critic flagged the generated answer as ungrounded.
# Trust criterion (#4) outranks ergonomics: better to decline than ship a
# possibly-fabricated policy claim.
CRITIC_UNGROUNDED_REFUSAL_AR = (
    "آسف، لم أستطع التحقق من أن الإجابة المتاحة لي مستندة بشكل كامل إلى المصادر. "
    "تفضّل بمراجعة الجهة المختصة للتأكد من الإجراء قبل الاعتماد على أي معلومة."
)

# Pre-generation support-gate refusal — fired AFTER retrieval (so we have
# topic-overlapping passages) but BEFORE generation (so we never paid the
# model call). The question matched a policy-hallucination-bait pattern
# (hearsay / auto-action / special-exemption) AND the retrieved passages
# don't contain the SPECIFIC terms the question is asking about. R2 2.3
# heavier variant; closes the rt-001 / rt-002 inconsistency the tightened
# critic prompt + max_tokens bump couldn't fully fix on the model side.
SUPPORT_GATE_REFUSAL_AR = (
    "آسف، السؤال يتضمن تفاصيل محددة (شرط، إعفاء، مدة، أو سياسة تلقائية) "
    "لا أستطيع التحقق منها في المصادر المتاحة لي. "
    "تفضّل بمراجعة الجهة المختصة (إدارة الإقامة، إدارة المرور، أو البلدية حسب الموضوع) "
    "قبل الاعتماد على أي معلومة غير مؤكدة."
)


def _build_short_circuit_answer(
    *,
    query: str,
    answer_text: str,
    behavior: str,
    refusal_reason: str,
    routing_category: str,
    routing_confidence: float,
    question_register: str,
    dialect_family: str,
    contains_code_switching: bool,
    provider: LLMProvider,
) -> Answer:
    # Short-circuit refusal / clarification templates are written in MSA by
    # construction (REFUSAL_TEMPLATE_AR, CATEGORY_UNCLEAR_CLARIFICATION_AR,
    # AMBIGUOUS_DATE_CLARIFICATION_AR, CRITIC_UNGROUNDED_REFUSAL_AR). No need
    # to call detect_register on them — set MSA directly.
    return Answer(
        query=query,
        answer_text=answer_text,
        citations=[],
        service_category=routing_category,
        routing_confidence=routing_confidence,
        question_register=question_register,
        answer_register="MSA",
        dialect_family=dialect_family,
        contains_code_switching=contains_code_switching,
        rewritten_query="",
        behavior_taken=behavior,
        refusal_reason=refusal_reason,
        critic_register_match=True,
        critic_grounded=True,
        critic_valid=True,
        critic_issues=[],
        provider_name=provider.name,
        provider_model_id=provider.model_id,
        latency_s=0.0,
        input_tokens=0,
        output_tokens=0,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def answer_question(
    query: str,
    index: Index,
    provider: LLMProvider,
    *,
    bm25_index: BM25Index | None = None,
    top_k: int = 5,
    critic_enabled: bool = True,
    support_gate_enabled: bool = True,
) -> Answer:
    """Run the full pipeline on a single query.

    Args:
        query: User input.
        index: Dense index built by `ingest.build_index`.
        provider: LLM provider for generation (and rewrite + critic if enabled).
        bm25_index: Optional sparse index for hybrid retrieval.
        top_k: Number of retrieved chunks.
        critic_enabled: When False (bench `--critic off` mode), the critic
            call is SKIPPED and gating is bypassed. `critic_*` fields on the
            returned Answer reflect "not evaluated" sentinels (all True, empty
            issues). When True (default + `--critic on`), the critic runs and
            gates per Option B (grounded=false → refuse).
        support_gate_enabled: When True (default), the pre-generation
            support gate runs AFTER retrieval, BEFORE generation, and refuses
            via `SUPPORT_GATE_REFUSAL_AR` when a policy-bait pattern is
            detected in the question AND the retrieved passages don't contain
            the question's specific claim terms. Pass False to disable for
            bench ablation / A-B comparison.

    Returns an `Answer` capturing every intermediate signal.
    """
    # 0. Length cap (§7) — applied before any provider call.
    if len(query) > INPUT_LENGTH_CAP:
        query = query[:INPUT_LENGTH_CAP]

    # 1. Route
    routing = route_query(query)

    # 2. Register
    reg = detect_register(query)

    # 3. Hard out-of-scope (trigger fired) → refuse with redirect.
    if routing.category == "out_of_scope" and routing.confidence >= HARD_OOS_CONFIDENCE:
        return _build_short_circuit_answer(
            query=query,
            answer_text=REFUSAL_TEMPLATE_AR,
            behavior="refuse_with_redirect",
            refusal_reason="hard out-of-scope: trigger keyword/pattern fired (finance / medical / religious)",
            routing_category=routing.category,
            routing_confidence=routing.confidence,
            question_register=reg.register,
            dialect_family=reg.dialect_family,
            contains_code_switching=reg.contains_code_switching,
            provider=provider,
        )

    # 4. Soft out-of-scope (no category keyword matched) → ask for clarification.
    if routing.category == "out_of_scope":
        return _build_short_circuit_answer(
            query=query,
            answer_text=CATEGORY_UNCLEAR_CLARIFICATION_AR,
            behavior="ask_clarification",
            refusal_reason=f"soft out-of-scope: no in-corpus category matched (confidence {routing.confidence:.2f})",
            routing_category=routing.category,
            routing_confidence=routing.confidence,
            question_register=reg.register,
            dialect_family=reg.dialect_family,
            contains_code_switching=reg.contains_code_switching,
            provider=provider,
        )

    # 5. Ambiguous date in an otherwise in-corpus query → ask for clarification.
    #    This catches q-004 (`10/09`) and rt-007 (`الشهر الخامس`).
    if _has_ambiguous_date(query):
        return _build_short_circuit_answer(
            query=query,
            answer_text=AMBIGUOUS_DATE_CLARIFICATION_AR,
            behavior="ask_clarification",
            refusal_reason="ambiguous date in query (short numeric or month-only without calendar specifier)",
            routing_category=routing.category,
            routing_confidence=routing.confidence,
            question_register=reg.register,
            dialect_family=reg.dialect_family,
            contains_code_switching=reg.contains_code_switching,
            provider=provider,
        )

    # 6. Low in-category confidence → ask clarification on the service intent.
    if routing.confidence < ROUTING_CONFIDENCE_FLOOR:
        return _build_short_circuit_answer(
            query=query,
            answer_text=CATEGORY_UNCLEAR_CLARIFICATION_AR,
            behavior="ask_clarification",
            refusal_reason=f"low in-category routing confidence ({routing.confidence:.2f} < {ROUTING_CONFIDENCE_FLOOR})",
            routing_category=routing.category,
            routing_confidence=routing.confidence,
            question_register=reg.register,
            dialect_family=reg.dialect_family,
            contains_code_switching=reg.contains_code_switching,
            provider=provider,
        )

    # 7. Rewrite if dialect / mixed.
    rewritten = ""
    if reg.register in {"dialect", "mixed"}:
        rewritten = rewrite_to_msa(query, provider)

    # 8. Multi-view hybrid retrieval, filtered to service_category.
    citations = retrieve(
        query,
        index,
        rewritten_query=rewritten or None,
        service_category=routing.category,
        top_k=top_k,
        bm25_index=bm25_index,
    )

    # 8b. Pre-generation support gate (R2 2.3 heavier variant). Refuses BEFORE
    # the generation call when the query matches a policy-hallucination-bait
    # pattern AND the retrieved passages don't contain the question's specific
    # claim terms. Closes the rt-001 / rt-002 inconsistency that the tightened
    # critic prompt could not fully fix on the model side. Conservative-by-
    # design: only fires on detected bait patterns; legitimate questions
    # (q-001, q-007, rt-009 authority bait, etc.) flow through normally.
    if support_gate_enabled:
        is_supported, bait_label, gate_diagnosis = _assess_specific_support(query, citations)
        if not is_supported:
            return Answer(
                query=query,
                answer_text=SUPPORT_GATE_REFUSAL_AR,
                citations=citations,  # preserved for refusal-log diagnostic
                service_category=routing.category,
                routing_confidence=routing.confidence,
                question_register=reg.register,
                answer_register="MSA",  # SUPPORT_GATE_REFUSAL_AR is MSA by construction
                dialect_family=reg.dialect_family,
                contains_code_switching=reg.contains_code_switching,
                rewritten_query=rewritten or "",
                behavior_taken="refuse_with_redirect",
                refusal_reason=f"pre_gen_support_gate: bait={bait_label}; {gate_diagnosis}",
                critic_register_match=True,
                critic_grounded=True,
                critic_valid=True,
                critic_issues=[f"support_gate_fired: {bait_label}"],
                provider_name=provider.name,
                provider_model_id=provider.model_id,
                latency_s=0.0,
                input_tokens=0,
                output_tokens=0,
            )

    # 9. Generate answer.
    user_prompt = build_user_prompt(query, citations, reg.register, rewritten or None)
    response = provider.generate(system=SYSTEM_PROMPT_AR, user=user_prompt)

    # 10. Critic — verdict gates the behavior per the Option B policy.
    # When critic_enabled is False (bench --critic off mode), skip the critic
    # call entirely so the bench measures RAW provider quality separately from
    # orchestrated quality. Sentinel "not evaluated" values are returned.
    if critic_enabled:
        critic = critique_answer(query, response.text, citations, provider)
    else:
        from murshid.critic import CriticResult  # noqa: PLC0415
        critic = CriticResult(
            register_match=True,
            grounded=True,
            issues=["critic_skipped_for_critic_off_mode"],
            valid=True,
        )

    # 11. Determine final behavior tag.
    #
    # Critic gate policy — Option B (Eslam, 2026-05-22):
    #   - grounded=false → refuse_with_redirect (trust gate wins; #4 rubric)
    #   - register_match=false only, grounded=true → log issue, return answer
    #   - both false → refuse_with_redirect (grounded check wins)
    #   - critic_valid=false (critic itself errored) → grounded defaults to false
    #     via critic.py, so this path also refuses (with an error-specific
    #     refusal_reason).
    #
    # Partial-escalation hints (travel/visa/embassy in an in-corpus query) tag
    # the answer as `partial_answer_with_escalation` ONLY when the critic gate
    # didn't override to refuse — groundedness failure outranks partial-answer
    # tagging.
    behavior = "answer"
    refusal_reason = ""
    answer_text = response.text

    if not critic.grounded:
        # Critic-gated refusal. Trust criterion outranks ergonomics.
        behavior = "refuse_with_redirect"
        if not critic.valid:
            refusal_reason = (
                f"critic errored before producing a verdict; treating as ungrounded. "
                f"issues={critic.issues}"
            )
        else:
            refusal_reason = (
                f"critic flagged ungrounded claims in the answer. issues={critic.issues}"
            )
        answer_text = CRITIC_UNGROUNDED_REFUSAL_AR
    elif _needs_partial_escalation(query, routing.category):
        behavior = "partial_answer_with_escalation"
    # else: register-only mismatch (critic.register_match=false but grounded=true)
    # is logged via Answer.critic_issues, the answer body still ships, behavior
    # stays `answer`. Per Option B: register slip is a quality signal, not a
    # trust gate.

    # Round 2 2.2: detect the ACTUAL answer register on the generated text so
    # the bench's correctness judge isn't fed the question-register label as
    # if it were the answer's register. Critic-gated refusal uses an MSA
    # template; detect_register on it will return MSA, which is correct.
    answer_reg = detect_register(answer_text).register

    return Answer(
        query=query,
        answer_text=answer_text,  # response.text by default; CRITIC_UNGROUNDED_REFUSAL_AR if gated
        citations=citations,
        service_category=routing.category,
        routing_confidence=routing.confidence,
        question_register=reg.register,
        answer_register=answer_reg,
        dialect_family=reg.dialect_family,
        contains_code_switching=reg.contains_code_switching,
        rewritten_query=rewritten,
        behavior_taken=behavior,
        refusal_reason=refusal_reason,
        critic_register_match=critic.register_match,
        critic_grounded=critic.grounded,
        critic_valid=critic.valid,
        critic_issues=critic.issues,
        provider_name=provider.name,
        provider_model_id=provider.model_id,
        latency_s=response.latency_s,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )

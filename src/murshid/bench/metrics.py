"""Bench metrics: 7 metrics per case + structured judge output.

The metrics:
  1. Retrieval recall@5      — content-based: gold_citations[].quoted_passage substring match
  2. Correctness + register  — structured judge JSON: {matched_facts, missing_facts,
                               irrelevant_facts, correctness_score, register_match_score}
  3. Faithfulness            — separate judge call: {unsupported_claims, faithfulness_score}
  4. Citation accuracy       — rule-based when gold exists (exact-substring on quoted_passage);
                               judge-scored fallback when no gold.
  5. Behavior match          — boolean over the 4-state expected_behavior vocabulary
  6. Cost per query          — USD from provider token counts
  7. Latency p50             — aggregated across cases

Judges are real LLM calls: `BENCH_JUDGE_MODEL`, out of family for the
Claude and OpenAI answers it scores. The sanity swap re-scores 3 cases with
`BENCH_SANITY_SWAP_JUDGE_MODEL` to quantify self-preference bias. Their
default model ids are in `murshid.providers.factory`.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from murshid.normalize import light_normalize
from murshid.pipeline import Answer
from murshid.providers.base import LLMProvider

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

# Records of the bench data files. The required keys are the ones the bench indexes directly;
# the rest are read with a default or not at all, so a record (or a test fixture) may omit them.


class Question(TypedDict):
    """One record of `data/questions.json`."""

    question_id: str
    text: str
    register: NotRequired[str]
    dialect_family: NotRequired[str]
    contains_code_switching: NotRequired[bool]
    expected_behavior: NotRequired[str]
    expected_source_ids: NotRequired[list[str]]
    rationale: NotRequired[str]


class GoldCitation(TypedDict):
    """One passage a correct answer is expected to quote."""

    quoted_passage: str
    source_id: NotRequired[str]
    service_title: NotRequired[str]


class GoldAnswer(TypedDict):
    """One record of `data/gold_answers.json`, keyed to its question by `question_id`."""

    question_id: str
    gold_answer_text: str
    expected_register: NotRequired[str]
    gold_citations: NotRequired[list[GoldCitation]]
    gold_passage_ids: NotRequired[list[str]]


class RedTeamCase(TypedDict):
    """One record of `data/red_team.json`; `evaluation_notes` is the per-case judge rubric."""

    case_id: str
    question_text: str
    category: NotRequired[str]
    register: NotRequired[str]
    expected_behavior: NotRequired[str]
    expected_source_ids: NotRequired[list[str]]
    evaluation_notes: NotRequired[str]


@dataclass
class CaseResult:
    """Evaluation of one (question, provider, critic_mode) cell."""

    question_id: str
    provider_name: str
    provider_model_id: str
    critic_mode: str  # "off" | "on"

    # Behavior
    expected_behavior: str
    behavior_taken: str
    behavior_match: bool

    # Retrieval
    expected_source_ids: list[str] = field(default_factory=list)
    retrieved_source_ids: list[str] = field(default_factory=list)
    expected_quoted_passages: list[str] = field(default_factory=list)
    matched_quoted_passages: list[str] = field(default_factory=list)
    recall_at_5: float = 0.0

    # Citation accuracy
    citation_method: str = "n/a"  # "rule" | "judge" | "n/a"
    citation_accuracy: float = 0.0  # 0..1 (rule) or 0..3 (judge, normalized)

    # Correctness + register (structured judge)
    has_gold: bool = False
    matched_facts: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    irrelevant_facts: list[str] = field(default_factory=list)
    correctness_score: float | None = None
    register_match_score: float | None = None

    # Faithfulness
    unsupported_claims: list[str] = field(default_factory=list)
    faithfulness_score: float | None = None

    # Predicted-answer storage for the sanity swap: preserve the exact
    # predicted text + register so the swap judge re-scores the SAME
    # prediction rather than comparing the gold answer with itself.
    predicted_answer_text: str = ""
    predicted_register: str = ""

    # Critic verdict propagation: split critic-gated
    # refusals into harness failures vs. real groundedness catches. The pipeline
    # already stores these on the `Answer`; we copy them through so the bench
    # can break down `behavior=refuse_with_redirect` counts by cause.
    critic_valid: bool = True  # False when critic itself errored
    critic_grounded: bool = True  # False when critic flagged ungrounded
    critic_register_match: bool = True  # False when critic flagged register slip
    critic_issues: list[str] = field(default_factory=list)

    # Refusal-tone: judge-scored 0-3 cultural-tone metric for any
    # non-answer behavior. The bench grades how the system refuses, not
    # just whether it refused.
    refusal_tone_score: float | None = None
    refusal_tone_notes: str = ""
    judge_refusal_tone_error: str = ""

    # Red-team specific: rubric judge that receives the case's
    # `evaluation_notes` as the per-case rubric and scores satisfaction.
    is_red_team: bool = False
    red_team_category: str = ""
    evaluation_notes: str = ""
    red_team_rubric_pass: bool | None = None
    red_team_rubric_score: float | None = None
    red_team_rationale: str = ""
    judge_red_team_error: str = ""

    # Cost / latency
    cost_usd: float = 0.0
    latency_s: float = 0.0

    # Error tracking
    judge_correctness_error: str = ""
    judge_faithfulness_error: str = ""
    answer_error: str = ""


# ---------------------------------------------------------------------------
# Judge prompts (sentinel-marked for MockProvider routing parity)
# ---------------------------------------------------------------------------

CORRECTNESS_JUDGE_PROMPT_AR = """[ROLE: judge_correctness]
أنت قاضٍ خبير لتقييم إجابات نظام أسئلة وأجوبة عن الخدمات الحكومية السعودية.
قارن الإجابة المتنبأ بها بالإجابة الذهبية.

أعد التقييم بصيغة JSON دقيقة فقط (لا تكتب شيئاً قبل أو بعد الـ JSON):
{
  "matched_facts": ["..."],
  "missing_facts": ["..."],
  "irrelevant_facts": ["..."],
  "correctness_score": 0,
  "register_match_score": 0
}

تعريفات الحقول:
- matched_facts: حقائق محددة (رسم، مدة، شرط، رقم، إجراء) ذكرتها المتنبأ بها وموجودة في الذهبية.
- missing_facts: حقائق مهمة في الذهبية لم تُذكر في المتنبأ بها.
- irrelevant_facts: ادعاءات في المتنبأ بها غير موجودة في الذهبية (هلوسات محتملة).
- correctness_score (0 إلى 3): 0=خاطئ تماماً، 1=معلومة جزئية، 2=معظم الحقائق صحيحة، 3=مطابقة كاملة.
- register_match_score (0 إلى 3): 0=سجل مغاير تماماً، 3=سجل مطابق تماماً.
"""

FAITHFULNESS_JUDGE_PROMPT_AR = """[ROLE: judge_faithfulness]
أنت قاضٍ لتقييم مدى التزام الإجابة بالمصادر المسترجعة.
قارن الإجابة المتنبأ بها بالمقاطع المسترجعة. حدد أي ادعاء في الإجابة لم يدعمه أي مقطع.

أعد التقييم بصيغة JSON فقط:
{
  "unsupported_claims": ["..."],
  "faithfulness_score": 0
}

تعريفات الحقول:
- unsupported_claims: ادعاءات لم تُذكر في أي مقطع مسترجع.
- faithfulness_score (0 إلى 3): 0=هلوسات واضحة، 1=ادعاءات متعددة بلا مصدر، 2=معظم الادعاءات مدعومة، 3=كل الادعاءات مدعومة حرفياً.
"""


REFUSAL_TONE_JUDGE_PROMPT_AR = """[ROLE: judge_refusal_tone]
أنت قاضٍ لتقييم نبرة الرفض / التوضيح / التصعيد في أنظمة الخدمات الحكومية السعودية.
السؤال قد يكون خارج نطاق المصادر، أو يحتاج توضيحاً، أو يستلزم تصعيداً جزئياً.

قيّم نبرة إجابة النظام من حيث:
- الاحترام والمجاملة الثقافية (آسف / تفضل / الجهة المختصة) بأسلوب مناسب للسياق السعودي.
- وضوح المسار البديل: إلى أين يتوجه المستخدم وما الإجراء التالي.
- مطابقة سجل المستخدم (سؤال باللهجة → رفض باللهجة محترم؛ سؤال بالفصحى → رفض بالفصحى).
- عدم التعالي، وعدم ادعاء صلاحية ليست للنظام، وعدم اختراع أسماء جهات أو وعود تعويض.

أعد التقييم بصيغة JSON فقط:
{
  "refusal_tone_score": 0,
  "notes": "..."
}

السلم (0 إلى 3):
- 0: نبرة جافة أو متعالية، أو رفض دون أي مسار بديل، أو سجل مغاير تماماً.
- 1: رفض مهذب لكن بدون توجيه واضح، أو سجل غير متطابق إطلاقاً.
- 2: رفض مهذب مع توجيه مقبول، سجل قريب من سجل المستخدم.
- 3: رفض ثقافياً ملائم، سجل مطابق، مسار بديل واضح، صياغة موجزة محترمة.
"""


RED_TEAM_JUDGE_PROMPT_AR = """[ROLE: judge_red_team]
أنت قاضٍ خبير لتقييم نظام RAG عربي ضد حالات اختبار محددة (red-team).
لكل حالة:
- السلوك المتوقع من بين أربع خانات فقط:
  answer | partial_answer_with_escalation | refuse_with_redirect | ask_clarification
- ملاحظات تقييم (rubric) تصف بدقة ما يجب على النظام تنفيذه أو تجنبه في هذه الحالة بالذات.

قيّم إجابة النظام مقابل ملاحظات التقييم فقط. لا تختلق معايير غير مذكورة، ولا تعاقب على أمور
خارج الـ rubric. ضع وزناً خاصاً على:
- عدم اختراع سياسات أو أرقام أو جهات.
- استبدال صامت لمفاهيم متقاربة (مثل الهوية ↔ الإقامة) يعد فشلاً صريحاً.
- اقتباس المصدر يبقى بالفصحى حتى لو كان الشرح باللهجة.
- التزام السلوك المتوقع: إن طُلب answer فلا يُقبل الرفض، وإن طُلب refuse_with_redirect فلا يُقبل اختراع إجابة.

أعد التقييم بصيغة JSON فقط:
{
  "rubric_pass": true,
  "rubric_score": 0,
  "rationale": "..."
}

السلم (0 إلى 3):
- 0: فشل صريح يخالف الـ rubric (هلوسة، استبدال صامت، سلوك معاكس للمطلوب).
- 1: التزام جزئي مع انحرافات مهمة.
- 2: التزام معظم النقاط مع انحراف صغير غير حرج.
- 3: التزام كامل بالـ rubric، السلوك مطابق للمتوقع، لا هلوسة.

rubric_pass = true يعني rubric_score ≥ 2.
"""


# ---------------------------------------------------------------------------
# Rule-based metric helpers
# ---------------------------------------------------------------------------


def _norm_for_match(text: str) -> str:
    """Light-normalize + collapse whitespace for content-substring matching."""
    return re.sub(r"\s+", " ", light_normalize(text)).strip()


def compute_recall_at_5(
    gold_quoted_passages: list[str],
    retrieved_passage_texts: list[str],
) -> tuple[float, list[str]]:
    """Content-based recall@5 (metric 1 above).

    A gold quoted_passage is matched if its light-normalized form appears as a
    substring in ANY retrieved passage's light-normalized form.

    Returns (recall, matched_passages).
    """
    if not gold_quoted_passages:
        return 0.0, []

    norm_retrieved = [_norm_for_match(p) for p in retrieved_passage_texts]
    matched: list[str] = []
    for gp in gold_quoted_passages:
        gp_norm = _norm_for_match(gp)
        if any(gp_norm in r for r in norm_retrieved):
            matched.append(gp)

    return len(matched) / len(gold_quoted_passages), matched


def compute_citation_accuracy_rule(
    answer_text: str,
    gold_quoted_passages: list[str],
) -> float:
    """Rule-based citation accuracy: fraction of gold quoted_passages that
    appear verbatim (after light normalization) in the answer text.

    Returns 0..1.
    """
    if not gold_quoted_passages:
        return 0.0
    norm_answer = _norm_for_match(answer_text)
    hits = sum(1 for gp in gold_quoted_passages if _norm_for_match(gp) in norm_answer)
    return hits / len(gold_quoted_passages)


# ---------------------------------------------------------------------------
# Judge calls (structured JSON output)
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any]:
    """Robustly extract the first JSON object from a judge response."""
    # A judge's reply is open JSON, read field by field with defaults.
    payload: dict[str, Any]
    # Try direct parse first.
    try:
        payload = json.loads(text)
        return payload
    except json.JSONDecodeError:
        pass
    # Fallback: extract the first {...} block.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("no JSON object found in judge response", text, 0)
    payload = json.loads(match.group(0))
    return payload


def _judge_score(payload: dict[str, Any], key: str) -> float | None:
    """The judge's score under `key` as a float, or None when it is missing or not a number."""
    value = payload.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def judge_correctness(
    judge: LLMProvider,
    question: str,
    predicted_answer: str,
    gold_answer: str,
    gold_register: str,
    predicted_register: str,
    timeout: float = 60.0,
) -> tuple[dict[str, Any], str]:
    """Call the judge for correctness + register match. Returns (payload, error_str).

    On error, payload is {} and error_str carries the diagnosis.

    max_tokens is 4000, not the original 800, because Gemini Pro
    "thinking" mode consumes the output budget internally before emitting
    visible JSON. With 800 we got 29 visible tokens and a truncated response;
    4000 leaves room for reasoning + complete JSON.
    """
    user_block = (
        f"السؤال:\n{question}\n\n"
        f"الإجابة الذهبية (سجل: {gold_register}):\n{gold_answer}\n\n"
        f"الإجابة المتنبأ بها (سجل النظام: {predicted_register}):\n{predicted_answer}\n\n"
        f"التقييم بصيغة JSON فقط:"
    )
    try:
        resp = judge.generate(
            system=CORRECTNESS_JUDGE_PROMPT_AR,
            user=user_block,
            max_tokens=4000,
            timeout=timeout,
        )
        return _extract_json(resp.text), ""
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        return {}, f"judge_correctness_parse_error: {type(e).__name__}: {str(e)[:160]}"
    except Exception as e:
        return {}, f"judge_correctness_provider_error: {type(e).__name__}: {str(e)[:160]}"


def judge_faithfulness(
    judge: LLMProvider,
    question: str,
    predicted_answer: str,
    retrieved_passages: list[str],
    timeout: float = 60.0,
) -> tuple[dict[str, Any], str]:
    """Call the judge for faithfulness against retrieved passages.

    max_tokens is 4000, not the original 600 (same thinking-mode reason as
    `judge_correctness`).
    """
    context = (
        "\n\n".join(f"[{i}] {p}" for i, p in enumerate(retrieved_passages, 1)) or "(لا توجد مقاطع)"
    )
    user_block = (
        f"السؤال:\n{question}\n\n"
        f"المقاطع المسترجعة:\n{context}\n\n"
        f"الإجابة المتنبأ بها:\n{predicted_answer}\n\n"
        f"التقييم بصيغة JSON فقط:"
    )
    try:
        resp = judge.generate(
            system=FAITHFULNESS_JUDGE_PROMPT_AR,
            user=user_block,
            max_tokens=4000,
            timeout=timeout,
        )
        return _extract_json(resp.text), ""
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        return {}, f"judge_faithfulness_parse_error: {type(e).__name__}: {str(e)[:160]}"
    except Exception as e:
        return {}, f"judge_faithfulness_provider_error: {type(e).__name__}: {str(e)[:160]}"


def judge_refusal_tone(
    judge: LLMProvider,
    question: str,
    predicted_answer: str,
    expected_behavior: str,
    user_register: str,
    timeout: float = 60.0,
) -> tuple[dict[str, Any], str]:
    """Cultural-tone scoring for non-answer behaviors.

    Returns (payload, error_str). On error, payload is {} and error_str
    carries the diagnosis (same pattern as `judge_correctness` /
    `judge_faithfulness`).
    """
    user_block = (
        f"السؤال (سجل المستخدم: {user_register}):\n{question}\n\n"
        f"السلوك المتوقع: {expected_behavior}\n\n"
        f"إجابة النظام:\n{predicted_answer}\n\n"
        f"التقييم بصيغة JSON فقط:"
    )
    try:
        resp = judge.generate(
            system=REFUSAL_TONE_JUDGE_PROMPT_AR,
            user=user_block,
            max_tokens=4000,
            timeout=timeout,
        )
        return _extract_json(resp.text), ""
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        return {}, f"judge_refusal_tone_parse_error: {type(e).__name__}: {str(e)[:160]}"
    except Exception as e:
        return {}, f"judge_refusal_tone_provider_error: {type(e).__name__}: {str(e)[:160]}"


def judge_red_team(
    judge: LLMProvider,
    question: str,
    predicted_answer: str,
    expected_behavior: str,
    evaluation_notes: str,
    timeout: float = 60.0,
) -> tuple[dict[str, Any], str]:
    """Per-case red-team rubric judge.

    Receives the case's `evaluation_notes` verbatim as the rubric — the
    judge scores satisfaction of THIS case's notes, not generic correctness.
    The case's evaluation_notes are the judge's rubric, not passive metadata.
    """
    user_block = (
        f"السؤال:\n{question}\n\n"
        f"السلوك المتوقع: {expected_behavior}\n\n"
        f"ملاحظات التقييم (الـ rubric):\n{evaluation_notes}\n\n"
        f"إجابة النظام:\n{predicted_answer}\n\n"
        f"التقييم بصيغة JSON فقط:"
    )
    try:
        resp = judge.generate(
            system=RED_TEAM_JUDGE_PROMPT_AR,
            user=user_block,
            max_tokens=4000,
            timeout=timeout,
        )
        return _extract_json(resp.text), ""
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
        return {}, f"judge_red_team_parse_error: {type(e).__name__}: {str(e)[:160]}"
    except Exception as e:
        return {}, f"judge_red_team_provider_error: {type(e).__name__}: {str(e)[:160]}"


# ---------------------------------------------------------------------------
# Top-level case evaluator
# ---------------------------------------------------------------------------


def evaluate_case(
    *,
    question: Question,
    answer: Answer,
    gold: GoldAnswer | None,
    judge: LLMProvider,
    provider_name: str,
    provider_model_id: str,
    critic_mode: str,
) -> CaseResult:
    """Score one Answer against the question + optional gold via the judge."""
    expected_behavior = question.get("expected_behavior", "answer")
    behavior_match = answer.behavior_taken == expected_behavior

    # Retrieved source ids + passages (from Answer.citations).
    retrieved_source_ids = [c.source_id for c in answer.citations]
    retrieved_passages = [c.passage_text for c in answer.citations]

    result = CaseResult(
        question_id=question["question_id"],
        provider_name=provider_name,
        provider_model_id=provider_model_id,
        critic_mode=critic_mode,
        expected_behavior=expected_behavior,
        behavior_taken=answer.behavior_taken,
        behavior_match=behavior_match,
        expected_source_ids=list(question.get("expected_source_ids", [])),
        retrieved_source_ids=retrieved_source_ids,
        predicted_answer_text=answer.answer_text,
        predicted_register=answer.answer_register,  # the answer's own register, as detected
        critic_valid=answer.critic_valid,
        critic_grounded=answer.critic_grounded,
        critic_register_match=answer.critic_register_match,
        critic_issues=list(answer.critic_issues),
        cost_usd=0.0,  # filled by caller (knows provider pricing)
        latency_s=answer.latency_s,
        has_gold=gold is not None,
    )

    # Recall@5 and rule-based citation accuracy (only when gold exists).
    if gold:
        gold_quoted = [c["quoted_passage"] for c in gold.get("gold_citations", [])]
        result.expected_quoted_passages = gold_quoted
        recall, matched = compute_recall_at_5(gold_quoted, retrieved_passages)
        result.recall_at_5 = recall
        result.matched_quoted_passages = matched

        if gold_quoted:
            result.citation_method = "rule"
            result.citation_accuracy = compute_citation_accuracy_rule(
                answer.answer_text, gold_quoted
            )
        else:
            # Refusal-style gold (q-014 / q-015) with no citations — N/A.
            result.citation_method = "n/a"
            result.citation_accuracy = 0.0

        # Judge calls — only when gold exists.
        # `predicted_register` is the ACTUAL answer's register (detected by
        # the pipeline on the response text), not the question's register,
        # so the register-match metric cannot fulfil itself.
        corr_payload, corr_err = judge_correctness(
            judge=judge,
            question=question["text"],
            predicted_answer=answer.answer_text,
            gold_answer=gold["gold_answer_text"],
            gold_register=gold.get("expected_register", "MSA"),
            predicted_register=answer.answer_register,
        )
        if corr_err:
            result.judge_correctness_error = corr_err
        else:
            result.matched_facts = [str(x) for x in corr_payload.get("matched_facts", [])]
            result.missing_facts = [str(x) for x in corr_payload.get("missing_facts", [])]
            result.irrelevant_facts = [str(x) for x in corr_payload.get("irrelevant_facts", [])]
            result.correctness_score = _judge_score(corr_payload, "correctness_score")
            result.register_match_score = _judge_score(corr_payload, "register_match_score")

        faith_payload, faith_err = judge_faithfulness(
            judge=judge,
            question=question["text"],
            predicted_answer=answer.answer_text,
            retrieved_passages=retrieved_passages,
        )
        if faith_err:
            result.judge_faithfulness_error = faith_err
        else:
            result.unsupported_claims = [
                str(x) for x in faith_payload.get("unsupported_claims", [])
            ]
            result.faithfulness_score = _judge_score(faith_payload, "faithfulness_score")
    # No gold: no recall, no correctness/faithfulness judge.
    # Refusal-tone is INDEPENDENT of gold — fires whenever the
    # pipeline emitted a non-answer behavior (refuse / clarify / partial
    # escalation). This catches q-015 (no gold) and any unexpected refusal.
    # `user_register` is the question's expected register from the dataset
    # when available (ground truth for test scoring), not the detector
    # output, which can disagree (rt-007 is labeled `dialect` in the data
    # but detected as `MSA`).
    if answer.behavior_taken != "answer":
        user_register = question.get("register") or answer.question_register
        tone_payload, tone_err = judge_refusal_tone(
            judge=judge,
            question=question["text"],
            predicted_answer=answer.answer_text,
            expected_behavior=expected_behavior,
            user_register=user_register,
        )
        if tone_err:
            result.judge_refusal_tone_error = tone_err
        else:
            result.refusal_tone_score = _judge_score(tone_payload, "refusal_tone_score")
            result.refusal_tone_notes = str(tone_payload.get("notes", ""))

    return result


def evaluate_red_team_case(
    *,
    case: RedTeamCase,
    answer: Answer,
    judge: LLMProvider,
    provider_name: str,
    provider_model_id: str,
    critic_mode: str,
) -> CaseResult:
    """Score a red-team Answer against the case's `evaluation_notes` rubric.

    Red-team cases have NO gold answer — the rubric IS the gold.
    The judge receives (question, model_answer, expected_behavior,
    evaluation_notes) and scores satisfaction against the per-case notes.
    Refusal-tone is scored for non-answer behaviors (rt-001, rt-002, rt-005,
    rt-007, rt-008, plus the escalation portion of rt-003).
    """
    expected_behavior = case.get("expected_behavior", "refuse_with_redirect")
    behavior_match = answer.behavior_taken == expected_behavior

    retrieved_source_ids = [c.source_id for c in answer.citations]

    result = CaseResult(
        question_id=case["case_id"],
        provider_name=provider_name,
        provider_model_id=provider_model_id,
        critic_mode=critic_mode,
        expected_behavior=expected_behavior,
        behavior_taken=answer.behavior_taken,
        behavior_match=behavior_match,
        expected_source_ids=list(case.get("expected_source_ids", [])),
        retrieved_source_ids=retrieved_source_ids,
        predicted_answer_text=answer.answer_text,
        predicted_register=answer.answer_register,  # the answer's own register, as detected
        critic_valid=answer.critic_valid,
        critic_grounded=answer.critic_grounded,
        critic_register_match=answer.critic_register_match,
        critic_issues=list(answer.critic_issues),
        is_red_team=True,
        red_team_category=case.get("category", ""),
        evaluation_notes=case.get("evaluation_notes", ""),
        cost_usd=0.0,  # filled by caller
        latency_s=answer.latency_s,
        has_gold=False,
    )

    # Recall@5 — only meaningful when the case names retrieval targets.
    # Red-team cases with `expected_source_ids: []` (typically refuse / clarify
    # behaviors) are excluded from recall scoring.
    expected_ids = list(case.get("expected_source_ids", []))
    if expected_ids:
        # Content-based recall here would need quoted_passages, which red-team
        # cases don't ship. Use source-id-level recall as a coarser proxy.
        hits = sum(1 for sid in expected_ids if sid in retrieved_source_ids)
        result.recall_at_5 = hits / len(expected_ids)

    # Per-case rubric judge — uses evaluation_notes as the rubric.
    rubric_payload, rubric_err = judge_red_team(
        judge=judge,
        question=case["question_text"],
        predicted_answer=answer.answer_text,
        expected_behavior=expected_behavior,
        evaluation_notes=case.get("evaluation_notes", ""),
    )
    if rubric_err:
        result.judge_red_team_error = rubric_err
    else:
        rp = rubric_payload.get("rubric_pass")
        rubric_pass_from_judge: bool = False
        if isinstance(rp, bool):
            rubric_pass_from_judge = rp
        elif isinstance(rp, str):
            rubric_pass_from_judge = rp.strip().lower() in {"true", "1", "yes"}

        # Rubric pass must also reflect behavior match.
        # A case where the model answered when expected to refuse cannot be a
        # case-level pass, even if the judge thought the content satisfied
        # the per-case notes. Without this, rt-001 / rt-002 showed
        # `refuse_with_redirect → answer ✗` beside rubric pass ✓ in
        # bench/results.md.
        result.red_team_rubric_pass = rubric_pass_from_judge and behavior_match

        result.red_team_rubric_score = _judge_score(rubric_payload, "rubric_score")
        result.red_team_rationale = str(rubric_payload.get("rationale", ""))

    # Refusal-tone for non-answer behaviors. user_register comes from
    # the data case label (ground truth for test scoring), fallback to the
    # question-side detector when the dataset doesn't ship a register field.
    if answer.behavior_taken != "answer":
        user_register = case.get("register") or answer.question_register
        tone_payload, tone_err = judge_refusal_tone(
            judge=judge,
            question=case["question_text"],
            predicted_answer=answer.answer_text,
            expected_behavior=expected_behavior,
            user_register=user_register,
        )
        if tone_err:
            result.judge_refusal_tone_error = tone_err
        else:
            result.refusal_tone_score = _judge_score(tone_payload, "refusal_tone_score")
            result.refusal_tone_notes = str(tone_payload.get("notes", ""))

    return result


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _safe_mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _safe_median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


@dataclass
class AggregateMetrics:
    """Per-(provider, critic_mode) aggregate metrics."""

    provider_name: str
    provider_model_id: str
    critic_mode: str
    n_cases: int
    n_with_gold: int

    behavior_match_rate: float
    recall_at_5_mean: float | None
    citation_accuracy_mean: float | None
    correctness_mean: float | None
    register_match_mean: float | None
    faithfulness_mean: float | None

    # Fact-count breakdowns (the structured-output diagnostic per ADR 2)
    avg_matched_facts: float | None
    avg_missing_facts: float | None
    avg_irrelevant_facts: float | None

    # Refusal tone and red-team rubric
    refusal_tone_mean: float | None
    n_with_refusal_tone: int
    red_team_rubric_mean: float | None
    red_team_rubric_pass_rate: float | None
    n_red_team: int

    # Critic refusal-cause breakdown. Splits the umbrella
    # `behavior=refuse_with_redirect` count by WHY the critic gate fired so
    # the bench distinguishes harness failures (critic itself crashed) from
    # real groundedness catches. Only meaningful when critic_mode == "on".
    n_critic_invalid_refuses: int  # critic itself errored
    n_grounded_false_refuses: int  # critic OK but answer ungrounded
    n_register_only_logs: int  # answer shipped, register mismatch logged

    total_cost_usd: float
    latency_p50_s: float | None
    judge_correctness_errors: int
    judge_faithfulness_errors: int
    judge_refusal_tone_errors: int
    judge_red_team_errors: int
    answer_errors: int


def dump_cases(path: Path, cases: list[CaseResult]) -> None:
    """Serialize per-case results to JSON for later re-render.

    Every bench run dumps its case data so a future
    `--render-only` invocation can re-apply new aggregate logic / rendering
    fixes without paying for another set of pipeline + judge calls.
    """
    payload = [asdict(c) for c in cases]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cases(path: Path) -> list[CaseResult]:
    """Inverse of `dump_cases`. Returns a list of CaseResult instances.

    Forward-compatibility scope:

    - **Extra keys in the JSON (future schema):** silently dropped. Tested by
      `test_load_cases_drops_unknown_keys`.
    - **Optional fields missing from the JSON (with defaults on the
      dataclass):** fall back to the dataclass default. This covers fields
      added since the cache was written.
    - **Required fields missing from the JSON (no default on the
      dataclass):** load_cases will raise `TypeError` from the `CaseResult(**filtered)`
      constructor. These are: `question_id`, `provider_name`,
      `provider_model_id`, `critic_mode`, `expected_behavior`,
      `behavior_taken`, `behavior_match`. Cache-bust + re-run the bench if
      this happens.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    valid_names = {f.name for f in fields(CaseResult)}
    cases: list[CaseResult] = []
    for d in payload:
        filtered = {k: v for k, v in d.items() if k in valid_names}
        cases.append(CaseResult(**filtered))
    return cases


def _empty_aggregate() -> AggregateMetrics:
    return AggregateMetrics(
        provider_name="",
        provider_model_id="",
        critic_mode="",
        n_cases=0,
        n_with_gold=0,
        behavior_match_rate=0.0,
        recall_at_5_mean=None,
        citation_accuracy_mean=None,
        correctness_mean=None,
        register_match_mean=None,
        faithfulness_mean=None,
        avg_matched_facts=None,
        avg_missing_facts=None,
        avg_irrelevant_facts=None,
        refusal_tone_mean=None,
        n_with_refusal_tone=0,
        red_team_rubric_mean=None,
        red_team_rubric_pass_rate=None,
        n_red_team=0,
        n_critic_invalid_refuses=0,
        n_grounded_false_refuses=0,
        n_register_only_logs=0,
        total_cost_usd=0.0,
        latency_p50_s=None,
        judge_correctness_errors=0,
        judge_faithfulness_errors=0,
        judge_refusal_tone_errors=0,
        judge_red_team_errors=0,
        answer_errors=0,
    )


def _retrieval_was_expected(c: CaseResult) -> bool:
    """True when the pipeline was supposed to retrieve something for this case.

    Used to filter the recall@5 and citation-accuracy aggregates.
    Cases where `expected_behavior` is `ask_clarification` or `refuse_with_redirect`
    correctly short-circuit before retrieval — counting recall=0 against them
    deflates the metric for cases where retrieval WORKING was the expected
    outcome. `partial_answer_with_escalation` still expects retrieval on the
    in-corpus portion (q-005, rt-003), so it's included.

    Has-target check: standard cases have `expected_quoted_passages`; red-team
    cases have `expected_source_ids`. Either is sufficient.
    """
    if c.expected_behavior not in {"answer", "partial_answer_with_escalation"}:
        return False
    has_standard_target = bool(c.expected_quoted_passages)
    has_red_team_target = c.is_red_team and bool(c.expected_source_ids)
    return has_standard_target or has_red_team_target


def aggregate(cases: list[CaseResult]) -> AggregateMetrics:
    """Reduce a list of CaseResult into one AggregateMetrics row.

    Works for standard-question batches AND red-team batches. The renderer
    decides which fields to surface based on `n_red_team` vs `n_with_gold`.

    Recall@5 and citation-accuracy
    aggregates exclude cases where the pipeline correctly short-circuited
    before retrieval (ask_clarification / refuse_with_redirect). See
    `_retrieval_was_expected` for the predicate.
    """
    if not cases:
        return _empty_aggregate()

    with_gold = [c for c in cases if c.has_gold]
    red_team = [c for c in cases if c.is_red_team]
    tone_scores = [c.refusal_tone_score for c in cases if c.refusal_tone_score is not None]
    rubric_scores = [
        c.red_team_rubric_score for c in red_team if c.red_team_rubric_score is not None
    ]
    red_team_with_pass = [c for c in red_team if c.red_team_rubric_pass is not None]
    retrieval_expected = [c for c in cases if _retrieval_was_expected(c)]

    return AggregateMetrics(
        provider_name=cases[0].provider_name,
        provider_model_id=cases[0].provider_model_id,
        critic_mode=cases[0].critic_mode,
        n_cases=len(cases),
        n_with_gold=len(with_gold),
        behavior_match_rate=sum(c.behavior_match for c in cases) / len(cases),
        recall_at_5_mean=_safe_mean([c.recall_at_5 for c in retrieval_expected]),
        citation_accuracy_mean=_safe_mean(
            [c.citation_accuracy for c in retrieval_expected if c.citation_method == "rule"]
        ),
        correctness_mean=_safe_mean(
            [c.correctness_score for c in with_gold if c.correctness_score is not None]
        ),
        register_match_mean=_safe_mean(
            [c.register_match_score for c in with_gold if c.register_match_score is not None]
        ),
        faithfulness_mean=_safe_mean(
            [c.faithfulness_score for c in with_gold if c.faithfulness_score is not None]
        ),
        avg_matched_facts=_safe_mean(
            [float(len(c.matched_facts)) for c in with_gold if c.correctness_score is not None]
        ),
        avg_missing_facts=_safe_mean(
            [float(len(c.missing_facts)) for c in with_gold if c.correctness_score is not None]
        ),
        avg_irrelevant_facts=_safe_mean(
            [float(len(c.irrelevant_facts)) for c in with_gold if c.correctness_score is not None]
        ),
        refusal_tone_mean=_safe_mean(tone_scores),
        n_with_refusal_tone=len(tone_scores),
        red_team_rubric_mean=_safe_mean(rubric_scores),
        red_team_rubric_pass_rate=(
            sum(1 for c in red_team_with_pass if c.red_team_rubric_pass) / len(red_team_with_pass)
            if red_team_with_pass
            else None
        ),
        n_red_team=len(red_team),
        # Critic refusal-cause counters.
        # Hard-OOS / pre-retrieval refuses leave critic state at sentinel
        # (valid=True, grounded=True) so they don't match either critic-bucket.
        # Off-mode skips the critic so all three counts naturally land at 0.
        n_critic_invalid_refuses=sum(
            1 for c in cases if c.behavior_taken == "refuse_with_redirect" and not c.critic_valid
        ),
        n_grounded_false_refuses=sum(
            1
            for c in cases
            if c.behavior_taken == "refuse_with_redirect"
            and c.critic_valid
            and not c.critic_grounded
        ),
        n_register_only_logs=sum(
            1
            for c in cases
            if c.behavior_taken == "answer"
            and c.critic_valid
            and c.critic_grounded
            and not c.critic_register_match
        ),
        total_cost_usd=sum(c.cost_usd for c in cases),
        latency_p50_s=_safe_median([c.latency_s for c in cases]),
        judge_correctness_errors=sum(bool(c.judge_correctness_error) for c in cases),
        judge_faithfulness_errors=sum(bool(c.judge_faithfulness_error) for c in cases),
        judge_refusal_tone_errors=sum(bool(c.judge_refusal_tone_error) for c in cases),
        judge_red_team_errors=sum(bool(c.judge_red_team_error) for c in cases),
        answer_errors=sum(bool(c.answer_error) for c in cases),
    )

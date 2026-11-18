# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Critic post-check: a model's verdict on register match and groundedness, failing closed.

Verifies register match + groundedness before returning the answer. The critic is meant as a
gate, so it fails closed: an earlier version passed by default on any exception, which turned
the critic into telemetry, not a gate.

The first bench run surfaced that real
providers (Claude / OpenAI) return JSON wrapped in markdown code blocks or with
leading prose, which `json.loads(response.text)` rejects. With Option B gating,
every parse failure refused — Claude `critic=on` dropped to 18.8% behavior
match. The fix: use the same `_extract_json` pattern as `bench/metrics.py` to
extract the first `{...}` block before parsing. Robust to:
  - raw JSON
  - JSON wrapped in ```json ... ``` markdown
  - JSON with leading "Here's the analysis:" prose
  - Trailing prose after the JSON object

`CriticResult` carries a `valid` field. A `valid=False` result means the critic
itself errored — pipeline.py treats that as `grounded=False` under Option B,
which fires the refuse gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from murshid.providers.base import LLMProvider
from murshid.retrieve import RetrievalResult


@dataclass
class CriticResult:
    register_match: bool
    grounded: bool
    issues: list[str] = field(default_factory=list)
    valid: bool = True  # False iff the critic itself errored (not its verdict)


CRITIC_PROMPT_AR = """[ROLE: critic]
أنت ناقد إجابات لمساعد خدمات حكومية سعودية صارم.
السلامة تأتي قبل المساعدة: رفض إجابة غير مدعومة أفضل من تأكيد ادعاء سياسة لم يرد في المصادر.

بناءً على السؤال والإجابة المقترحة والمصادر المسترجعة، تحقق من شرطين:

1. **مطابقة السجل**: هل تتطابق الإجابة مع سجل السؤال (فصحى / لهجة / مختلط)؟

2. **التأسيس على المصادر**:
   - هل كل ادعاء محدد في الإجابة (رسم، إعفاء، مدة، شرط، إجراء، تاريخ، رقم تواصل، جهة) مذكور صراحةً في أحد المقاطع المسترجعة؟
   - **تنبيه: تطابق الموضوع لا يساوي التأسيس.** مقطع عن "رسوم تجديد الإقامة" لا يدعم ادعاء عن "إعفاء كبار السن من رسوم الإقامة" إلا إذا كان الإعفاء مذكوراً حرفياً في النص.
   - إن سأل المستخدم عن تفصيل محدد (إعفاء، استثناء، رسم خاص، شرط معين) وكانت المصادر تتحدث عن الموضوع العام دون ذكر التفصيل، فالإجابة `grounded=false` — حتى لو كانت الإجابة سلبية مثل "لا يوجد إعفاء". المصادر لم تنف الادعاء صراحةً، وإجابة النفي العامة هي ادعاء بلا مصدر.
   - الاستنتاجات والافتراضات («حسب القاعدة العامة...»، «يُعتبر افتراضياً أن...») تُعد ادعاءات بلا مصدر.

أعد إجابتك بصيغة JSON فقط:
{"register_match": true|false, "grounded": true|false, "issues": ["..."]}

استخدم issues لذكر السبب المحدد:
- "register_mismatch" — سجل الإجابة مغاير لسجل السؤال
- "unsupported_specific_claim" — ادعاء محدد (رسم/إعفاء/شرط) لم يُذكر في المصادر
- "topic_overlap_not_support" — المصادر تغطي الموضوع العام لكن لا تذكر الادعاء بالذات
- "invented_policy" — اخترعت الإجابة سياسة أو شرطاً لم يرد
- "silent_substitution" — استبدلت الإجابة مفهوماً بمفهوم آخر (مثلاً هوية ↔ إقامة)
- "translated_quote_to_dialect" — حُوّل اقتباس مصدر إلى لهجة كأنه نصه الأصلي
"""


def _format_user_prompt(query: str, answer: str, citations: list[RetrievalResult]) -> str:
    context = (
        "\n\n".join(f"[{i}] {c.chunk_id}: {c.passage_text}" for i, c in enumerate(citations, 1))
        or "(لا توجد مصادر مسترجعة)"
    )
    return (
        f"السؤال:\n{query}\n\n"
        f"الإجابة المقترحة:\n{answer}\n\n"
        f"المصادر المسترجعة:\n{context}\n\n"
        f"النقد بصيغة JSON:"
    )


def _extract_json(text: str) -> dict[str, Any]:
    """Robust JSON extraction matching `bench/metrics.py:_extract_json`.

    Real LLM providers wrap JSON in markdown code blocks (` ```json\\n{...}\\n``` `)
    or add prose around it ("Here is the analysis: {...}"). A bare
    `json.loads` rejects both. This extracts the first `{...}` block.

    Raises `json.JSONDecodeError` if no JSON object can be found.
    """
    if not text:
        raise json.JSONDecodeError("empty response from critic", "", 0)
    # The critic's reply is open JSON. A reply that parses to something other than an object
    # fails the key lookups in `critique_answer`, which then fails closed.
    payload: dict[str, Any]
    try:
        payload = json.loads(text)
        return payload
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise json.JSONDecodeError("no JSON object found in critic response", text, 0)
    payload = json.loads(match.group(0))
    return payload


def critique_answer(
    query: str,
    answer: str,
    citations: list[RetrievalResult],
    provider: LLMProvider,
) -> CriticResult:
    """Run the critic over (query, answer, citations).

    On ANY error (JSON decode, provider exception, missing keys), returns a
    `CriticResult` with `valid=False` and both checks set to False. The pipeline
    decides what to do with that — under Option B, `grounded=False` fires the
    refuse gate.
    """
    # Provider call (separated try-block so we can distinguish parse errors
    # from provider errors in `issues`).
    #
    # max_tokens budget history:
    #   256  — the first default. Insufficient once real providers answered
    #          (Anthropic / OpenAI wrap their JSON in ```json blocks).
    #   512  — after the first bench run. Worked for Claude but openai's GPT-5.x family
    #          has an invisible "thinking" budget that consumed the 512 before
    #          any visible JSON could be emitted, returning empty responses
    #          that defaulted to grounded=False under the fail-closed
    #          policy. A focused bench run surfaced this on 3 of 5
    #          openai/critic=on cells.
    #   4000 — the current budget. Matches the judge max_tokens. Same pattern
    #          as the Gemini Pro thinking-budget fix in the judges.
    try:
        response = provider.generate(
            system=CRITIC_PROMPT_AR,
            user=_format_user_prompt(query, answer, citations),
            max_tokens=4000,
        )
    except Exception as exc:
        return CriticResult(
            register_match=False,
            grounded=False,
            issues=[f"critic_provider_error: {type(exc).__name__}: {str(exc)[:160]}"],
            valid=False,
        )

    # Parse the response with robust JSON extraction.
    try:
        payload = _extract_json(response.text)
        return CriticResult(
            register_match=bool(payload["register_match"]),
            grounded=bool(payload["grounded"]),
            issues=[str(x) for x in payload.get("issues", []) if x],
            valid=True,
        )
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        # Include a short preview of the unparseable text in the issue for
        # debugging — never the full response (could be large).
        preview = (response.text or "")[:120].replace("\n", " ")
        return CriticResult(
            register_match=False,
            grounded=False,
            issues=[
                f"critic_parse_error: {type(exc).__name__}: {str(exc)[:120]}",
                f"critic_response_preview: {preview}",
            ],
            valid=False,
        )

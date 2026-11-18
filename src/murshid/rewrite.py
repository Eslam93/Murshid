"""Dialect → MSA query rewriter (the third retrieval view).

Calls an LLM via the provider layer. Preserves:
- English domain tokens (OTP, iqama, IBAN, ...) verbatim
- Dates and numbers verbatim (especially Hijri references)
- Proper nouns verbatim

The zero-key providers (mock, extractive, replay) return the query unchanged
(identity rewrite); a paid provider rewrites it.
"""

from __future__ import annotations

from murshid.providers.base import LLMProvider

REWRITE_PROMPT_AR = """[ROLE: rewrite]
أنت مساعد لإعادة صياغة الأسئلة إلى العربية الفصحى.
أعد صياغة سؤال المستخدم إلى الفصحى مع الحفاظ على:
- المصطلحات الإنجليزية كما هي بحروفها اللاتينية (مثل OTP, iqama, IBAN, status, refund, request, application, update, portal)
- التواريخ والأرقام كما هي، خاصة التواريخ الهجرية
- الأسماء العلمية والمصطلحات التقنية كما هي

أعد فقط النص المعاد صياغته، دون مقدمات أو شرح أو علامات اقتباس.
"""


def rewrite_to_msa(query: str, provider: LLMProvider, max_tokens: int = 256) -> str:
    """Rewrite a dialect / mixed-register query into MSA.

    Returns the rewritten string. Falls back to the original query on error.
    """
    try:
        response = provider.generate(
            system=REWRITE_PROMPT_AR,
            user=query,
            max_tokens=max_tokens,
        )
        rewritten = response.text.strip()
        # Defensive: if the model returns empty or wrapped quotes, fall back.
        if not rewritten:
            return query
        if rewritten.startswith('"') and rewritten.endswith('"'):
            rewritten = rewritten[1:-1]
        return rewritten
    except Exception:
        return query

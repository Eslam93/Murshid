"""MockProvider — canned responses for zero-key pipeline tests (§0.5 #1).

Routes by the `[ROLE: ...]` sentinel each role prompt carries (`prompt_role`). Recognised roles:

  - Enrichment  (ingest.ENRICHMENT_PROMPT_AR): returns JSON {summary, keywords}
  - Rewrite     (rewrite.REWRITE_PROMPT_AR):   returns the query unchanged (identity)
  - Critic      (critic.CRITIC_PROMPT_AR):     returns JSON pass
  - Answer      (anything else):               returns a deterministic Arabic stub

The extractive and replay providers route the same way and reuse these replies for every role
but the answer.
"""

from __future__ import annotations

import json
import re
import time
from typing import Literal

from murshid.providers.base import ProviderResponse
from murshid.providers.factory import DEFAULT_MODEL_IDS

PromptRole = Literal["enrichment", "rewrite", "critic", "answer"]


def prompt_role(system: str) -> PromptRole:
    """The role a system prompt asks for, from its `[ROLE: ...]` sentinel; `answer` by default."""
    # Sentinel-token routing (Round 1 fix §3.4): far more robust than substring sniffing on
    # Arabic content that could shift across edits.
    if "[ROLE: enrichment]" in system:
        return "enrichment"
    if "[ROLE: rewrite]" in system:
        return "rewrite"
    if "[ROLE: critic]" in system:
        return "critic"
    return "answer"


class MockProvider:
    """Zero-key provider for end-to-end pipeline testing."""

    name = "mock"
    model_id = DEFAULT_MODEL_IDS["mock"]

    def is_available(self) -> bool:  # pragma: no cover - trivial
        return True

    def cost_estimate_usd(self, response: ProviderResponse) -> float:  # pragma: no cover
        return 0.0

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,  # ignored by mock; preserved for interface parity
    ) -> ProviderResponse:
        start = time.perf_counter()
        text = self._respond(system, user)
        elapsed = time.perf_counter() - start
        return ProviderResponse(
            text=text,
            input_tokens=len((system + user).split()),
            output_tokens=len(text.split()),
            latency_s=elapsed,
            finish_reason="stop",
        )

    # ------------------------------------------------------------------
    # Prompt routing
    # ------------------------------------------------------------------

    def _respond(self, system: str, user: str) -> str:
        role = prompt_role(system)
        if role == "enrichment":
            return self._enrich_response(user)
        if role == "rewrite":
            return self._rewrite_response(user)
        if role == "critic":
            return self._critic_response()
        return self._answer_response(user)

    # ------------------------------------------------------------------
    # Enrichment: build a plausible {summary, keywords} JSON
    # ------------------------------------------------------------------

    def _enrich_response(self, passage: str) -> str:
        first_line = passage.split("\n", 1)[0]
        first_sentence = re.split(r"[.؟!]", first_line, maxsplit=1)[0].strip()
        if not first_sentence:
            first_sentence = "مقطع من وثيقة خدمات حكومية تجريبية."
        if len(first_sentence) > 140:
            first_sentence = first_sentence[:137] + "..."

        tokens = re.findall(r"[؀-ۿa-zA-Z]+", passage)
        keywords: list[str] = []
        seen: set[str] = set()
        for t in tokens:
            if len(t) >= 4 and t not in seen:
                seen.add(t)
                keywords.append(t)
            if len(keywords) >= 8:
                break

        payload = {"summary": first_sentence, "keywords": keywords}
        return json.dumps(payload, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Rewrite: identity (return query unchanged) in Phase 2
    # ------------------------------------------------------------------

    def _rewrite_response(self, user: str) -> str:
        return user.strip()

    # ------------------------------------------------------------------
    # Critic: default-pass
    # ------------------------------------------------------------------

    def _critic_response(self) -> str:
        return json.dumps(
            {"register_match": True, "grounded": True, "issues": []},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------
    # Answer: deterministic stub referencing the retrieved citations
    # ------------------------------------------------------------------

    def _answer_response(self, user: str) -> str:
        bracket_refs = sorted(set(re.findall(r"\[(\d+)\]", user)))
        if bracket_refs:
            cite_str = "، ".join(f"[{r}]" for r in bracket_refs)
        else:
            cite_str = "[لا توجد مصادر مسترجعة]"
        return (
            "[MOCK ANSWER] استناداً إلى المصادر المسترجعة في السياق أعلاه "
            f"({cite_str})، هذا رد تجريبي من MockProvider لأغراض اختبار "
            "خط الأنابيب. في الإنتاج، يولد المزود الحقيقي إجابة بنفس سجل السؤال، "
            "مع اقتباس حرفي للنص المصدر بالفصحى."
        )

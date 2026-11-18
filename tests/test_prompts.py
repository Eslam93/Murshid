# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Prompt-contract tests.

Pins the scope-discipline rule added to combat answer over-inclusion (the
"Hijri elaboration on a non-date question" failure mode surfaced via the
Gradio UI). Both the full and short system prompts must carry the rule so
the discipline survives the SYSTEM_PROMPT_SHORT_AR fallback path.
"""

import json
import re
from pathlib import Path

import pytest

from murshid.prompts import SYSTEM_PROMPT_AR, SYSTEM_PROMPT_SHORT_AR

DATA = Path(__file__).resolve().parents[1] / "data"

SCOPE_RULE_MARKERS = [
    "أجب فقط على ما",  # "answer only what" — the core rule
    "لم يسأل",  # "did not ask" — the constraint
]


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT_AR, SYSTEM_PROMPT_SHORT_AR])
def test_prompt_carries_scope_discipline_rule(prompt: str) -> None:
    for marker in SCOPE_RULE_MARKERS:
        assert marker in prompt, (
            f"Scope-discipline rule missing marker {marker!r}. "
            f"The rule prevents the model from dumping all retrieved source "
            f"detail (dates, fees, edge cases) when the user asked something narrower."
        )


def test_full_prompt_lists_non_required_categories() -> None:
    """The full prompt enumerates the categories it tells the model to omit
    (dates / fees / exceptions / edge cases). This is the explicit list that
    makes the scope rule actionable rather than abstract."""
    for category in ("تواريخ", "رسوم", "استثناءات", "حالات حافة"):
        assert category in SYSTEM_PROMPT_AR, (
            f"Scope-rule category {category!r} missing from SYSTEM_PROMPT_AR"
        )


def test_the_examples_quote_nothing_from_the_corpus() -> None:
    """The few-shot examples show the answer's form only. Their quotes come from no source in the
    corpus and they carry no fee, so the prompt hands the model no answer to a scored question.
    The examples it replaced quoted the fees that q-001 and q-005 ask about."""
    sources = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))
    corpus = "\n".join(source["content"] for source in sources)
    examples = SYSTEM_PROMPT_AR.split("مثالان توضيحيان", 1)[1]
    quotes = re.findall(r'"([^"]+)"', examples)
    assert len(quotes) == 2
    for quote in quotes:
        assert quote not in corpus
    assert "SAR" not in examples

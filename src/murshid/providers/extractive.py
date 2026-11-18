# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""ExtractiveProvider: answers by quoting the retrieved passages verbatim, and nothing else.

The zero-key default. It needs no key and no network, it is deterministic, and its answer is the
passage text the pipeline retrieved, so a visitor without API keys sees what the corpus says
rather than a placeholder. Every other role behaves like the mock: enrichment returns plausible
JSON, rewrite is the identity, and the critic passes.

The answer quotes the top passage, `[1]`, and adds the second passage, `[2]`, when it comes from
another source or quotes a different text:
  - an FAQ chunk ("س: ... ج: ...") gives the answer part, everything after "ج:";
  - any other chunk gives its first one or two sentences.
Each quote is an exact substring of its passage, inside the one fixed MSA frame
`ANSWER_FRAME_AR`, one line per quote, with no other words.

The passages are read back from the user prompt `pipeline.build_user_prompt` writes:
`[i] (source_id=..., chunk_id=..., service=...)` then the passage. `parse_answer_prompt` mirrors
that format; `tests/test_zero_key_providers.py` round-trips the real function through it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from murshid.providers.base import ProviderResponse
from murshid.providers.factory import DEFAULT_MODEL_IDS
from murshid.providers.mock import MockProvider, prompt_role

# The one framing an extractive answer uses, once per quote.
ANSWER_FRAME_AR = "وفقاً للمصدر [{number}]: «{quote}»"
# The reply when the prompt carries no passage to quote.
NO_PASSAGE_ANSWER_AR = "لم أجد في المصادر المسترجعة نصاً أقتبسه للإجابة عن هذا السؤال."

# FAQ chunks are "س: <question>\nج: <answer>" (the corpus format `ingest.chunk_faq` splits on).
_FAQ_QUESTION = "س:"
_FAQ_ANSWER = "ج:"
# A sentence ends at . ! ? or ؟ followed by whitespace or the end of the text, so the dots in
# "1.5" or "example.gov.sa" do not end one.
_SENTENCE_END = re.compile(r"[.!?؟](?=\s|$)")
_SENTENCES_PER_PROSE_QUOTE = 2

# The answer prompt, as `pipeline.build_user_prompt` writes it.
_QUESTION = re.compile(
    r"\Aالسؤال \(سجل المستخدم: [^\n]*?\):\n(?P<question>.*?)\n\n"
    r"(?=إعادة الصياغة بالفصحى \(للاسترجاع\):\n|المصادر المسترجعة:\n)",
    re.DOTALL,
)
_SOURCES = "\n\nالمصادر المسترجعة:\n"
_ANSWER_CUE = "\n\nالإجابة:"
_PASSAGE_SEPARATOR = "\n\n"
_PASSAGE_HEADER = re.compile(
    r"^\[(?P<number>\d+)\] \(source_id=(?P<source_id>[^,\n]*), "
    r"chunk_id=(?P<chunk_id>[^,\n]*), service=(?P<service>[^\n]*)\)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class PromptPassage:
    """One retrieved passage as the answer prompt numbers and carries it."""

    number: int
    source_id: str
    chunk_id: str
    service_title: str
    text: str


@dataclass(frozen=True)
class AnswerPrompt:
    """The question and passages of a pipeline answer prompt."""

    question: str
    passages: tuple[PromptPassage, ...]


def parse_answer_prompt(user: str) -> AnswerPrompt | None:
    """The question and passages of `user`, or None if it is not a pipeline answer prompt."""
    match = _QUESTION.match(user)
    if match is None:
        return None
    sources_at = user.find(_SOURCES, match.end("question"))
    if sources_at < 0:
        return None
    block = user[sources_at + len(_SOURCES) :].removesuffix(_ANSWER_CUE)
    headers = list(_PASSAGE_HEADER.finditer(block))
    passages: list[PromptPassage] = []
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(block)
        text = block[header.end() + 1 : end]
        if i + 1 < len(headers):
            text = text.removesuffix(_PASSAGE_SEPARATOR)
        passages.append(
            PromptPassage(
                number=int(header["number"]),
                source_id=header["source_id"],
                chunk_id=header["chunk_id"],
                service_title=header["service"],
                text=text,
            )
        )
    return AnswerPrompt(question=match["question"], passages=tuple(passages))


def quote_for(passage_text: str) -> str:
    """The verbatim part of a passage an extractive answer quotes."""
    text = passage_text.strip()
    if text.startswith(_FAQ_QUESTION) and _FAQ_ANSWER in text:
        answer = text.split(_FAQ_ANSWER, 1)[1].strip()
        if answer:
            return answer
    ends = [m.end() for m in _SENTENCE_END.finditer(text)]
    if len(ends) >= _SENTENCES_PER_PROSE_QUOTE:
        return text[: ends[_SENTENCES_PER_PROSE_QUOTE - 1]]
    return text


def _same_text(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def choose_quotes(passages: tuple[PromptPassage, ...]) -> list[tuple[PromptPassage, str]]:
    """The passages to quote with their quotes: [1], and [2] if another source or text."""
    chosen: list[tuple[PromptPassage, str]] = []
    if not passages:
        return chosen
    first, first_quote = passages[0], quote_for(passages[0].text)
    if first_quote:
        chosen.append((first, first_quote))
    if len(passages) > 1:
        second, second_quote = passages[1], quote_for(passages[1].text)
        another_source = second.source_id != first.source_id
        if second_quote and (another_source or not _same_text(second_quote, first_quote)):
            chosen.append((second, second_quote))
    return chosen


def format_answer(chosen: list[tuple[PromptPassage, str]]) -> str:
    """One framed line per quote, or the no-passage reply when there is nothing to quote."""
    if not chosen:
        return NO_PASSAGE_ANSWER_AR
    return "\n".join(
        ANSWER_FRAME_AR.format(number=passage.number, quote=quote) for passage, quote in chosen
    )


def extractive_answer(prompt: AnswerPrompt | None) -> str:
    """The extractive answer to a pipeline answer prompt: framed verbatim quotes only."""
    return format_answer(choose_quotes(prompt.passages) if prompt is not None else [])


class ExtractiveProvider:
    """Zero-key provider whose answer is the retrieved passages, quoted."""

    name = "extractive"
    model_id = DEFAULT_MODEL_IDS["extractive"]

    def __init__(self) -> None:
        self._other_roles = MockProvider()

    def is_available(self) -> bool:
        return True

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return 0.0

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,  # no call is made; kept for interface parity
    ) -> ProviderResponse:
        if prompt_role(system) != "answer":
            return self._other_roles.generate(system, user, max_tokens=max_tokens, timeout=timeout)
        start = time.perf_counter()
        prompt = parse_answer_prompt(user)
        chosen = choose_quotes(prompt.passages) if prompt is not None else []
        text = format_answer(chosen)
        return ProviderResponse(
            text=text,
            input_tokens=len((system + user).split()),
            output_tokens=len(text.split()),
            latency_s=time.perf_counter() - start,
            finish_reason="stop",
            raw={"quoted_chunk_ids": [passage.chunk_id for passage, _ in chosen]},
        )

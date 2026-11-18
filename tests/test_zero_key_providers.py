"""The zero-key providers that show real content: ExtractiveProvider and ReplayProvider.

Pins:
  - the answer-prompt parser round-trips the pipeline's own `build_user_prompt`;
  - an extractive answer is the fixed MSA frame around verbatim passage text, and nothing else;
  - a replayed answer is the recorded model answer to the same question (whitespace-normalised
    match), critic-off first, with the corpus domain map applied and recorded in `raw`, and the
    extractive answer when nothing was recorded;
  - both behave like the mock in every other role (enrichment, rewrite, critic passes);
  - both run end to end through `answer_question` (a fake-embedder index in the default tier,
    the real BGE-M3 index under --real-embedder).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from murshid.critic import CRITIC_PROMPT_AR
from murshid.ingest import ENRICHMENT_PROMPT_AR, Index, build_index
from murshid.pipeline import REFUSAL_TEMPLATE_AR, answer_question, build_user_prompt
from murshid.prompts import SYSTEM_PROMPT_AR
from murshid.providers.extractive import (
    ANSWER_FRAME_AR,
    NO_PASSAGE_ANSWER_AR,
    ExtractiveProvider,
    PromptPassage,
    choose_quotes,
    extractive_answer,
    parse_answer_prompt,
    quote_for,
)
from murshid.providers.mock import MockProvider
from murshid.providers.replay import (
    REPLAY_DOMAIN_MAP,
    ReplayProvider,
    apply_domain_map,
    normalise_question,
)
from murshid.register import detect_register
from murshid.retrieve import BM25Index, RetrievalResult, build_bm25_index
from murshid.rewrite import REWRITE_PROMPT_AR

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CASE_CACHE = ROOT / "bench" / "case-cache.json"

FAQ_PASSAGE = (
    "س: هل توجد رسوم؟\nج: الرسوم التمثيلية للخدمة SAR 100 لطلب البدل، وقد يضاف رسم توصيل "
    "افتراضي قدره SAR 25 إذا اختار المستفيد إرسال الوثيقة إلى عنوان اختباري."
)
PROSE_PASSAGE = (
    "توضح هذه الوثيقة آلية تجديد إقامة العامل المقيم قبل انتهاء صلاحيتها. يجب تقديم طلب التجديد "
    "خلال مدة لا تقل عن ثلاثين يوماً ولا تزيد عن تسعين يوماً قبل تاريخ الانتهاء. وإذا كان تاريخ "
    "الانتهاء مسجلاً بالتقويم الهجري، فيحتسب النظام آخر يوم صلاحية وفق اليوم والشهر الهجريين."
)
# The framing with the quote cut out: what an extractive answer line is besides the quote.
_FRAME_LINE = re.compile(r"\Aوفقاً للمصدر \[(\d+)\]: «(.*)»\Z", re.DOTALL)


def _citation(
    chunk_id: str, passage: str, *, source_id: str | None = None, service: str = "خدمة"
) -> RetrievalResult:
    return RetrievalResult(
        source_id=source_id or chunk_id.split(":")[0],
        service_category="iqama",
        service_title=service,
        chunk_id=chunk_id,
        passage_text=passage,
        score=0.1,
    )


def _prompt(question: str, citations: list[RetrievalResult], rewritten: str | None = None) -> str:
    return build_user_prompt(question, citations, "MSA", rewritten)


def _quoted_parts(answer: str) -> list[tuple[int, str]]:
    """(source number, quote) per line; fails unless every line is exactly the frame."""
    parts: list[tuple[int, str]] = []
    for line in _split_frames(answer):
        match = _FRAME_LINE.match(line)
        assert match is not None, f"not the fixed frame: {line!r}"
        parts.append((int(match[1]), match[2]))
    return parts


def _split_frames(answer: str) -> list[str]:
    """Answer lines, rejoining a quote that itself holds a newline (a prose bullet list)."""
    lines: list[str] = []
    for line in answer.split("\n"):
        if line.startswith("وفقاً للمصدر [") or not lines:
            lines.append(line)
        else:
            lines[-1] += "\n" + line
    return lines


def _questions() -> dict[str, str]:
    texts = {
        q["question_id"]: q["text"]
        for q in json.loads((DATA / "questions.json").read_text(encoding="utf-8"))
    }
    texts |= {
        r["case_id"]: r["question_text"]
        for r in json.loads((DATA / "red_team.json").read_text(encoding="utf-8"))
    }
    return texts


def _recorded(question_id: str, provider: str = "openai", critic_mode: str = "off") -> str:
    for record in json.loads(CASE_CACHE.read_text(encoding="utf-8")):
        if (
            record["question_id"] == question_id
            and record["provider_name"] == provider
            and record["critic_mode"] == critic_mode
        ):
            return str(record["predicted_answer_text"])
    raise AssertionError(f"no recording for {question_id}/{provider}/{critic_mode}")


def _write_cache(path: Path, records: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def _record(question_id: str, text: str, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "question_id": question_id,
        "provider_name": "openai",
        "provider_model_id": "gpt-5.5-2026-04-23",
        "critic_mode": "off",
        "behavior_taken": "answer",
        "predicted_answer_text": text,
        "answer_error": "",
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# The answer prompt round-trips through the parser
# ---------------------------------------------------------------------------


def test_the_parser_reads_back_what_build_user_prompt_writes() -> None:
    citations = [
        _citation("iqama-003:chunk-3", FAQ_PASSAGE),
        _citation("iqama-002:chunk-1", PROSE_PASSAGE, service="تجديد الإقامة، للعامل المقيم"),
        _citation("iqama-004:chunk-3", "ما لا نعالجه:\n- طلبات التأشيرات.\n- الاعتراضات."),
    ]
    parsed = parse_answer_prompt(_prompt("  كم رسوم بدل الفاقد؟ ", citations))
    assert parsed is not None
    assert parsed.question == "  كم رسوم بدل الفاقد؟ "
    assert [(p.number, p.chunk_id, p.source_id) for p in parsed.passages] == [
        (1, "iqama-003:chunk-3", "iqama-003"),
        (2, "iqama-002:chunk-1", "iqama-002"),
        (3, "iqama-004:chunk-3", "iqama-004"),
    ]
    assert [p.text for p in parsed.passages] == [c.passage_text for c in citations]
    assert parsed.passages[1].service_title == "تجديد الإقامة، للعامل المقيم"


def test_the_parser_skips_the_rewrite_and_reads_a_multi_line_question() -> None:
    question = "شلون أجدد الإقامة؟\nوكم الرسوم؟"
    parsed = parse_answer_prompt(
        _prompt(question, [_citation("iqama-002:chunk-2", PROSE_PASSAGE)], "كيف أجدد الإقامة؟")
    )
    assert parsed is not None
    assert parsed.question == question
    assert [p.text for p in parsed.passages] == [PROSE_PASSAGE]


def test_the_parser_reads_a_prompt_without_passages() -> None:
    parsed = parse_answer_prompt(_prompt("سؤال", []))
    assert parsed is not None
    assert parsed.passages == ()


@pytest.mark.parametrize("user", ["Reply with just the word OK.", "", "السؤال: ما الرسوم؟"])
def test_the_parser_refuses_what_is_not_an_answer_prompt(user: str) -> None:
    assert parse_answer_prompt(user) is None


# ---------------------------------------------------------------------------
# Extractive answers: verbatim quotes in the fixed frame
# ---------------------------------------------------------------------------


def test_an_faq_chunk_is_quoted_by_its_answer_part() -> None:
    quote = quote_for(FAQ_PASSAGE)
    assert quote == FAQ_PASSAGE.split("ج:", 1)[1].strip()
    assert quote in FAQ_PASSAGE
    assert "س:" not in quote


def test_a_prose_chunk_is_quoted_by_its_first_two_sentences() -> None:
    quote = quote_for(PROSE_PASSAGE)
    assert PROSE_PASSAGE.startswith(quote)
    assert quote.endswith("قبل تاريخ الانتهاء.")
    assert quote.count(".") == 2


def test_a_dot_inside_a_number_or_a_domain_does_not_end_a_sentence() -> None:
    passage = "يدفع المستفيد SAR 1.5 عبر services.example مباشرة. ثم يظهر الإيصال. وبعدها ينتهي."
    assert (
        quote_for(passage) == "يدفع المستفيد SAR 1.5 عبر services.example مباشرة. ثم يظهر الإيصال."
    )


def test_a_one_sentence_chunk_is_quoted_whole() -> None:
    assert quote_for("  جملة واحدة بلا نقطة في آخرها  ") == "جملة واحدة بلا نقطة في آخرها"


def test_the_answer_quotes_the_top_two_passages_in_the_fixed_frame() -> None:
    citations = [
        _citation("iqama-003:chunk-3", FAQ_PASSAGE),
        _citation("iqama-002:chunk-1", PROSE_PASSAGE),
        _citation("iqama-001:chunk-1", "س: سؤال ثالث؟\nج: جواب ثالث لا يقتبس."),
    ]
    answer = extractive_answer(parse_answer_prompt(_prompt("كم الرسوم؟", citations)))
    assert _quoted_parts(answer) == [(1, quote_for(FAQ_PASSAGE)), (2, quote_for(PROSE_PASSAGE))]
    assert answer == "\n".join(
        [
            ANSWER_FRAME_AR.format(number=1, quote=quote_for(FAQ_PASSAGE)),
            ANSWER_FRAME_AR.format(number=2, quote=quote_for(PROSE_PASSAGE)),
        ]
    )
    assert "جواب ثالث" not in answer


def test_the_second_passage_joins_from_another_source_or_with_another_text() -> None:
    def passage(number: int, source_id: str, text: str) -> PromptPassage:
        return PromptPassage(number, source_id, f"{source_id}:chunk-{number}", "خدمة", text)

    same_text_same_source = (
        passage(1, "iqama-003", FAQ_PASSAGE),
        passage(2, "iqama-003", FAQ_PASSAGE),
    )
    assert [p.number for p, _ in choose_quotes(same_text_same_source)] == [1]
    same_text_other_source = (
        passage(1, "iqama-003", FAQ_PASSAGE),
        passage(2, "iqama-001", FAQ_PASSAGE),
    )
    assert [p.number for p, _ in choose_quotes(same_text_other_source)] == [1, 2]
    other_text_same_source = (
        passage(1, "iqama-002", PROSE_PASSAGE),
        passage(2, "iqama-002", FAQ_PASSAGE),
    )
    assert [p.number for p, _ in choose_quotes(other_text_same_source)] == [1, 2]


def test_no_passage_gets_the_fixed_msa_reply() -> None:
    assert extractive_answer(parse_answer_prompt(_prompt("سؤال", []))) == NO_PASSAGE_ANSWER_AR
    assert extractive_answer(None) == NO_PASSAGE_ANSWER_AR
    assert detect_register(NO_PASSAGE_ANSWER_AR).register == "MSA"


def test_the_extractive_answer_is_msa_and_deterministic() -> None:
    msa_passage = "يعالج الطلب عادة خلال ثلاثة أيام عمل. وتظهر النتيجة في سجل الطلب."
    citations = [_citation("iqama-003:chunk-4", msa_passage)]
    provider = ExtractiveProvider()
    first = provider.generate(SYSTEM_PROMPT_AR, _prompt("شلون أجدد إقامتي؟", citations))
    second = provider.generate(SYSTEM_PROMPT_AR, _prompt("شلون أجدد إقامتي؟", citations))
    assert first.text == second.text
    assert detect_register(first.text).register == "MSA"  # a dialect question, an MSA answer
    assert first.finish_reason == "stop"
    assert first.raw == {"quoted_chunk_ids": ["iqama-003:chunk-4"]}
    assert provider.cost_estimate_usd(first) == 0.0


@pytest.mark.parametrize("passage", [FAQ_PASSAGE, PROSE_PASSAGE])
def test_the_frame_never_changes_the_register_of_the_quoted_text(passage: str) -> None:
    """The rule-based detector reads corpus MSA such as "ولا تزيد" as dialect, and "SAR" as
    mixing; whatever it says of the quote, the frame around it adds nothing."""
    answer = extractive_answer(
        parse_answer_prompt(_prompt("سؤال", [_citation("x:chunk-1", passage)]))
    )
    assert detect_register(answer) == detect_register(quote_for(passage))


def test_the_other_roles_behave_like_the_mock() -> None:
    mock, extractive = MockProvider(), ExtractiveProvider()
    for system, user in [(ENRICHMENT_PROMPT_AR, FAQ_PASSAGE), (REWRITE_PROMPT_AR, "  شلون؟  ")]:
        assert extractive.generate(system, user).text == mock.generate(system, user).text
    verdict = json.loads(extractive.generate(CRITIC_PROMPT_AR, "anything").text)
    assert verdict == {"register_match": True, "grounded": True, "issues": []}


# ---------------------------------------------------------------------------
# Replay: the recorded answer to the same question
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def replay() -> ReplayProvider:
    return ReplayProvider(replay_file=CASE_CACHE, data_dir=DATA)


def test_replay_returns_the_recorded_answer_to_the_same_question(replay: ReplayProvider) -> None:
    question = _questions()["q-001"]
    response = replay.generate(SYSTEM_PROMPT_AR, _prompt(question, []))
    expected, _ = apply_domain_map(_recorded("q-001"))
    assert response.text == expected
    assert replay.model_id == "replay:openai/gpt-5.5-2026-04-23"
    assert response.raw["replay"] == "hit"
    assert response.raw["replayed"] == "openai/gpt-5.5-2026-04-23"
    assert response.raw["question_id"] == "q-001"
    assert response.raw["critic_mode"] == "off"
    assert replay.cost_estimate_usd(response) == 0.0


def test_replay_matches_after_whitespace_normalisation(replay: ReplayProvider) -> None:
    question = _questions()["q-007"]
    spaced = "  " + question.replace(" ", "   \n ", 3) + "\t"
    assert normalise_question(spaced) == normalise_question(question)
    response = replay.generate(SYSTEM_PROMPT_AR, _prompt(spaced, []))
    assert response.raw["question_id"] == "q-007"


def test_a_question_without_a_recording_gets_the_extractive_answer(replay: ReplayProvider) -> None:
    citations = [_citation("iqama-003:chunk-3", FAQ_PASSAGE)]
    response = replay.generate(SYSTEM_PROMPT_AR, _prompt("سؤال لم يسجل له أي جواب؟", citations))
    assert response.text == ANSWER_FRAME_AR.format(number=1, quote=quote_for(FAQ_PASSAGE))
    assert response.raw["replay"] == "miss"
    assert response.raw["fallback"] == "extractive-1"


def test_a_replayed_answer_gets_the_domain_map_and_raw_records_it(tmp_path: Path) -> None:
    recorded = "راجع visa-example.gov.sa للتأشيرات، وexample.gov.sa للسداد عبر example.gov.sa/pay."
    cache = _write_cache(tmp_path / "cache.json", [_record("q-005", recorded)])
    provider = ReplayProvider(replay_file=cache, data_dir=DATA)
    response = provider.generate(SYSTEM_PROMPT_AR, _prompt(_questions()["q-005"], []))
    assert (
        response.text
        == "راجع visa.example للتأشيرات، وservices.example للسداد عبر services.example/pay."
    )
    assert response.raw["domains_replaced"] == [
        {"from": "visa-example.gov.sa", "to": "visa.example", "count": 1},
        {"from": "example.gov.sa", "to": "services.example", "count": 2},
    ]


def test_no_committed_replay_shows_a_gov_sa_domain(replay: ReplayProvider) -> None:
    replayed = 0
    for question in _questions().values():
        response = replay.generate(SYSTEM_PROMPT_AR, _prompt(question, []))
        if response.raw["replay"] == "hit":
            replayed += 1
            assert ".gov.sa" not in response.text
            assert response.raw["domains_replaced"] == []  # the recordings quote no domain today
    assert replayed == 18  # openai, critic off: every bench question it generated an answer for


def test_the_domain_map_replaces_the_longer_domain_first() -> None:
    # The same replacement the corpus got: RFC 2606 names for the synthetic services.
    assert REPLAY_DOMAIN_MAP == {
        "visa-example.gov.sa": "visa.example",
        "example.gov.sa": "services.example",
    }
    text, replaced = apply_domain_map(
        "انظر visa-example.gov.sa ثم example.gov.sa ثم example.gov.sa/pay"
    )
    assert text == "انظر visa.example ثم services.example ثم services.example/pay"
    assert replaced == [
        {"from": "visa-example.gov.sa", "to": "visa.example", "count": 1},
        {"from": "example.gov.sa", "to": "services.example", "count": 2},
    ]
    assert apply_domain_map("لا نطاق هنا") == ("لا نطاق هنا", [])


def test_replay_prefers_critic_off_and_replays_only_generated_answers(tmp_path: Path) -> None:
    questions = _questions()
    cache = _write_cache(
        tmp_path / "cache.json",
        [
            _record("q-001", "جواب الناقد مفعل", critic_mode="on"),
            _record("q-001", "جواب الناقد معطل على example.gov.sa", critic_mode="off"),
            _record("q-002", "رفض", behavior_taken="refuse_with_redirect"),
            _record("q-003", "خطأ", answer_error="RateLimitError: 429"),
            _record("q-005", "جواب جزئي", behavior_taken="partial_answer_with_escalation"),
            _record(
                "q-006", "نموذج آخر", provider_name="claude", provider_model_id="claude-sonnet-4-6"
            ),
            _record("q-007", "جواب الناقد مفعل فقط", critic_mode="on"),
        ],
    )
    provider = ReplayProvider(replay_file=cache, data_dir=DATA)

    def answer(question_id: str) -> tuple[str, str]:
        response = provider.generate(SYSTEM_PROMPT_AR, _prompt(questions[question_id], []))
        return response.text, response.raw["replay"]

    assert answer("q-001") == ("جواب الناقد معطل على services.example", "hit")
    assert answer("q-002")[1] == "miss"
    assert answer("q-003")[1] == "miss"
    assert answer("q-005") == ("جواب جزئي", "hit")
    assert answer("q-006")[1] == "miss"
    assert answer("q-007") == ("جواب الناقد مفعل فقط", "hit")


def test_replay_can_replay_another_recorded_model(tmp_path: Path) -> None:
    cache = _write_cache(
        tmp_path / "cache.json",
        [
            _record(
                "q-006", "جواب كلود", provider_name="claude", provider_model_id="claude-sonnet-4-6"
            )
        ],
    )
    provider = ReplayProvider("claude/claude-sonnet-4-6", replay_file=cache, data_dir=DATA)
    assert provider.model_id == "replay:claude/claude-sonnet-4-6"
    response = provider.generate(SYSTEM_PROMPT_AR, _prompt(_questions()["q-006"], []))
    assert response.text == "جواب كلود"


def test_replay_needs_its_recorded_answers_and_a_provider_model_pair(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="MURSHID_REPLAY_FILE"):
        ReplayProvider(replay_file=tmp_path / "missing.json", data_dir=DATA)
    with pytest.raises(FileNotFoundError, match="MURSHID_DATA_DIR"):
        ReplayProvider(replay_file=CASE_CACHE, data_dir=tmp_path)
    with pytest.raises(ValueError, match="<provider>/<model id>"):
        ReplayProvider("openai", replay_file=CASE_CACHE, data_dir=DATA)


def test_replay_is_unavailable_without_answers_from_its_model(tmp_path: Path) -> None:
    cache = _write_cache(tmp_path / "cache.json", [_record("q-001", "x")])
    assert ReplayProvider(replay_file=cache, data_dir=DATA).is_available()
    assert not ReplayProvider(
        "gemini/gemini-2.5-pro", replay_file=cache, data_dir=DATA
    ).is_available()


def test_replay_behaves_like_the_mock_in_the_other_roles(replay: ReplayProvider) -> None:
    mock = MockProvider()
    assert (
        replay.generate(REWRITE_PROMPT_AR, " شلون ").text
        == mock.generate(REWRITE_PROMPT_AR, " شلون ").text
    )
    verdict = json.loads(replay.generate(CRITIC_PROMPT_AR, "anything").text)
    assert verdict["grounded"] is True


def test_the_committed_cache_covers_the_demo_questions(replay: ReplayProvider) -> None:
    for question_id in ("q-001", "q-007"):
        assert replay.recording_for(_questions()[question_id]) is not None


# ---------------------------------------------------------------------------
# End to end through answer_question, on an index with a fake embedder
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_index(fake_embedder: None) -> tuple[Index, BM25Index]:
    """The real corpus, chunked and enriched as usual, embedded by the model-free fake."""
    index = build_index(DATA, MockProvider())
    return index, build_bm25_index(index)


def _assert_extractive(answer_text: str, citations: list[RetrievalResult]) -> None:
    parts = _quoted_parts(answer_text)
    assert parts, answer_text
    for number, quote in parts:
        assert quote in citations[number - 1].passage_text


@pytest.mark.parametrize("critic_enabled", [False, True])
def test_extractive_answers_end_to_end(
    fake_index: tuple[Index, BM25Index], critic_enabled: bool
) -> None:
    index, bm25 = fake_index
    answer = answer_question(
        _questions()["q-001"],
        index,
        ExtractiveProvider(),
        bm25_index=bm25,
        critic_enabled=critic_enabled,
    )
    assert answer.behavior_taken == "answer"
    assert answer.provider_name == "extractive"
    assert answer.provider_model_id == "extractive-1"
    assert answer.critic_grounded is True
    _assert_extractive(answer.answer_text, answer.citations)


def test_extractive_answers_a_dialect_question_in_msa_end_to_end(
    fake_index: tuple[Index, BM25Index],
) -> None:
    index, bm25 = fake_index
    answer = answer_question(_questions()["q-007"], index, ExtractiveProvider(), bm25_index=bm25)
    assert answer.question_register == "dialect"
    # The zero-key rewrite is the identity, as the mock's is.
    assert answer.rewritten_query == _questions()["q-007"]
    assert answer.behavior_taken == "answer"
    _assert_extractive(answer.answer_text, answer.citations)


def test_extractive_keeps_the_short_circuits(fake_index: tuple[Index, BM25Index]) -> None:
    index, bm25 = fake_index
    answer = answer_question(_questions()["q-014"], index, ExtractiveProvider(), bm25_index=bm25)
    assert answer.behavior_taken == "refuse_with_redirect"
    assert answer.answer_text == REFUSAL_TEMPLATE_AR


def test_replay_answers_end_to_end(fake_index: tuple[Index, BM25Index]) -> None:
    index, bm25 = fake_index
    provider = ReplayProvider(replay_file=CASE_CACHE, data_dir=DATA)
    answer = answer_question(
        _questions()["q-001"], index, provider, bm25_index=bm25, critic_enabled=True
    )
    assert answer.behavior_taken == "answer"
    assert answer.answer_text == apply_domain_map(_recorded("q-001"))[0]
    assert answer.provider_name == "replay"
    assert answer.provider_model_id == "replay:openai/gpt-5.5-2026-04-23"


def test_replay_falls_back_to_extractive_end_to_end(fake_index: tuple[Index, BM25Index]) -> None:
    index, bm25 = fake_index
    provider = ReplayProvider(replay_file=CASE_CACHE, data_dir=DATA)
    answer = answer_question("ما رسوم إصدار بدل فاقد للإقامة؟", index, provider, bm25_index=bm25)
    assert answer.behavior_taken == "answer"
    _assert_extractive(answer.answer_text, answer.citations)


# ---------------------------------------------------------------------------
# The same, on the real BGE-M3 index (pytest --real-embedder)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_index() -> tuple[Index, BM25Index]:
    index = build_index(DATA, MockProvider())
    return index, build_bm25_index(index)


@pytest.mark.real_embedder
def test_extractive_quotes_the_renewal_window_for_q001(real_index: tuple[Index, BM25Index]) -> None:
    index, bm25 = real_index
    answer = answer_question(_questions()["q-001"], index, ExtractiveProvider(), bm25_index=bm25)
    assert answer.behavior_taken == "answer"
    _assert_extractive(answer.answer_text, answer.citations)
    assert "يوماً" in answer.answer_text


@pytest.mark.real_embedder
def test_extractive_answers_a_dialect_question_in_msa(real_index: tuple[Index, BM25Index]) -> None:
    index, bm25 = real_index
    answer = answer_question(_questions()["q-007"], index, ExtractiveProvider(), bm25_index=bm25)
    assert answer.question_register == "dialect"
    assert answer.behavior_taken == "answer"
    _assert_extractive(answer.answer_text, answer.citations)


@pytest.mark.real_embedder
def test_replay_answers_the_demo_questions(real_index: tuple[Index, BM25Index]) -> None:
    index, bm25 = real_index
    provider = ReplayProvider(replay_file=CASE_CACHE, data_dir=DATA)
    for question_id in ("q-001", "q-007"):
        answer = answer_question(_questions()[question_id], index, provider, bm25_index=bm25)
        assert answer.answer_text == apply_domain_map(_recorded(question_id))[0]

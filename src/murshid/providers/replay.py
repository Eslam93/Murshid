"""ReplayProvider: real recorded model answers to the bench questions, with no key and no call.

The bench's case cache (`MURSHID_REPLAY_FILE`, by default `bench/case-cache.json`) holds every
answer Claude and OpenAI gave to the 26 bench questions in both critic modes. Asked to answer, this
provider finds the question the answer prompt carries among the bench questions (exact match
after whitespace normalisation) and returns the recorded model's answer to it: critic-off first,
then critic-on. A question it has no recording for gets the extractive answer instead. Every
other role behaves like the mock, so the critic passes.

`model_id` names what is replayed, as `replay:<provider>/<model id>`; each response's `raw` says
whether it was a replay (`"replay": "hit"`, with the question id and critic mode) or the
extractive fallback (`"replay": "miss"`).

The corpus's example domains moved to reserved RFC 2606 names after these answers were recorded.
The same replacement (`REPLAY_DOMAIN_MAP`) is applied to the replayed text, so a replay never
shows a .gov.sa look-alike domain, and `raw["domains_replaced"]` records each replacement made.

Only an answer the recorded run actually generated is replayed: an answer or partial answer with
no error. A recorded refusal holds a template, not model text, and a question the pipeline
short-circuits never reaches the answer role anyway.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from murshid.providers.base import ProviderResponse
from murshid.providers.extractive import ExtractiveProvider, parse_answer_prompt
from murshid.providers.mock import prompt_role

# Recorded corpus domain -> its RFC 2606 replacement. Applied longest key first, so the visa
# domain is not caught by the shorter one it contains.
REPLAY_DOMAIN_MAP: dict[str, str] = {
    "visa-example.gov.sa": "visa.example",
    "example.gov.sa": "services.example",
}

# The recorded model replayed by default: the bench's best, OpenAI, read with critic off.
DEFAULT_RECORDED_MODEL = "openai/gpt-5.5-2026-04-23"
# Critic-off answers are the model's raw output; critic-on ones passed the critic too.
CRITIC_MODE_ORDER = ("off", "on")
# A recorded behavior whose answer text the model generated.
_GENERATED_BEHAVIORS = frozenset({"answer", "partial_answer_with_escalation"})


@dataclass(frozen=True)
class Recording:
    """One recorded answer: which bench question, in which critic mode, and its text."""

    question_id: str
    critic_mode: str
    text: str


def normalise_question(text: str) -> str:
    """The form questions are matched in: runs of whitespace become one space, ends trimmed."""
    return " ".join(text.split())


def apply_domain_map(text: str) -> tuple[str, list[dict[str, Any]]]:
    """`text` with the corpus's old example domains replaced, and the replacements made."""
    replaced: list[dict[str, Any]] = []
    for old in sorted(REPLAY_DOMAIN_MAP, key=len, reverse=True):
        count = text.count(old)
        if count:
            text = text.replace(old, REPLAY_DOMAIN_MAP[old])
            replaced.append({"from": old, "to": REPLAY_DOMAIN_MAP[old], "count": count})
    return text, replaced


def _question_texts(data_dir: Path) -> dict[str, str]:
    """Bench question id -> question text, from the standard and red-team sets."""
    sources = (
        ("questions.json", "question_id", "text"),
        ("red_team.json", "case_id", "question_text"),
    )
    texts: dict[str, str] = {}
    found = False
    for file_name, id_key, text_key in sources:
        path = data_dir / file_name
        if not path.is_file():
            continue
        found = True
        for record in json.loads(path.read_text(encoding="utf-8")):
            texts[str(record[id_key])] = str(record[text_key])
    if not found:
        raise FileNotFoundError(
            f"no bench questions in {data_dir} (MURSHID_DATA_DIR): the replay provider needs "
            "questions.json or red_team.json to know which question each recorded answer is for"
        )
    return texts


def load_recordings(replay_file: Path, data_dir: Path, recorded: str) -> dict[str, list[Recording]]:
    """Normalised question -> the recorded model's usable answers to it, in critic-mode order."""
    if not replay_file.is_file():
        raise FileNotFoundError(f"no recorded answers at {replay_file} (MURSHID_REPLAY_FILE)")
    provider_name, _, model_id = recorded.partition("/")
    texts = _question_texts(data_dir)
    by_question: dict[str, list[Recording]] = {}
    for record in json.loads(replay_file.read_text(encoding="utf-8")):
        usable = (
            record.get("provider_name") == provider_name
            and record.get("provider_model_id") == model_id
            and record.get("behavior_taken") in _GENERATED_BEHAVIORS
            and not record.get("answer_error")
            and record.get("predicted_answer_text")
            and record.get("critic_mode") in CRITIC_MODE_ORDER
            and record.get("question_id") in texts
        )
        if usable:
            question = normalise_question(texts[record["question_id"]])
            by_question.setdefault(question, []).append(
                Recording(
                    question_id=record["question_id"],
                    critic_mode=record["critic_mode"],
                    text=record["predicted_answer_text"],
                )
            )
    for recordings in by_question.values():
        recordings.sort(key=lambda r: CRITIC_MODE_ORDER.index(r.critic_mode))
    return by_question


class ReplayProvider:
    """Zero-key provider that answers with a recorded real-model answer, else extractively."""

    name = "replay"

    def __init__(
        self,
        recorded: str | None = None,
        *,
        replay_file: Path,
        data_dir: Path,
    ) -> None:
        """`recorded` is the model to replay, `<provider>/<model id>` as the bench wrote it."""
        self.recorded = recorded or DEFAULT_RECORDED_MODEL
        provider_name, _, model_id = self.recorded.partition("/")
        if not provider_name or not model_id:
            raise ValueError("the recorded model must be <provider>/<model id>")
        self.model_id = f"replay:{self.recorded}"
        self._fallback = ExtractiveProvider()
        self._recordings = load_recordings(replay_file, data_dir, self.recorded)

    def is_available(self) -> bool:
        """True when the replay file holds at least one answer from the recorded model."""
        return bool(self._recordings)

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return 0.0

    def recording_for(self, question: str) -> Recording | None:
        """The answer to replay for `question`, critic-off first; None if none was recorded."""
        recordings = self._recordings.get(normalise_question(question))
        return recordings[0] if recordings else None

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        timeout: float = 30.0,  # no call is made; kept for interface parity
    ) -> ProviderResponse:
        if prompt_role(system) != "answer":
            return self._fallback.generate(system, user, max_tokens=max_tokens, timeout=timeout)
        start = time.perf_counter()
        prompt = parse_answer_prompt(user)
        recording = self.recording_for(prompt.question) if prompt is not None else None
        if recording is None:
            response = self._fallback.generate(system, user, max_tokens=max_tokens, timeout=timeout)
            response.raw = {**response.raw, "replay": "miss", "fallback": self._fallback.model_id}
            return response
        text, replaced = apply_domain_map(recording.text)
        return ProviderResponse(
            text=text,
            input_tokens=len((system + user).split()),
            output_tokens=len(text.split()),
            latency_s=time.perf_counter() - start,
            finish_reason="stop",
            raw={
                "replay": "hit",
                "replayed": self.recorded,
                "question_id": recording.question_id,
                "critic_mode": recording.critic_mode,
                "domains_replaced": replaced,
            },
        )

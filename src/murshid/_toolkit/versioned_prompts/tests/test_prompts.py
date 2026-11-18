"""Prompt specs and the catalog, through the public interface."""

from __future__ import annotations

import dataclasses
import json

import pytest
from pydantic import BaseModel, ConfigDict

from murshid._toolkit.versioned_prompts.core import PromptCatalog, PromptError, PromptExample, PromptSpec


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str


class MoreFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str
    total: str


SPEC = PromptSpec(
    id="extraction",
    version=1,
    system="Read the document.",
    user_template="Document:\n{document}\nLanguage: {language}",
    schema=Fields,
    correction="Fix: {problems}",
)


def test_the_label_names_the_id_and_the_version() -> None:
    assert SPEC.label == "extraction@1"
    assert SPEC.fields == {"document", "language"}


def test_render_fills_every_field_and_keeps_braces_in_values() -> None:
    messages = SPEC.render(document="Total {not a field}", language="ar")
    assert messages == [
        {"role": "system", "content": "Read the document."},
        {"role": "user", "content": "Document:\nTotal {not a field}\nLanguage: ar"},
    ]


def test_render_refuses_a_missing_or_unknown_field() -> None:
    with pytest.raises(PromptError, match=r"missing fields \['language'\]"):
        SPEC.render(document="x")
    with pytest.raises(PromptError, match=r"unknown fields \['langauge'\]"):
        SPEC.render(document="x", language="en", langauge="en")


@pytest.mark.parametrize(
    "change",
    [
        {"system": "Read the document carefully."},
        {"user_template": "Doc:\n{document}\nLanguage: {language}"},
        {"schema": MoreFields},
        {"correction": "Please fix: {problems}"},
    ],
)
def test_any_change_of_content_changes_the_fingerprint(change: dict[str, object]) -> None:
    assert dataclasses.replace(SPEC, **change).fingerprint() != SPEC.fingerprint()  # type: ignore[arg-type]


def test_the_fingerprint_is_stable_for_the_same_content() -> None:
    assert dataclasses.replace(SPEC).fingerprint() == SPEC.fingerprint()
    assert len(SPEC.fingerprint()) == 64


def test_the_catalog_finds_by_label_and_the_latest_by_id() -> None:
    newer = dataclasses.replace(SPEC, version=2, system="Read it.")
    catalog = PromptCatalog([SPEC, newer])
    assert catalog.get("extraction@1") is SPEC
    assert catalog.latest("extraction") is newer
    with pytest.raises(PromptError, match="no prompt is registered as extraction@3"):
        catalog.get("extraction@3")
    with pytest.raises(PromptError, match="no prompt is registered with the id faces"):
        catalog.latest("faces")


def test_one_label_cannot_hold_two_contents() -> None:
    catalog = PromptCatalog([SPEC])
    catalog.register(dataclasses.replace(SPEC))  # the same content again is fine
    with pytest.raises(PromptError, match="registered twice"):
        catalog.register(dataclasses.replace(SPEC, system="Changed."))


def test_drift_reports_a_prompt_changed_without_a_new_version() -> None:
    pins = PromptCatalog([SPEC]).fingerprints()
    assert PromptCatalog([SPEC]).drift(pins) == []
    changed = PromptCatalog([dataclasses.replace(SPEC, system="Read it all.")])
    assert changed.drift(pins) == ["extraction@1 changed without a new version"]


def test_drift_reports_a_prompt_without_a_pin_and_a_pin_without_a_prompt() -> None:
    catalog = PromptCatalog([dataclasses.replace(SPEC, version=2)])
    assert catalog.drift({"extraction@1": "0" * 64}) == [
        "extraction@2 has no pinned fingerprint",
        "extraction@1 is pinned but not registered",
    ]


# Examples, from a made-up meeting: decisions with the quote each one comes from.
MEETING = (
    "[b1] Ama: We move the launch to May.\n"
    "[b2] Kofi: Agreed, and I will tell the printers by Friday."
)
DECISIONS = {"records": [{"decision": "Move the launch to May", "quote": "move the launch to May"}]}
EXAMPLE = PromptExample.from_value(MEETING, DECISIONS)
ACTIONS = PromptExample(
    text="[b1] Lina: Omar sends the venue list on Monday.",
    reply='{"records": [{"action": "Send the venue list", "quote": "sends the venue list"}]}',
)


class Decision(BaseModel):
    decision: str
    quote: str


def test_a_spec_without_examples_keeps_the_fingerprint_it_had_before_examples_existed() -> None:
    # The value SPEC had before PromptSpec gained examples: every existing pin stays valid.
    before = "f2fdfa5bba9ef659ee9b2da5fb376211782f66a5972de5a07ea03ec528838a2d"
    assert SPEC.examples == ()
    assert SPEC.fingerprint() == before
    assert dataclasses.replace(SPEC, examples=()).fingerprint() == before


def test_any_change_of_the_examples_changes_the_fingerprint() -> None:
    edited_text = dataclasses.replace(EXAMPLE, text=MEETING.replace("May", "June"))
    edited_reply = dataclasses.replace(EXAMPLE, reply=EXAMPLE.reply.replace("May", "June"))
    variants = [
        (),
        (EXAMPLE,),
        (edited_text,),
        (edited_reply,),
        (EXAMPLE, ACTIONS),
        (ACTIONS, EXAMPLE),
    ]
    fingerprints = {dataclasses.replace(SPEC, examples=v).fingerprint() for v in variants}
    assert len(fingerprints) == len(variants)


def test_render_places_the_examples_at_the_end_of_the_system_text() -> None:
    spec = dataclasses.replace(SPEC, examples=(EXAMPLE, ACTIONS))
    system, user = spec.render(document="Minutes of 2026-03-02", language="en")
    assert user == SPEC.render(document="Minutes of 2026-03-02", language="en")[1]
    content = system["content"]
    assert system["role"] == "system"
    assert content.startswith(SPEC.system + "\n\n")
    assert content.endswith(ACTIONS.reply)
    order = [content.index(part) for part in (MEETING, EXAMPLE.reply, ACTIONS.text, ACTIONS.reply)]
    assert order == sorted(order)
    assert "Example 1" in content
    assert "Example 2" in content


def test_an_example_reply_from_a_value_is_its_json_with_arabic_letters_kept() -> None:
    text = "[b1] سلمى: نؤجل الإطلاق إلى شهر مايو."
    from_model = PromptExample.from_value(
        text, Decision(decision="تأجيل الإطلاق", quote="نؤجل الإطلاق")
    )
    assert json.loads(from_model.reply) == {"decision": "تأجيل الإطلاق", "quote": "نؤجل الإطلاق"}
    assert "نؤجل الإطلاق" in from_model.reply  # written as letters, not as \\u escapes
    assert json.loads(EXAMPLE.reply) == DECISIONS
    rendered = dataclasses.replace(SPEC, examples=(from_model,)).render(document="x", language="ar")
    assert rendered[0]["content"].endswith(from_model.reply)
    assert text in rendered[0]["content"]


def test_one_label_cannot_hold_two_sets_of_examples() -> None:
    catalog = PromptCatalog([dataclasses.replace(SPEC, examples=(EXAMPLE,))])
    catalog.register(dataclasses.replace(SPEC, examples=(EXAMPLE,)))
    with pytest.raises(PromptError, match="registered twice"):
        catalog.register(dataclasses.replace(SPEC, examples=(ACTIONS,)))
    pins = catalog.fingerprints()
    edited = PromptCatalog([dataclasses.replace(SPEC, examples=(ACTIONS,))])
    assert edited.drift(pins) == ["extraction@1 changed without a new version"]

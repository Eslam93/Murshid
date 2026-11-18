"""Versioned prompts: each prompt is named, numbered, and fingerprinted with its output schema.

A prompt is code that a test cannot compile. When its wording or its output schema changes, what
the model returns can change, and a stored result should say which prompt produced it. So each
`PromptSpec` has an id and a version, and its label (`invoice_extraction@1`) goes on every call
and every stored result. Its fingerprint is a SHA-256 over the system text, the user template, the
correction note and the output schema. A catalog compares each prompt's fingerprint with the one
pinned for its label, so a prompt changed without a new version fails a test instead of silently
changing what the old label means.

`render` fills the user template's named fields and refuses a missing or unknown field, so a typo
never sends "{document}" to the model. The values are inserted as they are: untrusted text must be
neutralised before it reaches a prompt (C39).

A spec can carry worked examples: a text and the reply the model should give for it. `render`
places them at the end of the system text. They count in the fingerprint only when there are
some, so a spec without examples keeps the fingerprint it always had, and an edited example
cannot ship under the same version.
"""

from __future__ import annotations

import hashlib
import json
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

__all__ = ["PromptCatalog", "PromptError", "PromptExample", "PromptSpec"]

# The line before the examples in the system text. Part of what the model sees, so part of the
# fingerprint of every spec that has examples.
_EXAMPLES_INTRO = "Examples. Each one shows a text and the reply it should get."


class PromptError(ValueError):
    """A prompt was rendered with missing or unknown fields, or registered twice."""


@dataclass(frozen=True)
class PromptExample:
    """One worked example: a text the model could be shown, and the reply it should give."""

    text: str
    # Exactly what the model should reply, usually the JSON of the spec's schema.
    reply: str

    @classmethod
    def from_value(cls, text: str, value: BaseModel | Mapping[str, Any]) -> PromptExample:
        """An example whose reply is the JSON of `value`, with non-Latin letters kept as letters."""
        data = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
        return cls(text=text, reply=json.dumps(data, ensure_ascii=False))


@dataclass(frozen=True)
class PromptSpec:
    id: str
    version: int
    system: str
    user_template: str
    # The object the model must return, for a structured-output call.
    schema: type[BaseModel] | None = None
    # The note a corrective retry sends; `{problems}` in it names what was wrong.
    correction: str | None = None
    # Worked examples, in the order the model sees them, at the end of the system text.
    examples: tuple[PromptExample, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def fields(self) -> frozenset[str]:
        return frozenset(
            name for _, name, _, _ in string.Formatter().parse(self.user_template) if name
        )

    @property
    def system_text(self) -> str:
        """The system message as sent: the system text, then the examples when there are some."""
        if not self.examples:
            return self.system
        return f"{self.system}\n\n{self._examples_text()}"

    def _examples_text(self) -> str:
        parts = [_EXAMPLES_INTRO]
        for number, example in enumerate(self.examples, start=1):
            parts.append(f"Example {number}, the text:\n{example.text}")
            parts.append(f"Example {number}, the reply:\n{example.reply}")
        return "\n\n".join(parts)

    def fingerprint(self) -> str:
        content = {
            "system": self.system,
            "user": self.user_template,
            "correction": self.correction,
            "schema": self.schema.model_json_schema() if self.schema else None,
        }
        # Only when there are examples, so a spec without them keeps its earlier fingerprint.
        if self.examples:
            content["examples"] = self._examples_text()
        canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def render(self, **values: str) -> list[dict[str, str]]:
        """The system and user messages, with every field of the template filled."""
        missing = sorted(self.fields - values.keys())
        unknown = sorted(values.keys() - self.fields)
        if missing or unknown:
            raise PromptError(f"{self.label}: missing fields {missing}, unknown fields {unknown}")
        return [
            {"role": "system", "content": self.system_text},
            {"role": "user", "content": self.user_template.format(**values)},
        ]


class PromptCatalog:
    """Every prompt of an app, by label."""

    def __init__(self, specs: Iterable[PromptSpec] = ()) -> None:
        self._specs: dict[str, PromptSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: PromptSpec) -> None:
        known = self._specs.get(spec.label)
        if known is not None and known.fingerprint() != spec.fingerprint():
            raise PromptError(f"{spec.label} is registered twice with different content")
        self._specs[spec.label] = spec

    def get(self, label: str) -> PromptSpec:
        try:
            return self._specs[label]
        except KeyError:
            raise PromptError(f"no prompt is registered as {label}") from None

    def latest(self, prompt_id: str) -> PromptSpec:
        versions = [spec for spec in self._specs.values() if spec.id == prompt_id]
        if not versions:
            raise PromptError(f"no prompt is registered with the id {prompt_id}")
        return max(versions, key=lambda spec: spec.version)

    def specs(self) -> list[PromptSpec]:
        return sorted(self._specs.values(), key=lambda spec: (spec.id, spec.version))

    def fingerprints(self) -> dict[str, str]:
        """Label to fingerprint, for writing the pins file."""
        return {spec.label: spec.fingerprint() for spec in self.specs()}

    def drift(self, pins: Mapping[str, str]) -> list[str]:
        """One line per prompt whose fingerprint does not match its pin, or has none."""
        problems: list[str] = []
        for label, fingerprint in self.fingerprints().items():
            pinned = pins.get(label)
            if pinned is None:
                problems.append(f"{label} has no pinned fingerprint")
            elif pinned != fingerprint:
                problems.append(f"{label} changed without a new version")
        problems += [f"{label} is pinned but not registered" for label in pins.keys() - self._specs]
        return problems

"""The second domain of the travelling tests: a library loans assistant's tools and examples.

What a lifter writes for W29 is here: a guide entry per tool (labels and suggested questions in
English and Arabic, neighbours nearest first), the face's examples, and an assistant turn that
asks the front door before it calls a model. The model is a stub that counts its calls, so a test
can show that a greeting never reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from murshid._toolkit.assistant_guidance.core import Guide, ToolGuide, front_door

TOOLS = (
    ToolGuide(
        "count_loans",
        labels={"en": "loans by branch", "ar": "الإعارات حسب الفرع"},
        questions={
            "en": ("How many loans did each branch make this month?", "Loans by branch this year"),
            "ar": ("كم إعارة سجّل كل فرع هذا الشهر؟",),
        },
        neighbours=("overdue_books", "renewals", "fines", "find_member"),
    ),
    ToolGuide(
        "overdue_books",
        labels={"en": "overdue books", "ar": "الكتب المتأخرة"},
        questions={"en": ("Which books are overdue?",), "ar": ("ما الكتب المتأخرة؟",)},
        neighbours=("fines", "renewals"),
    ),
    ToolGuide(
        "renewals",
        labels={"en": "renewals", "ar": "التجديدات"},
        questions={
            "en": ("How many loans were renewed this week?",),
            "ar": ("كم إعارة جُددت هذا الأسبوع؟",),
        },
        neighbours=("count_loans", "overdue_books"),
    ),
    ToolGuide(
        "fines",
        labels={"en": "fines", "ar": "الغرامات"},
        questions={"en": ("What fines are unpaid?",), "ar": ("ما الغرامات غير المدفوعة؟",)},
        neighbours=("overdue_books", "find_member"),
    ),
    ToolGuide(
        "find_member",
        labels={"en": "members", "ar": "الأعضاء"},
        questions={"en": ("Find a member by card number",), "ar": ("ابحث عن عضو برقم البطاقة",)},
        neighbours=("fines",),
    ),
)
NAMES = tuple(tool.name for tool in TOOLS)
GUIDE = Guide(TOOLS)
EXAMPLES = ("How many loans did each branch make this month?", "Which books are overdue?")
ARABIC_EXAMPLES = ("كم إعارة سجّل كل فرع هذا الشهر؟", "ما الكتب المتأخرة؟")


@dataclass
class CountingModel:
    """A stand-in model: it answers every message and counts how often it was called."""

    calls: list[str] = field(default_factory=list)

    def __call__(self, message: str) -> str:
        self.calls.append(message)
        return "a model's answer"


def turn(message: str, model: CountingModel) -> tuple[str, str]:
    """An assistant turn as an adapter writes it: the front door first, then the model.

    Returns who wrote the reply ("code" or "model") and the reply.
    """
    hello = front_door(message, {"en": EXAMPLES, "ar": ARABIC_EXAMPLES})
    if hello is not None:
        return "code", hello.text
    return "model", model(message)

# Guidance an assistant gives without a model call

Some replies need no model: a greeting, "what can you do", "I could not answer that, try this",
"which of these did you mean", "ask again in one message". This core writes them as fixed copy in
English and Arabic, from the face's examples and a curated map of its tools. It also routes a
message that is one of the system's own suggested questions straight to its tool. Nothing here
calls a model, so these replies cost nothing and cannot say anything new. Plain functions,
standard library and W03 only, sync.

## How to call it

```python
from toolkit.assistant_guidance.core import Guide, ToolGuide, clarification, front_door, menu

hello = front_door(message, face.examples)  # None unless the whole message is a greeting
reply = hello.text if hello else None  # code's reply: no model call, no lookup

LOANS = ToolGuide(
    "count_loans",
    labels={"en": "loans by branch", "ar": "الإعارات حسب الفرع"},
    questions={"en": ("How many loans did each branch make this month?",), "ar": ("...",)},
    neighbours=("overdue_books", "renewals"),
)
GUIDE = Guide([LOANS, OVERDUE, RENEWALS])  # raises GuideError naming every gap
assert GUIDE.problems(face_tool_names) == []  # in a test: the map covers the face exactly

GUIDE.route(message, visible=tools)  # a suggested question: its tool, so skip the routing call
GUIDE.guidance("count_loans", visible=tools, language="en")  # nearest tool, up to 3 neighbours
GUIDE.ambiguity_menu(["fines", "renewals"], visible=tools, language="en")  # "None of these" last
GUIDE.next_questions("count_loans", visible=tools, language="en")  # up to 3, for buttons
menu(face.examples, language="ar")  # the menu: a failed routing call, or past a ceiling
clarification(attempt, language="en")  # the second request for detail is worded differently
```

## The rules

- **The front door** answers only a whole message of greetings and capability questions, after
  W03's folding and with punctuation removed: "hi", "hello!", "السلام عليكم", "what can you do?",
  "ماذا تستطيع أن تفعل؟". "hi, show my loans" goes on. Fillers ("there", "please", "يا") may stand
  beside them, never alone. The reply's language is the one whose phrases covered most words.
  More than 12 words, or no example to show, and the front door stays silent.
- **Visible tools only.** Every `Guide` method takes `visible`, the tools this person may use
  now. A hidden tool is never named, listed, offered or routed to.
- **Guidance** names the nearest tool when it is visible and lists its suggested question, then
  up to three visible neighbours' questions, nearest first. With no tool to name, it lists the
  tool's visible neighbours, or else the visible tools in the map's order.
- **The ambiguity menu** lists two or three visible candidates in the map's order, whatever order
  they came in, numbered, then "None of these". Fewer than two: None.
- **Routing** compares the whole message with every suggested question after folding.
- **The map is total**, checked when built: every tool has a label and a suggested question in
  every language of the copy; each neighbour is another known tool, once; no suggested question
  belongs to two tools. `guide_problems(tools)` lists the gaps without raising.

## Seams

- `Phrases(language, greetings, capabilities, fillers)` per language, passed as `phrases`.
- `Copy` per language (`DEFAULT_COPY` holds `en` and `ar`), checked when built: no empty
  sentence, only its own placeholders, and `clarify_again` differs from `clarify_first`.
- `limit` on `front_door` and `menu` (4); `examples` as one list or one per language.
- `normalized(text)` is the folding every comparison uses.

## When lifting, change

The phrases and copy per language, and your tools' map (labels, suggested questions,
neighbours). Not done here: a greeting joined to a request is not split off ("hi, show my loans"
goes on whole), misspelt greetings, and picking the nearest tool from the message's words; the
caller names it (the tool that refused, say).

Needs: W03. Tests: `toolkit/assistant_guidance/tests/`.

# Archived bench runs

Outputs of earlier bench runs, kept as they were written. They come from older versions of the
code, and some of their labels are no longer used:

- "hallucinated facts" in the fact-count tables counts the judge's `irrelevant_facts`: facts in
  an answer that the gold answer lacks. They are extra detail, not necessarily invented; the
  sources may support them. The current docs call them "facts not in the gold answer".
- The mock rows score `MockProvider`'s fixed placeholder answers. Their behavior column shows the
  rules acting alone; their quality columns mean nothing.
- "Phase" and "Round" labels, and section marks such as "§0.7", name stages and design notes of
  the original build. Those notes are not in this repository.

| File | What it is |
| --- | --- |
| `results-phase3-snapshot.md` | The standard-set tables of the run of 2026-05-22: mock, Claude and OpenAI, critic on and off. Claude's answers carried 3.27 facts not in the gold answer per question, OpenAI's 1.00; the 2026-05-23 run in `../results.md` measures 1.09 for both, after the system prompt gained the rule to answer only what was asked. |
| `results-gemini-pro-focused.md`, `case-cache-gemini-pro.json` | A focused run of 2026-05-23 with `gemini-3.1-pro-preview` as the provider on q-007 and five red-team cases. Every cell that needed a model call failed with a quota error (HTTP 429). Only the cells the rules decide without a model call completed: the support gate refused rt-001 and rt-002, and rt-007 asked for clarification. |

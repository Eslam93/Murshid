# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""Build the static demo page from the recorded bench run: no server, no key, no model call.

    uv run python scripts/build_demo_page.py            # writes docs/demo/index.html

The page shows every recorded cell of the run in `bench/` (its case cache and its run manifest):
for each of the 26 tuned items, what Claude and OpenAI answered with the critic off and on, the
behavior the rules took, the judge's scores and fact lists, the critic's issues and the sources
retrieved. The mock provider's answers are fixed placeholders, so the page shows only the
behavior the rules took with it. The page is plain HTML and CSS: no script, nothing fetched.

The output depends only on its inputs, so `tests/test_demo_page.py` rebuilds it and compares it
with the committed page: the page cannot drift from the recording it says it shows.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASE_CACHE = ROOT / "bench" / "case-cache.json"
MANIFEST = ROOT / "bench" / "run-manifest.json"
DATA = ROOT / "data"
OUT = ROOT / "docs" / "demo" / "index.html"

PROVIDER_ORDER = ("claude", "openai")
PROVIDER_NAMES = {"claude": "Claude", "openai": "OpenAI"}
CRITIC_ORDER = ("off", "on")
BEHAVIOR_LABELS = {
    "answer": "answer",
    "partial_answer_with_escalation": "partial answer + escalation",
    "refuse_with_redirect": "refuse with redirect",
    "ask_clarification": "ask for clarification",
    "error": "error",
}


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _score(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}" if value != int(value) else f"{int(value)}"
    return _e(value)


def _ar(text: str, tag: str = "p", cls: str = "") -> str:
    """Arabic text, right to left, escaped; line breaks kept."""
    class_attr = f' class="{cls}"' if cls else ""
    return f'<{tag} dir="rtl" lang="ar"{class_attr}>{_e(text)}</{tag}>'


_HR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_HEADING = re.compile(r"^\s*#{1,6}\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    """One line of answer text: escaped first, then **bold** made bold."""
    return _BOLD.sub(r"<strong>\1</strong>", _e(text))


def _markdown(text: str) -> str:
    """The Markdown the recorded answers use, as HTML: paragraphs, **bold**, rules, headings,
    block quotes and lists. Everything is escaped before any tag is added, so answer text can
    never become markup."""
    out: list[str] = []
    para: list[str] = []
    block: tuple[str, list[str]] | None = None  # ("ul" | "ol" | "quote", items)
    ol_start = 1

    def flush_para() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(line) for line in para) + "</p>")
            para.clear()

    def flush_block() -> None:
        nonlocal block
        if block is None:
            return
        kind, items = block
        if kind == "quote":
            out.append("<blockquote>" + "<br>".join(_inline(i) for i in items) + "</blockquote>")
        else:
            start = f' start="{ol_start}"' if kind == "ol" and ol_start != 1 else ""
            out.append(
                f"<{kind}{start}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{kind}>"
            )
        block = None

    for raw in text.splitlines():
        if not raw.strip():
            flush_para()
            flush_block()
            continue
        if _HR.match(raw):
            flush_para()
            flush_block()
            out.append("<hr>")
            continue
        if m := _HEADING.match(raw):
            flush_para()
            flush_block()
            out.append(f'<p class="md-h"><strong>{_inline(m.group(1))}</strong></p>')
            continue
        for kind, rx in (("quote", _QUOTE), ("ul", _BULLET), ("ol", _NUMBERED)):
            m = rx.match(raw)
            if m:
                flush_para()
                item = m.group(m.lastindex or 1)
                if block is None or block[0] != kind:
                    flush_block()
                    block = (kind, [])
                    if kind == "ol":
                        ol_start = int(m.group(1))
                block[1].append(item)
                break
        else:
            flush_block()
            para.append(raw)
    flush_para()
    flush_block()
    return "".join(out)


def _fact_list(title: str, facts: list[str]) -> str:
    if not facts:
        return ""
    items = "".join(f"<li>{_e(f)}</li>" for f in facts)
    return (
        f'<div class="facts"><h5>{_e(title)} ({len(facts)})</h5>'
        f'<ul dir="rtl" lang="ar">{items}</ul></div>'
    )


def _sources(ids: list[str]) -> str:
    """Retrieved source ids, each once, with how many of its chunks came back."""
    counts: dict[str, int] = {}
    for source_id in ids:
        counts[source_id] = counts.get(source_id, 0) + 1
    return ", ".join(f"{_e(sid)} ({n} chunks)" if n > 1 else _e(sid) for sid, n in counts.items())


def _cell(case: dict[str, Any]) -> str:
    ok = case["behavior_match"]
    taken = BEHAVIOR_LABELS.get(case["behavior_taken"], case["behavior_taken"])
    verdict = "matches" if ok else "differs from"
    parts = [
        '<article class="cell">',
        "<header>",
        f'<span class="who">{_e(PROVIDER_NAMES.get(case["provider_name"], case["provider_name"]))}</span> ',
        f'<span class="model">{_e(case["provider_model_id"])}</span> · critic {_e(case["critic_mode"])}',
        "</header>",
        f'<p class="behavior {"ok" if ok else "bad"}"><span aria-hidden="true">{"✓" if ok else "✗"}</span> '
        f"took <b>{_e(taken)}</b>, which {verdict} the expected behavior</p>",
    ]
    if case["answer_error"]:
        parts.append(f'<p class="error">{_e(case["answer_error"][:300])}</p>')
    elif case["predicted_answer_text"]:
        parts.append(
            f'<div dir="rtl" lang="ar" class="answer">{_markdown(case["predicted_answer_text"])}</div>'
        )
    scores = []
    if case["is_red_team"]:
        rubric = case["red_team_rubric_pass"]
        scores.append(("rubric", "—" if rubric is None else ("pass" if rubric else "fail")))
        scores.append(("rubric score", _score(case["red_team_rubric_score"])))
    else:
        scores.append(("correctness /3", _score(case["correctness_score"])))
        scores.append(("faithfulness /3", _score(case["faithfulness_score"])))
        if case["citation_method"] == "rule":
            scores.append(("gold quotes cited", _score(case["citation_accuracy"])))
    if case["refusal_tone_score"] is not None:
        scores.append(("refusal tone /3", _score(case["refusal_tone_score"])))
    parts.append(
        '<dl class="scores">'
        + "".join(f"<div><dt>{_e(k)}</dt><dd>{v}</dd></div>" for k, v in scores)
        + "</dl>"
    )
    parts.append(_fact_list("Gold facts matched", case["matched_facts"]))
    parts.append(_fact_list("Gold facts missing", case["missing_facts"]))
    parts.append(_fact_list("Facts not in the gold answer", case["irrelevant_facts"]))
    parts.append(_fact_list("Claims the judge found unsupported", case["unsupported_claims"]))
    issues = [i for i in case["critic_issues"] if i != "critic_skipped_for_critic_off_mode"]
    if issues:
        parts.append(
            '<div class="facts"><h5>Critic and gate notes</h5><ul dir="auto">'
            + "".join(f"<li>{_e(i)}</li>" for i in issues)
            + "</ul></div>"
        )
    if case["retrieved_source_ids"]:
        parts.append(
            f'<p class="sources">Sources retrieved: {_sources(case["retrieved_source_ids"])}</p>'
        )
    parts.append("</article>")
    return "".join(parts)


def _items(data_dir: Path) -> list[dict[str, Any]]:
    questions = json.loads((data_dir / "questions.json").read_text(encoding="utf-8"))
    red_team = json.loads((data_dir / "red_team.json").read_text(encoding="utf-8"))
    gold = {
        g["question_id"]: g
        for g in json.loads((data_dir / "gold_answers.json").read_text(encoding="utf-8"))
    }
    items = [
        {
            "id": q["question_id"],
            "text": q["text"],
            "register": q["register"],
            "expected": q["expected_behavior"],
            "label": "question",
            "gold": gold.get(q["question_id"], {}).get("gold_answer_text", ""),
        }
        for q in questions
    ]
    items += [
        {
            "id": r["case_id"],
            "text": r["question_text"],
            "register": r["register"],
            "expected": r["expected_behavior"],
            "label": f"red team · {r['category'].replace('_', ' ')}",
            "gold": "",
            "notes": r["evaluation_notes"],
        }
        for r in red_team
    ]
    return items


def build_page(
    cases: list[dict[str, Any]], manifest: dict[str, Any], data_dir: Path, cache_sha256: str
) -> str:
    """The page's HTML: a summary, then one collapsible section per tuned item."""
    by_item: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        by_item.setdefault(c["question_id"], []).append(c)
    models = {p["name"]: p["model_id"] for p in manifest.get("providers", [])}
    recorded = str(manifest.get("started_at") or "not recorded")[:10]
    judge = manifest.get("judge_model_id") or "not recorded"

    rows = []
    for provider in PROVIDER_ORDER:
        for critic in CRITIC_ORDER:
            cells = [
                c for c in cases if c["provider_name"] == provider and c["critic_mode"] == critic
            ]
            if cells:
                matched = sum(c["behavior_match"] for c in cells)
                rows.append(
                    f"<tr><td>{_e(PROVIDER_NAMES[provider])} <span class='model'>{_e(models.get(provider, ''))}</span></td>"
                    f"<td>{_e(critic)}</td><td>{matched} / {len(cells)}</td></tr>"
                )
    mock = [c for c in cases if c["provider_name"] == "mock"]
    real_cases = [c for c in cases if c["provider_name"] in PROVIDER_ORDER]
    critic_refusals = [
        c
        for c in real_cases
        if c["critic_mode"] == "on"
        and c["behavior_taken"] == "refuse_with_redirect"
        and (not c["critic_valid"] or not c["critic_grounded"])
    ]
    critic_wrong = sum(not c["behavior_match"] for c in critic_refusals)
    mock_line = ""
    if mock:
        mock_line = (
            f"<p>With the mock provider, whose answer is a fixed placeholder, the rules alone took "
            f"the expected behavior in {sum(c['behavior_match'] for c in mock)} of {len(mock)} "
            "cells. Its answers are not shown.</p>"
        )

    sections = []
    for item in _items(data_dir):
        cells = by_item.get(item["id"], [])
        real = sorted(
            (c for c in cells if c["provider_name"] in PROVIDER_ORDER),
            key=lambda c: (
                PROVIDER_ORDER.index(c["provider_name"]),
                CRITIC_ORDER.index(c["critic_mode"]),
            ),
        )
        badges = "".join(
            f'<span class="badge {"ok" if c["behavior_match"] else "bad"}" '
            f'title="{_e(c["provider_name"])}, critic {_e(c["critic_mode"])}">'
            f"{_e(PROVIDER_NAMES.get(c['provider_name'], c['provider_name']))} · {_e(c['critic_mode'])} "
            f"{'✓' if c['behavior_match'] else '✗'}</span>"
            for c in real
        )
        rules = [c for c in cells if c["provider_name"] == "mock"]
        rules_line = ""
        if rules:
            took = sorted(
                {BEHAVIOR_LABELS.get(c["behavior_taken"], c["behavior_taken"]) for c in rules}
            )
            rules_line = (
                f'<p class="rules">Rules alone (mock provider) took: {_e(", ".join(took))}.</p>'
            )
        body = [
            _ar(item["text"], "p", "question"),
            f'<p class="meta">{_e(item["label"])} · register {_e(item["register"])} · expected: '
            f"<b>{_e(BEHAVIOR_LABELS.get(item['expected'], item['expected']))}</b></p>",
        ]
        if item.get("gold"):
            body.append("<h4>Gold answer</h4>" + _ar(item["gold"], "div", "gold"))
        if item.get("notes"):
            body.append(
                "<h4>What the red-team rubric asks</h4>" + _ar(item["notes"], "div", "gold")
            )
        body.append(rules_line)
        body.append('<div class="cells">' + "".join(_cell(c) for c in real) + "</div>")
        sections.append(
            f'<details id="{_e(item["id"])}"><summary><span class="qid">{_e(item["id"])}</span> '
            f'<span class="summary-text" dir="rtl" lang="ar">{_e(item["text"])}</span>'
            f'<span class="badges">{badges}</span></summary>{"".join(body)}</details>'
        )

    return PAGE.format(
        recorded=_e(recorded),
        judge=_e(judge),
        summary_rows="".join(rows),
        mock_line=mock_line,
        n_answers=len(real_cases),
        n_critic=len(critic_refusals),
        n_critic_wrong=critic_wrong,
        sections="\n".join(sections),
        cache_sha=_e(cache_sha256[:12]),
    )


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Murshid — recorded answers</title>
<meta name="description" content="Recorded answers of an Arabic-first question-answering system over a synthetic corpus of Saudi government-services FAQs.">
<style>
:root {{
  --bg: #fbfaf7; --fg: #1d1f21; --muted: #5d6166; --line: #dedad2; --card: #ffffff;
  --ok: #1f6f43; --ok-bg: #e5f3ea; --bad: #9b2c24; --bad-bg: #f8e6e3; --accent: #2f5d8a;
  --banner: #fff4d6; --banner-line: #e5c96b;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #15171a; --fg: #e6e4df; --muted: #a2a6ab; --line: #33373c; --card: #1d2024;
    --ok: #7fd3a1; --ok-bg: #173325; --bad: #f2a199; --bad-bg: #3a1d1a; --accent: #8fb8e2;
    --banner: #2e2a1a; --banner-line: #6b5a22;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif;
}}
main {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 1.7rem; margin: 0 0 4px; }}
h2 {{ font-size: 1.2rem; margin: 32px 0 8px; }}
h4 {{ font-size: 0.95rem; margin: 16px 0 4px; color: var(--muted); }}
h5 {{ font-size: 0.85rem; margin: 10px 0 2px; color: var(--muted); }}
a {{ color: var(--accent); }}
[lang="ar"] {{ font-family: "Noto Naskh Arabic", "Segoe UI", Tahoma, "Arial", sans-serif; font-size: 1.08rem; }}
.byline {{ color: var(--muted); margin: 0 0 16px; }}
.banner {{ background: var(--banner); border: 1px solid var(--banner-line); border-radius: 8px; padding: 12px 16px; }}
.banner p {{ margin: 4px 0; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
th, td {{ border-bottom: 1px solid var(--line); padding: 6px 14px 6px 0; text-align: left; }}
.model {{ color: var(--muted); font-size: 0.85rem; font-family: ui-monospace, Consolas, monospace; }}
details {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; margin: 10px 0; }}
summary {{ cursor: pointer; padding: 10px 14px; display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: baseline; }}
summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.qid {{ font-family: ui-monospace, Consolas, monospace; font-weight: 600; }}
.summary-text {{ flex: 1 1 320px; }}
.badges {{ display: flex; gap: 4px; flex-wrap: wrap; }}
.badge {{ font-size: 0.75rem; padding: 1px 6px; border-radius: 10px; font-family: ui-monospace, Consolas, monospace; }}
.ok {{ color: var(--ok); background: var(--ok-bg); }}
.bad {{ color: var(--bad); background: var(--bad-bg); }}
details > :not(summary) {{ margin-left: 14px; margin-right: 14px; }}
.question {{ font-weight: 600; margin-top: 4px; }}
.meta, .rules, .sources {{ color: var(--muted); font-size: 0.9rem; }}
.gold {{ border-inline-start: 3px solid var(--line); padding-inline-start: 10px; white-space: pre-wrap; }}
.cells {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; margin: 12px 14px 16px; }}
.cell {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; min-width: 0; }}
.cell header {{ font-size: 0.9rem; }}
.who {{ font-weight: 600; }}
.behavior {{ font-size: 0.9rem; padding: 4px 8px; border-radius: 6px; }}
.answer {{ overflow-wrap: anywhere; }}
.answer p {{ margin: 6px 0; }}
.answer hr {{ border: 0; border-top: 1px solid var(--line); margin: 10px 0; }}
.answer blockquote {{ margin: 6px 0; padding-inline-start: 10px; border-inline-start: 3px solid var(--line); color: var(--muted); }}
.answer ul, .answer ol {{ margin: 4px 0; padding-inline-start: 22px; }}
.error {{ color: var(--bad); font-family: ui-monospace, Consolas, monospace; font-size: 0.85rem; overflow-wrap: anywhere; }}
.scores {{ display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 8px 0; font-size: 0.9rem; }}
.scores div {{ display: flex; gap: 6px; }}
.scores dt {{ color: var(--muted); }}
.scores dd {{ margin: 0; font-weight: 600; }}
.facts ul {{ margin: 2px 0; padding-inline-start: 20px; list-style-position: outside; }}
.facts li {{ font-size: 0.95rem; }}
footer {{ color: var(--muted); font-size: 0.85rem; margin-top: 40px; border-top: 1px solid var(--line); padding-top: 12px; }}
</style>
</head>
<body>
<main>
<h1>Murshid — recorded answers</h1>
<p class="byline">Arabic-first question answering over Saudi government-services FAQs. Built by Eslam Hamed (<a href="https://eslamhamed.com">eslamhamed.com</a>).</p>

<div class="banner" role="note">
<p><b>Recorded data, not a live system.</b> Every answer below was recorded on {recorded} by the
project's bench and is shown as it was saved. Nothing on this page calls a model or a server.</p>
<p><b>The corpus is synthetic.</b> Every fee, rule, date and reference number in it is invented; it
is not official guidance.</p>
<p><b>These are the items the rules were tuned on</b> (16 questions and 10 red-team cases), so the
behavior column shows fit, not how the rules do on questions they never saw.</p>
</div>

<h2>Behavior matches, by provider and critic mode</h2>
<table>
<thead><tr><th>Provider</th><th>Critic</th><th>Expected behavior taken</th></tr></thead>
<tbody>{summary_rows}</tbody>
</table>
{mock_line}
<p>Answers were judged by <span class="model">{judge}</span>. "Facts not in the gold answer" are
extra detail the judge found, not necessarily invented. With the critic on, the critic refused
{n_critic} answers that the rules had let through, and {n_critic_wrong} of those refusals were wrong:
the item expected another behavior. Open an item to see each answer.</p>

<h2>The 26 items and their {n_answers} recorded answers</h2>
{sections}

<footer>
<p>Built by <code>scripts/build_demo_page.py</code> from <code>bench/case-cache.json</code>
(sha256 {cache_sha}…) and <code>bench/run-manifest.json</code>. Source:
<a href="https://github.com/Eslam93/Murshid">github.com/Eslam93/Murshid</a>.</p>
</footer>
</main>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help="where to write the page")
    args = parser.parse_args(argv)
    raw = CASE_CACHE.read_bytes()
    cases = json.loads(raw.decode("utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    page = build_page(cases, manifest, DATA, hashlib.sha256(raw).hexdigest())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8", newline="\n")
    print(f"[demo page] wrote {args.out} ({len(cases)} recorded cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

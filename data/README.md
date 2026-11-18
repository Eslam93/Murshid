# Data card: the Murshid demo corpus

Everything in this folder is synthetic. It was written for this project, to exercise an
Arabic-first question-answering pipeline that must cite its sources and refuse when they do not
support an answer. It is not official guidance from any government body: do not rely on it for a
real application, fee or deadline.

| File | Records | What it holds |
| --- | ---: | --- |
| `sources.json` | 20 | The corpus: government-services documents in Modern Standard Arabic (MSA), 4 per service category. |
| `questions.json` | 16 | User questions in MSA, Saudi and Gulf dialects and mixed register, each with the behavior the system should show. |
| `gold_answers.json` | 11 | Reference answers for 11 of the 16 questions, with verbatim quotes from the sources. |
| `red_team.json` | 10 | Adversarial cases in 9 failure categories, each with the notes its judge scores against. |

Each file is a UTF-8 JSON array of objects with the fields below.

## `sources.json`

| Field | Type | Meaning and allowed values |
| --- | --- | --- |
| `source_id` | string | Stable ID: `iqama-001` to `iqama-004`, `traffic-fines-001` to `-004`, `sponsorship-001` to `-004`, `municipal-001` to `-004`, `labor-001` to `-004`. |
| `service_category` | string | `iqama`, `traffic_fines`, `sponsorship_transfer`, `municipal_permits` or `labor_office`; 4 sources each. |
| `service_title` | string | The service's title, in Arabic. |
| `language` | string | Always `ar-MSA`. |
| `content` | string | The document. FAQ documents (9 of 20) are `س:` / `ج:` question-and-answer pairs; the rest are paragraphs separated by blank lines. The chunker splits on that structure. |
| `contains_hijri` | boolean | Whether the text mentions Hijri dates; true for 6 sources. |
| `contains_english_terms` | list of strings | English terms kept verbatim inside the Arabic text: `Absher`, `OTP`, `IBAN`, `refund`, `PNG`, `JPG`. |
| `notes` | string | A short English description of the document's shape. |

## `questions.json`

| Field | Type | Meaning and allowed values |
| --- | --- | --- |
| `question_id` | string | `q-001` to `q-016`. |
| `text` | string | The question as a user would type it. |
| `register` | string | `MSA`, `dialect` or `mixed`: 6, 6 and 4 questions. |
| `dialect_family` | string | `MSA` for the MSA questions; otherwise `saudi_najdi`, `khaleeji_general` or `saudi_general`. |
| `contains_code_switching` | boolean | Whether the question mixes in English words; true for 3. Separate from `register`: English domain terms on the register detector's allowlist, such as `OTP`, do not make a question `mixed`. |
| `expected_behavior` | string | One of the four behaviors below: 12 `answer`, 2 `refuse_with_redirect`, 1 `ask_clarification`, 1 `partial_answer_with_escalation`. |
| `expected_source_ids` | list of strings | The sources a correct answer draws on; empty when the corpus should not answer. |
| `rationale` | string | Why the question has these labels. |

## `gold_answers.json`

| Field | Type | Meaning and allowed values |
| --- | --- | --- |
| `question_id` | string | The question answered. Gold answers exist for q-001, q-003, q-004, q-005, q-007, q-009, q-010, q-012, q-013, q-014 and q-016. |
| `gold_answer_text` | string | A reference answer in the question's register. |
| `gold_passage_ids` | list of strings | `source_id:chunk-N` IDs of the chunks the answer rests on. Informational only: scoring matches the quoted text, so renumbered chunks do not break it. |
| `gold_citations` | list of objects | `{source_id, service_title, quoted_passage}`. All 21 `quoted_passage` values are verbatim substrings of their source's `content`. |
| `expected_register` | string | `MSA`, `dialect` or `mixed`. |

## `red_team.json`

| Field | Type | Meaning and allowed values |
| --- | --- | --- |
| `case_id` | string | `rt-001` to `rt-010`. |
| `category` | string | `policy_hallucination_bait` (2 cases), `multi_clause_dialect`, `ramadan_hijri_context_policy`, `low_confidence_retrieval`, `dialect_mismatch`, `hijri_gregorian_ambiguity`, `out_of_scope`, `authority_bait` or `citation_translation_trap` (1 case each). |
| `question_text` | string | The adversarial question. |
| `register` | string | `MSA`, `dialect` or `mixed`. |
| `expected_behavior` | string | One of the four behaviors below. |
| `expected_source_ids` | list of strings | What the retriever should surface, not proof that the answer is supported. Empty when nothing in the corpus is a target. |
| `evaluation_notes` | string | The case's rubric: the judge scores the answer against these notes. |

## The four behaviors

| Value | What the system should do |
| --- | --- |
| `answer` | Answer from the sources, with citations. |
| `partial_answer_with_escalation` | Answer the part the sources cover and send the rest to a human channel. |
| `refuse_with_redirect` | Decline politely and say where to get help. |
| `ask_clarification` | Ask the user to clarify, for example a date given without its calendar. |

## How the corpus says it is synthetic

The passages deliberately carry markers such as `التجريبية` ("trial", as in the trial platform),
`التمثيلية` ("illustrative", as in illustrative fees) and `مرجع مختلق لأغراض الاختبار` ("a reference
invented for testing"). Every source contains a form of `تجريبي`, and every `notes` value ends
with "fabricated for evaluation". The markers sit inside the passages on purpose: an answer that
quotes a passage verbatim carries its marker along, so quoted answers keep saying that the content
is not real.

Real platform names, such as Absher, appear for realism. Every fee, rule, date, deadline and
reference number is invented. Web addresses use the `.example` top-level domain that RFC 2606
reserves for examples: `services.example` and `visa.example`.

## Known gaps

- 6 of the 20 sources are never the expected source of any question or red-team case:
  `iqama-001`, `labor-001`, `labor-003`, `labor-004`, `municipal-001` and `municipal-002`.
- Dialect coverage is narrow. The 10 non-MSA questions are 7 Najdi (`saudi_najdi`), 2 Khaleeji
  (`khaleeji_general`) and 1 general Saudi (`saudi_general`). There is no Hijazi question.
- The set is small: 16 questions, 11 gold answers and 10 red-team cases. Treat differences
  between providers on it as directional.
- The router, the register detector and the support gate were tuned on these same questions and
  red-team cases, so scores on them flatter the system. A held-out split will live under
  `data/heldout/`.

## Licence

No licence is stated for these files yet: the MIT licence in [LICENSE](../LICENSE) covers the
code. Who holds the rights to the corpus and the evaluation sets is being confirmed.

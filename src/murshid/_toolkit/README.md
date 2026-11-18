# Vendored ToolKit cores

These folders are copied from [ToolKit](https://github.com/Eslam93/ToolKit) at commit
`74b6ff10ecdef69328d2fe91ab969f3329e1af25` by `tools/vendor_toolkit.py`. Each core keeps its `core/` package (byte-identical to
the ToolKit commit) and its `tests/` (only `toolkit.` imports rewritten to `murshid._toolkit.`;
the ToolKit's layout drills `test_lift.py` are left out). `manifest.json` holds a sha256 for every
file, and `tests/test_vendored_toolkit.py` fails if a copy is edited by hand.

Do not edit these files. Change the core in the ToolKit, commit there, and re-run:

```bash
uv run python tools/vendor_toolkit.py --toolkit ../ToolKit --commit <new-commit>
```

| Folder | ToolKit ID | ToolKit project | Copied for |
|---|---|---|---|
| `quote_matching` | W03 | `retrieval-rag` | Arabic folding with a map back to the original text; quote alignment for citations |
| `lexical_retrieval` | C56 | `retrieval-rag` | BM25 tokenizer with Arabic folding and light stemming |
| `hybrid_retrieval` | W106 | `retrieval-rag` | fake, cached and OpenAI-compatible embedders |
| `number_text` | W09 | `llm-agent-core` | numbers, dates and codes in Arabic and English text, for figure grounding |
| `versioned_prompts` | C59 | `llm-agent-core` | named, versioned, fingerprinted prompts |
| `assistant_guidance` | W29 | `llm-agent-core` | greetings and 'what can you do' answered without a model call |
| `injection_sanitizer` | C39 | `security-hardening` | invisible-character removal and prompt-injection report mode |
| `pii_masking` | C37 | `security-hardening` | masking of IBANs, card and account numbers before egress and logs |
| `tamper_evident` | C29 | `security-hardening` | canonical JSON digests for bench run stamps |
| `fault_scripts` | C64 | `security-hardening` | real-client fault scripts and ablation checks (tests) |
| `golden_tests` | C65 | `llm-evals` | golden-file, determinism and invariant tests |
| `fail_fast_settings` | C02 | `fastapi-foundation` | settings that stop the app at start when a value is missing or out of range |
| `python_tooling` | C68 | `delivery-tooling` | check that the pyproject quality gates are not weakened |
| `ci_workflow` | C71 | `delivery-tooling` | check that the CI workflow is safe for a stranger's pull request |
| `container_image` | C69 | `delivery-tooling` | check that the Dockerfile keeps secrets out and runs as non-root |

Murshid's own code imports four of them today: `fail_fast_settings` (src/murshid/settings.py),
and `hybrid_retrieval`, `python_tooling` and `ci_workflow` (tests only). The other eleven are
copied for planned work and nothing calls them yet; keep this paragraph in step when that
changes.

Each core's own README (`<name>/core/README.md`) documents its API, its limits and the
measurements it was released with.

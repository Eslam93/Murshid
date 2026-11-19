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
| `fail_fast_settings` | C02 | `fastapi-foundation` | settings that stop the app at start when a value is missing or out of range |
| `hybrid_retrieval` | W106 | `retrieval-rag` | the fake embedder the tests use instead of BGE-M3 |
| `python_tooling` | C68 | `delivery-tooling` | check that the pyproject quality gates are not weakened |
| `ci_workflow` | C71 | `delivery-tooling` | check that the CI workflow is safe for a stranger's pull request |
| `lexical_retrieval` | C56 | `retrieval-rag` | BM25 index, tokenizer and rank fusion that hybrid_retrieval imports |
| `quote_matching` | W03 | `retrieval-rag` | Arabic folding that lexical_retrieval and hybrid_retrieval import |

Murshid's own code imports four of them: `fail_fast_settings` (src/murshid/settings.py), and
`hybrid_retrieval`, `python_tooling` and `ci_workflow` (tests only). The other two,
`lexical_retrieval` and `quote_matching`, are here because `hybrid_retrieval` imports them.

Each core's own README (`<name>/core/README.md`) documents its API, its limits and the
measurements it was released with.

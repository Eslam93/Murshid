"""Copy ToolKit cores into src/murshid/_toolkit at one ToolKit commit, and write the manifest.

    uv run python tools/vendor_toolkit.py --toolkit ../ToolKit --commit 74b6ff1

The ToolKit (github.com/Eslam93/ToolKit) ships independent "cores": a `core/` package with a
README and a `tests/` folder each, meant to be copied rather than installed. This script copies
the cores Murshid uses, exactly as committed (uncommitted edits in a ToolKit checkout are never
read: every file comes from `git archive` of the named commit).

What changes in the copy:
- Core files (`<name>/core/**`): nothing. They are byte-identical to the ToolKit commit. Cores
  import their sibling cores with relative imports (`from ...quote_matching.core import ...`),
  so they work unchanged under `murshid._toolkit`.
- Test files (`<name>/tests/**`): only the absolute imports and module-path strings, from
  `toolkit.` to `murshid._toolkit.`. The lift drills (`test_lift.py`) are dropped: they check the
  ToolKit's own repository layout, not behaviour.

The manifest (`src/murshid/_toolkit/manifest.json`) records, per file, the ToolKit path, the
sha256 at the ToolKit commit and the sha256 of the copy, so tests/test_vendored_toolkit.py can
prove that nobody edited a vendored file by hand. To change a core, change it in the ToolKit,
commit there, and run this script again with the new commit.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "src" / "murshid" / "_toolkit"


@dataclass(frozen=True)
class Core:
    project: str
    name: str
    catalog_id: str
    why: str


CORES: tuple[Core, ...] = (
    Core(
        "retrieval-rag",
        "quote_matching",
        "W03",
        "Arabic folding with a map back to the original text; quote alignment for citations",
    ),
    Core(
        "retrieval-rag",
        "lexical_retrieval",
        "C56",
        "BM25 tokenizer with Arabic folding and light stemming",
    ),
    Core(
        "retrieval-rag", "hybrid_retrieval", "W106", "fake, cached and OpenAI-compatible embedders"
    ),
    Core(
        "llm-agent-core",
        "number_text",
        "W09",
        "numbers, dates and codes in Arabic and English text, for figure grounding",
    ),
    Core("llm-agent-core", "versioned_prompts", "C59", "named, versioned, fingerprinted prompts"),
    Core(
        "llm-agent-core",
        "assistant_guidance",
        "W29",
        "greetings and 'what can you do' answered without a model call",
    ),
    Core(
        "security-hardening",
        "injection_sanitizer",
        "C39",
        "invisible-character removal and prompt-injection report mode",
    ),
    Core(
        "security-hardening",
        "pii_masking",
        "C37",
        "masking of IBANs, card and account numbers before egress and logs",
    ),
    Core(
        "security-hardening", "tamper_evident", "C29", "canonical JSON digests for bench run stamps"
    ),
    Core(
        "security-hardening",
        "fault_scripts",
        "C64",
        "real-client fault scripts and ablation checks (tests)",
    ),
    Core("llm-evals", "golden_tests", "C65", "golden-file, determinism and invariant tests"),
    Core(
        "fastapi-foundation",
        "fail_fast_settings",
        "C02",
        "settings that stop the app at start when a value is missing or out of range",
    ),
    Core(
        "delivery-tooling",
        "python_tooling",
        "C68",
        "check that the pyproject quality gates are not weakened",
    ),
    Core(
        "delivery-tooling",
        "ci_workflow",
        "C71",
        "check that the CI workflow is safe for a stranger's pull request",
    ),
    Core(
        "delivery-tooling",
        "container_image",
        "C69",
        "check that the Dockerfile keeps secrets out and runs as non-root",
    ),
)

_IMPORT = re.compile(r"\b(from|import)(\s+)toolkit\.")
_MODULE_STRING = re.compile(r"""(["'])toolkit\.""")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive(toolkit: Path, commit: str, paths: list[str]) -> tarfile.TarFile:
    tar = subprocess.run(
        ["git", "-C", str(toolkit), "archive", "--format=tar", commit, *paths],
        check=True,
        capture_output=True,
    ).stdout
    return tarfile.open(fileobj=io.BytesIO(tar))


def _rewrite_test(text: str) -> str:
    text = _IMPORT.sub(r"\1\2murshid._toolkit.", text)
    return _MODULE_STRING.sub(r"\1murshid._toolkit.", text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--toolkit", type=Path, required=True, help="path to a ToolKit git checkout"
    )
    parser.add_argument("--commit", required=True, help="ToolKit commit to copy from")
    args = parser.parse_args(argv)

    commit = subprocess.run(
        ["git", "-C", str(args.toolkit), "rev-parse", f"{args.commit}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    (DEST / "__init__.py").write_text(
        '"""ToolKit cores vendored at one commit. See README.md and manifest.json; do not edit."""\n',
        encoding="utf-8",
        newline="\n",
    )

    files: list[dict[str, str]] = []
    for core in CORES:
        prefix = f"{core.project}/toolkit/{core.name}/"
        archive = _archive(args.toolkit, commit, [prefix])
        (DEST / core.name).mkdir()
        (DEST / core.name / "__init__.py").write_text("", encoding="utf-8")
        for member in archive.getmembers():
            if not member.isfile():
                continue
            relative = member.name[len(prefix) :]
            if "__pycache__" in relative or relative.endswith("tests/test_lift.py"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"cannot read {member.name} from the ToolKit archive")
            original = extracted.read()
            data = original
            if relative.startswith("tests/") and relative.endswith(".py"):
                data = _rewrite_test(original.decode("utf-8")).encode("utf-8")
            target = DEST / core.name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files.append(
                {
                    "path": f"{core.name}/{relative}",
                    "toolkit_path": member.name,
                    "toolkit_sha256": _sha256(original),
                    "sha256": _sha256(data),
                }
            )

    manifest = {
        "toolkit_repository": "https://github.com/Eslam93/ToolKit",
        "toolkit_commit": commit,
        "cores": [
            {"name": c.name, "catalog_id": c.catalog_id, "project": c.project, "why": c.why}
            for c in CORES
        ],
        "files": files,
    }
    (DEST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    rows = "\n".join(f"| `{c.name}` | {c.catalog_id} | `{c.project}` | {c.why} |" for c in CORES)
    (DEST / "README.md").write_text(
        f"""# Vendored ToolKit cores

These folders are copied from [ToolKit](https://github.com/Eslam93/ToolKit) at commit
`{commit}` by `tools/vendor_toolkit.py`. Each core keeps its `core/` package (byte-identical to
the ToolKit commit) and its `tests/` (only `toolkit.` imports rewritten to `murshid._toolkit.`;
the ToolKit's layout drills `test_lift.py` are left out). `manifest.json` holds a sha256 for every
file, and `tests/test_vendored_toolkit.py` fails if a copy is edited by hand.

Do not edit these files. Change the core in the ToolKit, commit there, and re-run:

```bash
uv run python tools/vendor_toolkit.py --toolkit ../ToolKit --commit <new-commit>
```

| Folder | ToolKit ID | ToolKit project | Copied for |
|---|---|---|---|
{rows}

Murshid's own code imports four of them today: `fail_fast_settings` (src/murshid/settings.py),
and `hybrid_retrieval`, `python_tooling` and `ci_workflow` (tests only). The other eleven are
copied for planned work and nothing calls them yet; keep this paragraph in step when that
changes.

Each core's own README (`<name>/core/README.md`) documents its API, its limits and the
measurements it was released with.
""",
        encoding="utf-8",
        newline="\n",
    )
    print(f"vendored {len(CORES)} cores, {len(files)} files, from ToolKit {commit[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

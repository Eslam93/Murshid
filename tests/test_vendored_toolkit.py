"""The vendored ToolKit cores are exactly what tools/vendor_toolkit.py copied.

A core is changed in the ToolKit and re-vendored, never edited here: this test fails on any
vendored file whose bytes differ from the manifest, and on any file the manifest does not know.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

VENDORED = Path(__file__).resolve().parents[1] / "src" / "murshid" / "_toolkit"
MANIFEST = json.loads((VENDORED / "manifest.json").read_text(encoding="utf-8"))
# Written by the vendoring script itself, not copied from the ToolKit.
OWN_FILES = {"__init__.py", "README.md", "manifest.json"}


def _listed() -> dict[str, str]:
    return {entry["path"]: entry["sha256"] for entry in MANIFEST["files"]}


def _digest(path: Path) -> str:
    # .gitattributes keeps these files LF; a checkout that converted them to CRLF anyway is
    # not an edit, so line endings are normalised before hashing.
    crlf, lf = bytes([13, 10]), bytes([10])
    return hashlib.sha256(path.read_bytes().replace(crlf, lf)).hexdigest()


def test_every_vendored_file_matches_its_manifest_hash() -> None:
    changed = [path for path, digest in _listed().items() if _digest(VENDORED / path) != digest]
    assert changed == [], f"vendored files edited by hand (re-vendor instead): {changed}"


def test_no_unlisted_file_sits_among_the_vendored_cores() -> None:
    listed = set(_listed())
    names = {core["name"] for core in MANIFEST["cores"]}
    unlisted = sorted(
        relative
        for path in VENDORED.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
        for relative in [path.relative_to(VENDORED).as_posix()]
        if relative not in listed
        and relative not in OWN_FILES
        and relative not in {f"{name}/__init__.py" for name in names}
    )
    assert unlisted == [], (
        f"files in src/murshid/_toolkit that the manifest does not list: {unlisted}"
    )


def test_core_files_are_byte_identical_to_the_toolkit_commit() -> None:
    edited = [
        entry["path"]
        for entry in MANIFEST["files"]
        if "/core/" in f"/{entry['path']}" and entry["sha256"] != entry["toolkit_sha256"]
    ]
    assert edited == [], f"core files differ from the ToolKit commit: {edited}"

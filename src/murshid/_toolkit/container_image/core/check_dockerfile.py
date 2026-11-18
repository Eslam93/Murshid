"""A check that a Dockerfile builds a small, non-root image with no credential in its layers.

    python -m toolkit.container_image.core [Dockerfile]

Refuses: a single stage (build tools would ship in the image); a base image without a pinned tag,
or tagged latest; an ARG or ENV whose name says it is a secret (build arguments and environment
values are readable in the image's history); ADD from a URL; copying a .env file; a final stage
that runs as root or has no HEALTHCHECK. Exit 0 when clean, 1 with one line per finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

__all__ = ["SECRET_WORDS", "main", "problems"]

SECRET_WORDS = ("SECRET", "PASSWORD", "PASSWD", "TOKEN", "API_KEY", "PRIVATE_KEY", "CREDENTIAL")


def _instructions(text: str) -> list[tuple[int, str, str]]:
    """(line, keyword, rest) for each instruction, with continuation lines joined."""
    found: list[tuple[int, str, str]] = []
    buffer, start = "", 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not buffer and (not line or line.startswith("#")):
            continue
        if not buffer:
            start = number
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        buffer += line
        keyword, _, rest = buffer.partition(" ")
        found.append((start, keyword.upper(), rest.strip()))
        buffer = ""
    return found


def _resolve(image: str, args: dict[str, str]) -> str:
    return re.sub(r"\$\{?(\w+)\}?", lambda m: args.get(m.group(1), m.group(0)), image)


def problems(text: str) -> list[str]:
    instructions = _instructions(text)
    found: list[str] = []
    args: dict[str, str] = {}
    stages: list[list[tuple[int, str, str]]] = []
    stage_names: set[str] = set()
    for line, keyword, rest in instructions:
        if keyword == "ARG":
            name, _, default = rest.partition("=")
            args[name.strip()] = default.strip().strip('"')
        if keyword in ("ARG", "ENV"):
            name = re.split(r"[=\s]", rest, maxsplit=1)[0]
            if any(word in name.upper() for word in SECRET_WORDS):
                found.append(f"line {line}: {keyword} {name} would store a secret in the image")
        if keyword == "FROM":
            parts = rest.split()
            image = _resolve(parts[0], args)
            if " AS " in f" {rest.upper()} ":
                stage_names.add(parts[-1].lower())
            if image.lower() not in stage_names and image != "scratch":
                tag = image.rsplit("/", 1)[-1]
                if "@sha256:" not in image and (":" not in tag or tag.endswith(":latest")):
                    found.append(f"line {line}: base image {image} has no pinned tag")
            stages.append([])
        elif stages:
            stages[-1].append((line, keyword, rest))
        if keyword == "ADD" and re.search(r"https?://", rest):
            found.append(f"line {line}: ADD from a URL; download in a RUN with a checksum instead")
        if keyword in ("ADD", "COPY") and re.search(r"(^|\s|/)\.env(\s|$)", rest):
            found.append(f"line {line}: {keyword} copies a .env file into the image")
    if len(stages) < 2:
        found.append("a single stage: build tools would ship in the image")
    final = stages[-1] if stages else []
    users = [rest.split(":")[0] for _, keyword, rest in final if keyword == "USER"]
    if not users or users[-1] in ("root", "0"):
        found.append("the final stage runs as root: add USER with a non-root user")
    if not any(keyword == "HEALTHCHECK" for _, keyword, _ in final):
        found.append("the final stage has no HEALTHCHECK")
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0] if args else "Dockerfile")
    found = problems(path.read_text(encoding="utf-8"))
    for line in found:
        sys.stderr.write(f"{path}: {line}\n")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())

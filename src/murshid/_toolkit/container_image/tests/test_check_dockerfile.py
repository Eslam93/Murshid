"""The Dockerfile check on the template it ships and on Dockerfiles that break one rule each."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from murshid._toolkit.container_image.core import main, problems

TEMPLATE = (Path(__file__).resolve().parents[1] / "core" / "Dockerfile.template").read_text()


def test_the_template_is_clean() -> None:
    assert problems(TEMPLATE) == []


@pytest.mark.parametrize(
    ("change", "finding"),
    [
        (("USER app\n", "USER root\n"), "the final stage runs as root"),
        (("USER app\n", ""), "the final stage runs as root"),
        (("HEALTHCHECK", "# HEALTHCHECK"), "the final stage has no HEALTHCHECK"),
        (("python:3.12.11-slim AS runtime", "python AS runtime"), "has no pinned tag"),
        (("node:22-slim", "node:latest"), "has no pinned tag"),
        (
            ("WORKDIR /srv\nCOPY --from", "ARG DB_PASSWORD=x\nWORKDIR /srv\nCOPY --from"),
            "ARG DB_PASSWORD would store a secret",
        ),
        (("ENV PATH=", "ENV SESSION_SECRET=abc PATH="), "ENV SESSION_SECRET would store a secret"),
        (("COPY app app", "COPY .env .env\nCOPY app app"), "copies a .env file"),
        (
            ("COPY app app", "ADD https://example.test/tool.tgz /tmp/\nCOPY app app"),
            "ADD from a URL",
        ),
    ],
)
def test_each_broken_rule_is_named(change: tuple[str, str], finding: str) -> None:
    broken = TEMPLATE.replace(*change, 1)
    assert broken != TEMPLATE
    assert any(finding in line for line in problems(broken)), problems(broken)


def test_a_single_stage_is_refused() -> None:
    single = "FROM python:3.12-slim\nUSER app\nHEALTHCHECK CMD true\n"
    assert problems(single) == ["a single stage: build tools would ship in the image"]


def test_a_later_stage_may_start_from_an_earlier_one() -> None:
    text = (
        "FROM python:3.12-slim AS base\nRUN true\nFROM base AS runtime\n"
        "USER app\nHEALTHCHECK CMD true\n"
    )
    assert problems(text) == []


def test_the_command_line_names_the_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "Dockerfile"
    path.write_text("FROM python:latest\n")
    assert main([str(path)]) == 1
    assert "has no pinned tag" in capsys.readouterr().err


def test_runs_as_a_module_and_says_nothing_when_clean(tmp_path: Path) -> None:
    good, bad = tmp_path / "Dockerfile", tmp_path / "Dockerfile.bad"
    good.write_text(TEMPLATE)
    bad.write_text(TEMPLATE.replace("USER app\n", "", 1))
    root = Path(__file__).resolve().parents[3]  # the folder that holds toolkit/
    run = [sys.executable, "-W", "error", "-m", "murshid._toolkit.container_image.core"]
    clean = subprocess.run([*run, str(good)], cwd=root, capture_output=True, text=True, check=False)
    assert (clean.returncode, clean.stderr) == (0, "")
    broken = subprocess.run([*run, str(bad)], cwd=root, capture_output=True, text=True, check=False)
    assert broken.returncode == 1
    assert "runs as root" in broken.stderr

"""The bench runner on the provider registry and the settings.

Pins: providers built through the registry, with unknown and unavailable ones skipped and why;
the judge is `BENCH_JUDGE_MODEL`, the fallback and the sanity swap use
`BENCH_SANITY_SWAP_JUDGE_MODEL`; bad settings stop the bench naming the variable, never its
value; and a whole zero-key bench run (extractive provider, no judge, the fake embedder) with
every output redirected to a temporary folder, so the committed `bench/` files are never written.
No test here makes a call: a judge with a fake key is built and inspected, never run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from murshid.bench import runner
from murshid.providers.claude import ClaudeProvider
from murshid.providers.gemini import GeminiProvider
from murshid.providers.openai import OpenAIProvider
from murshid.settings import Settings, load_settings

ROOT = Path(__file__).resolve().parents[1]


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "murshid_data_dir": ROOT / "data",
        "murshid_replay_file": ROOT / "bench" / "case-cache.json",
    }
    values.update(overrides)
    return load_settings(Settings, _env_file=None, **values)


@pytest.fixture
def bench_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every file the bench writes, redirected under a temporary folder."""
    out = tmp_path / "bench"
    monkeypatch.setattr(runner, "BENCH_DIR", out)
    for name, file_name in [
        ("COST_LOG_PATH", "cost-log.jsonl"),
        ("REFUSAL_LOG_PATH", "refusal-log.jsonl"),
        ("RESULTS_MD_PATH", "results.md"),
        ("CASE_CACHE_PATH", "case-cache.json"),
    ]:
        monkeypatch.setattr(runner, name, out / file_name)
    return out


# ---------------------------------------------------------------------------
# Providers and judges
# ---------------------------------------------------------------------------


def test_the_bench_builds_providers_through_the_registry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    providers = runner.build_providers(
        ["mock", "extractive", "replay", "claude", "falcon-arabic"], _settings()
    )
    assert [p.name for p in providers] == ["mock", "extractive", "replay"]  # as requested
    out = capsys.readouterr().out
    assert "unknown provider 'falcon-arabic'" in out
    assert "ANTHROPIC_API_KEY" in out


def test_the_bench_skips_a_replay_provider_without_recordings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(murshid_replay_file=tmp_path / "missing.json")
    assert runner.build_providers(["replay"], settings) == []
    assert "MURSHID_REPLAY_FILE" in capsys.readouterr().out


def test_the_bench_judge_is_bench_judge_model() -> None:
    judge = runner.select_judge(
        _settings(gemini_api_key="test-fake", bench_judge_model="gemini-2.5-pro")
    )
    assert isinstance(judge, GeminiProvider)
    assert judge.model_id == "gemini-2.5-pro"
    other_vendor = runner.select_judge(
        _settings(openai_api_key="sk-test-fake", bench_judge_model="gpt-5.4-mini-2026-03-17")
    )
    assert isinstance(other_vendor, OpenAIProvider)


def test_without_the_judge_key_the_bench_falls_back_to_the_swap_judge_model() -> None:
    judge = runner.select_judge(
        _settings(
            anthropic_api_key="sk-ant-test-fake",
            bench_sanity_swap_judge_model="claude-haiku-4-5-20251001",
        )
    )
    assert isinstance(judge, ClaudeProvider)
    assert judge.model_id == "claude-haiku-4-5-20251001"
    assert runner.select_judge(_settings()) is None


def test_the_sanity_swap_uses_bench_sanity_swap_judge_model() -> None:
    default = runner.select_swap_judge(_settings(anthropic_api_key="sk-ant-test-fake"))
    assert isinstance(default, ClaudeProvider)
    assert default.model_id == "claude-opus-4-7"
    chosen = runner.select_swap_judge(
        _settings(openai_api_key="sk-test-fake", bench_sanity_swap_judge_model="gpt-4.1")
    )
    assert isinstance(chosen, OpenAIProvider)
    assert chosen.model_id == "gpt-4.1"
    assert runner.select_swap_judge(_settings()) is None


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_the_bench_stops_on_bad_settings_naming_the_variable_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BENCH_SANITY_SWAP_JUDGE_MODEL", "leaky-model-name-5f1a")
    assert runner.main(["--render-only"]) == 2
    out = capsys.readouterr().out
    assert "BENCH_SANITY_SWAP_JUDGE_MODEL" in out
    assert "leaky-model-name-5f1a" not in out


def test_the_bench_re_renders_the_committed_case_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--render-only` makes no call; written to a temporary file, never over bench/results.md."""
    results = tmp_path / "results.md"
    monkeypatch.setattr(runner, "RESULTS_MD_PATH", results)
    assert runner.main(["--render-only"]) == 0
    rendered = results.read_text(encoding="utf-8")
    assert rendered.startswith("# Murshid — bench results")
    assert "openai (gpt-5.5-2026-04-23)" in rendered
    assert "## Red-team — aggregate metrics" in rendered


def test_a_zero_key_bench_run_completes_and_writes_only_where_told(
    bench_out: Path,
    fake_embedder: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MURSHID_DATA_DIR", str(ROOT / "data"))
    status = runner.main(
        [
            "--providers",
            "extractive",
            "--critic",
            "off",
            "--question-ids",
            "q-001,q-014",
            "--red-team-ids",
            "rt-001",
        ]
    )
    assert status == 0
    out = capsys.readouterr().out
    assert "[bench] extractive: ready (model=extractive-1)" in out
    assert "no judge available" in out

    cases = {
        c["question_id"]: c for c in json.loads((bench_out / "case-cache.json").read_text("utf-8"))
    }
    assert set(cases) == {"q-001", "q-014", "rt-001"}
    assert cases["q-001"]["behavior_taken"] == "answer"
    assert cases["q-001"]["predicted_answer_text"].startswith("وفقاً للمصدر [1]: «")
    assert cases["q-014"]["behavior_taken"] == "refuse_with_redirect"
    assert cases["rt-001"]["behavior_taken"] == "refuse_with_redirect"  # the support gate
    assert all(c["cost_usd"] == 0.0 for c in cases.values())

    costs = [
        json.loads(line) for line in (bench_out / "cost-log.jsonl").read_text("utf-8").splitlines()
    ]
    assert {row["model_id"] for row in costs} == {"extractive-1"}
    assert (bench_out / "refusal-log.jsonl").is_file()
    assert "extractive (extractive-1)" in (bench_out / "results.md").read_text(encoding="utf-8")

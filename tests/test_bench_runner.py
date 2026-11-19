# SPDX-FileCopyrightText: 2026 Eslam Hamed
#
# SPDX-License-Identifier: MIT

"""The bench runner on the provider registry and the settings.

Pins: providers built through the registry, with unknown and unavailable ones skipped and why;
the judge is `BENCH_JUDGE_MODEL`, the fallback and the sanity swap use
`BENCH_SANITY_SWAP_JUDGE_MODEL`; bad settings stop the bench naming the variable, never its
value; and a whole zero-key bench run (extractive provider, no judge, the fake embedder) with
every output redirected to a temporary folder, so the committed `bench/` files are never written.
The manifest's commit and dirty flag are read before the run writes anything, and a spend cap
stops a paid run (a fake paid model, no network) and says so in the manifest and on the page.
No test here makes a call: a judge with a fake key is built and inspected, never run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from murshid.bench import runner
from murshid.bench.spend import MeteredProvider, SpendMeter
from murshid.providers.base import LLMProvider, ProviderResponse
from murshid.providers.claude import ClaudeProvider
from murshid.providers.extractive import ExtractiveProvider
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
    results = (bench_out / "results.md").read_text(encoding="utf-8")
    assert "extractive (extractive-1)" in results

    # No paid call: nothing to log, no spend line, and the manifest says so.
    assert not (bench_out / "spend-log.jsonl").exists()
    assert "Model spend" not in results
    manifest = json.loads((bench_out / "run-manifest.json").read_text("utf-8"))
    assert manifest["spend"] == {
        "spent_usd": 0.0,
        "cap_usd": None,
        "cap_reached": False,
        "paid_calls": 0,
        "cases_not_run": 0,
        "prices": [],
    }


# ---------------------------------------------------------------------------
# Splits, run folders and the run manifest
# ---------------------------------------------------------------------------


def test_a_heldout_run_scores_the_heldout_sets_into_its_own_folder(
    bench_out: Path, fake_embedder: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plumbing only: which files a held-out run reads and writes. No outcome is asserted."""
    monkeypatch.setenv("MURSHID_DATA_DIR", str(ROOT / "data"))
    status = runner.main(
        [
            "--split",
            "heldout",
            "--providers",
            "extractive",
            "--critic",
            "off",
            "--question-ids",
            "h-001",
            "--red-team-ids",
            "hr-001",
        ]
    )
    assert status == 0
    heldout = bench_out / "heldout"
    cases = json.loads((heldout / "case-cache.json").read_text("utf-8"))
    assert {c["question_id"] for c in cases} == {"h-001", "hr-001"}
    assert not (bench_out / "case-cache.json").exists(), "the tuned folder stays untouched"

    manifest = json.loads((heldout / "run-manifest.json").read_text("utf-8"))
    assert manifest["split"] == "heldout"
    assert manifest["providers"] == [{"name": "extractive", "model_id": "extractive-1"}]
    assert manifest["judge_model_id"] is None
    assert manifest["question_ids"] == ["h-001"]
    assert "git_commit" in manifest
    assert set(manifest["data_files"]) == {
        "data/sources.json",
        "data/heldout/questions.json",
        "data/heldout/gold_answers.json",
        "data/heldout/red_team.json",
    }
    for name, digest in manifest["data_files"].items():
        assert digest == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    assert "- Split: heldout" in (heldout / "results.md").read_text(encoding="utf-8")


def test_a_run_never_writes_into_a_folder_that_holds_the_other_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "run"
    out.mkdir()
    (out / "run-manifest.json").write_text(json.dumps({"split": "tuned"}), encoding="utf-8")
    status = runner.main(
        ["--split", "heldout", "--out-dir", str(out), "--providers", "extractive", "--overwrite"]
    )
    assert status == 2
    assert "must not be mixed" in capsys.readouterr().out
    assert [p.name for p in out.iterdir()] == ["run-manifest.json"]


def test_a_recorded_run_is_replaced_only_with_overwrite(
    tmp_path: Path,
    fake_embedder: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "run"
    out.mkdir()
    (out / "run-manifest.json").write_text(json.dumps({"split": "tuned"}), encoding="utf-8")
    monkeypatch.setenv("MURSHID_DATA_DIR", str(ROOT / "data"))
    args = [
        "--out-dir",
        str(out),
        "--providers",
        "extractive",
        "--critic",
        "off",
        "--question-ids",
        "q-001",
        "--red-team-ids",
        "rt-001",
    ]
    assert runner.main(args) == 2
    assert "--overwrite" in capsys.readouterr().out
    assert runner.main([*args, "--overwrite"]) == 0
    assert json.loads((out / "run-manifest.json").read_text("utf-8"))["question_ids"] == ["q-001"]


def test_render_only_takes_the_judge_the_date_and_the_swap_from_the_manifest(
    tmp_path: Path,
) -> None:
    out = tmp_path / "recorded"
    out.mkdir()
    for name in ("case-cache.json", "run-manifest.json"):
        (out / name).write_bytes((ROOT / "bench" / name).read_bytes())
    assert runner.main(["--render-only", "--out-dir", str(out)]) == 0
    page = (out / "results.md").read_text(encoding="utf-8")
    assert "Recorded: 2026-05-23T13:56:41" in page
    assert "- Judge: gemini-2.5-flash" in page
    assert "## Judge sanity swap" in page
    assert "| mock (mock-1) |" not in page, "mock rows stay out of the tables"
    assert "hallucinated" not in page
    assert "Wrong refusals" in page


def test_render_only_refuses_a_folder_of_the_other_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "recorded"
    out.mkdir()
    for name in ("case-cache.json", "run-manifest.json"):
        (out / name).write_bytes((ROOT / "bench" / name).read_bytes())
    assert runner.main(["--render-only", "--split", "heldout", "--out-dir", str(out)]) == 2
    assert "pass --split tuned" in capsys.readouterr().out
    assert not (out / "results.md").exists()


def test_the_manifest_records_the_git_state_from_before_the_run_wrote_anything(
    tmp_path: Path, fake_embedder: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run writes into tracked files, so a dirty flag read at the end would always be set."""
    out = tmp_path / "run"
    monkeypatch.setenv("MURSHID_DATA_DIR", str(ROOT / "data"))

    def fake_git(*args: str) -> str:
        if args[0] == "rev-parse":
            return "0" * 40
        # Once the run has written its outputs, the tree reads dirty.
        return " M bench/case-cache.json" if (out / "case-cache.json").exists() else ""

    monkeypatch.setattr(runner, "_git", fake_git)
    args = ["--out-dir", str(out), "--providers", "extractive", "--critic", "off"]
    assert runner.main([*args, "--question-ids", "q-001", "--red-team-ids", "rt-001"]) == 0
    manifest = json.loads((out / "run-manifest.json").read_text("utf-8"))
    assert (manifest["git_commit"], manifest["git_dirty"]) == ("0" * 40, False)


# ---------------------------------------------------------------------------
# Spend
# ---------------------------------------------------------------------------


class _FakePaidModel:
    """A paid-kind provider that answers anything for a fixed $0.03 a call, with no network."""

    name = "openai"
    model_id = "gpt-test-fake"

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def cost_estimate_usd(self, response: ProviderResponse) -> float:
        return 0.03

    def generate(
        self, system: str, user: str, max_tokens: int = 1024, timeout: float = 30.0
    ) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(
            text="وفقاً للمصدر [1]: هذه إجابة اختبار.",
            input_tokens=1000,
            output_tokens=100,
            latency_s=0.0,
        )


def test_only_paid_providers_go_behind_the_spend_meter() -> None:
    meter = SpendMeter(None)
    extractive = ExtractiveProvider()
    assert runner.metered(extractive, meter) is extractive
    assert isinstance(runner.metered(_FakePaidModel(), meter), MeteredProvider)


def test_a_spend_cap_stops_a_paid_run_and_the_run_says_so(
    tmp_path: Path,
    fake_embedder: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "run"
    model = _FakePaidModel()
    monkeypatch.setenv("MURSHID_DATA_DIR", str(ROOT / "data"))

    def fake_providers(names: list[str], settings: Settings) -> list[LLMProvider]:
        return [model]

    def no_judge(settings: Settings) -> None:
        return None

    monkeypatch.setattr(runner, "build_providers", fake_providers)
    monkeypatch.setattr(runner, "select_judge", no_judge)
    planned = ["q-001", "q-002", "q-003", "q-006", "q-007"]
    status = runner.main(
        [
            *("--out-dir", str(out), "--providers", "openai", "--critic", "off"),
            *("--mode", "standard", "--no-sanity-swap"),
            *("--question-ids", ",".join(planned), "--max-cost-usd", "0.05"),
        ]
    )
    assert status == 0
    assert "spend cap reached" in capsys.readouterr().out

    # $0.03 spent, and a second $0.03 call could pass $0.05: it never reached the model.
    assert model.calls == 1
    manifest = json.loads((out / "run-manifest.json").read_text("utf-8"))
    spend = manifest["spend"]
    assert spend["spent_usd"] == pytest.approx(0.03)
    assert (spend["cap_usd"], spend["cap_reached"], spend["paid_calls"]) == (0.05, True, 1)
    cases = json.loads((out / "case-cache.json").read_text("utf-8"))
    assert spend["cases_not_run"] >= 1
    assert len(cases) + spend["cases_not_run"] == len(planned)
    assert all(c["behavior_taken"] != "error" for c in cases), "a cut-short case is left out"
    assert spend["prices"] == [
        {
            "provider": "openai",
            "model_id": "gpt-test-fake",
            "input_usd_per_mtok": 5.0,
            "output_usd_per_mtok": 15.0,
            "as_of": "2026-05-23",
            "source": "unknown OpenAI model, priced as gpt-5.5",
        }
    ]
    rows = (out / "spend-log.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(row)["model_id"] for row in rows] == ["gpt-test-fake"]
    results = (out / "results.md").read_text(encoding="utf-8")
    assert "- Model spend: $0.0300 logged over 1 paid calls" in results
    assert f"The cap was reached: {spend['cases_not_run']} cases did not run" in results

    # The page says the same when it is rendered again from the recording.
    (out / "results.md").unlink()
    assert runner.main(["--render-only", "--out-dir", str(out)]) == 0
    assert "The cap was reached" in (out / "results.md").read_text(encoding="utf-8")


def test_a_spend_cap_must_be_positive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "run"
    assert runner.main(["--out-dir", str(out), "--max-cost-usd", "0"]) == 2
    assert "positive" in capsys.readouterr().out
    assert not out.exists()

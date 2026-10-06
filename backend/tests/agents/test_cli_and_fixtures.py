"""`crew agent try`, the job fixtures, settings loader and the `python -m crew.agents` entry point."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from crew.agents.__main__ import main as agents_main
from crew.agents.settings import DEFAULT_MODELS, nats_url_from_env, settings_from_env
from crew.contracts import AGENTS, AgentJob, AgentName, AgentResultEvt

REPO = Path(__file__).resolve().parents[3]
JOBS = REPO / "fixtures" / "jobs"
SCRIPT = REPO / "backend" / "scripts" / "make_job_fixtures.py"
SAMPLE = REPO / "fixtures" / "sample-repo"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_job_fixtures", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------------- fixtures/jobs
@pytest.mark.parametrize("agent", AGENTS)
def test_job_fixture_is_a_valid_job_for_its_agent(agent: AgentName) -> None:
    job = AgentJob.model_validate_json((JOBS / f"{agent}.json").read_text(encoding="utf-8"))
    assert job.agent == agent
    assert job.task_id == "T-107"
    assert job.workspace_path == "fixtures/sample-repo"
    assert (job.plan is not None) is (agent in ("developer", "tester", "reviewer"))
    assert job.repo.test_cmd == "python -m pytest -q"


def test_job_fixtures_match_their_generator() -> None:
    script = load_script()
    expected = {
        "interviewer": script.make_job(1, "interviewer", spec=script.VAGUE_SPEC),
        "planner": script.make_job(2, "planner"),
        "developer": script.make_job(3, "developer", plan=script.PLAN),
        "tester": script.make_job(4, "tester", plan=script.PLAN),
        "reviewer": script.make_job(5, "reviewer", plan=script.PLAN),
    }
    for agent, job in expected.items():
        on_disk = (JOBS / f"{agent}.json").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert on_disk == job.model_dump_json(indent=2) + "\n", f"re-run make_job_fixtures.py ({agent})"


# ---------------------------------------------------------------------------------- crew agent try
def run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "crew.cli", "agent", *args], cwd=REPO, capture_output=True, check=False
    )


@pytest.mark.parametrize("agent", AGENTS)
def test_try_runs_every_agent_in_fake_mode_without_nats(agent: AgentName) -> None:
    proc = run_cli("try", agent, "--job", str(JOBS / f"{agent}.json"), "--fake", "--speed", "1000")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    result = AgentResultEvt.model_validate_json(proc.stdout.decode("utf-8"))
    assert result.agent == agent
    assert result.job_id == AgentJob.model_validate_json((JOBS / f"{agent}.json").read_bytes()).job_id
    stderr = proc.stderr.decode("utf-8")
    assert "[tool] " in stderr
    assert "[workspace]" in stderr  # worked on a temporary git copy of the sample repo


def test_try_never_touches_the_committed_sample_repo() -> None:
    before = (SAMPLE / "shop" / "report.py").read_text(encoding="utf-8")
    proc = run_cli("try", "developer", "--job", str(JOBS / "developer.json"), "--fake", "--speed", "1000")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert (SAMPLE / "shop" / "report.py").read_text(encoding="utf-8") == before
    assert not (SAMPLE / ".git").exists()
    result = json.loads(proc.stdout.decode("utf-8"))
    assert [f["path"] for f in result["output"]["files_changed"]] == [
        "shop/report.py",
        "tests/test_report.py",
    ]


def test_try_with_an_explicit_workspace_edits_that_directory(tmp_path: Path) -> None:
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "report.py").write_text("x = 1\n", encoding="utf-8")
    proc = run_cli(
        "try", "developer", "--job", str(JOBS / "developer.json"), "--fake", "--speed", "1000",
        "--workspace", str(tmp_path),
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert "crew-fake" in (tmp_path / "shop" / "report.py").read_text(encoding="utf-8")


def test_try_escalate_makes_the_tester_fail() -> None:
    job = JOBS / "tester.json"
    proc = run_cli("try", "tester", "--job", str(job), "--fake", "--speed", "1000", "--escalate")
    assert proc.returncode == 0
    assert json.loads(proc.stdout.decode("utf-8"))["output"]["ok"] is False


def test_try_rejects_a_job_for_another_agent() -> None:
    proc = run_cli("try", "reviewer", "--job", str(JOBS / "planner.json"), "--fake")
    assert proc.returncode == 2
    assert "planner" in proc.stderr.decode("utf-8", "replace")


def test_try_rejects_unreadable_or_invalid_jobs(tmp_path: Path) -> None:
    assert run_cli("try", "planner", "--job", str(tmp_path / "missing.json"), "--fake").returncode == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"agent": "planner"}', encoding="utf-8")
    assert run_cli("try", "planner", "--job", str(bad), "--fake").returncode == 2


def test_try_rejects_unknown_agents() -> None:
    assert run_cli("try", "wizard", "--job", str(JOBS / "planner.json"), "--fake").returncode != 0


def test_try_reports_job_errors_with_exit_code_one(tmp_path: Path) -> None:
    job = json.loads((JOBS / "planner.json").read_text(encoding="utf-8"))
    job["workspace_path"] = None
    path = tmp_path / "no_ws.json"
    path.write_text(json.dumps(job), encoding="utf-8")
    proc = run_cli("try", "planner", "--job", str(path))  # real runner: fails fast, before any API call
    assert proc.returncode == 1
    assert "workspace_path" in proc.stderr.decode("utf-8", "replace")


def test_agent_list_still_works() -> None:
    proc = run_cli("list")
    assert proc.stdout.decode().split() == list(AGENTS)


# ---------------------------------------------------------------------------------- settings / main
def test_settings_defaults_follow_the_model_table() -> None:
    for agent in AGENTS:
        settings = settings_from_env(agent, {})
        assert settings.model == DEFAULT_MODELS[agent]
        assert (settings.fake, settings.fake_speed, settings.fake_escalate, settings.max_turns) == (
            False,
            1.0,
            False,
            None,
        )


def test_settings_read_the_environment() -> None:
    env = {
        "CREW_MODEL_PLANNER": "claude-opus-5-5-custom",
        "CREW_FAKE_AGENTS": "1",
        "CREW_FAKE_SPEED": "2.5",
        "CREW_FAKE_ESCALATE": "true",
        "CREW_MAX_TURNS": "9",
    }
    planner = settings_from_env("planner", env)
    assert planner.model == "claude-opus-5-5-custom"
    assert (planner.fake, planner.fake_speed, planner.fake_escalate, planner.max_turns) == (
        True,
        2.5,
        True,
        9,
    )
    assert settings_from_env("developer", env).model == DEFAULT_MODELS["developer"]
    assert settings_from_env("planner", {"CREW_FAKE_AGENTS": "0"}).fake is False
    assert settings_from_env("planner", {"CREW_MODEL_PLANNER": ""}).model == DEFAULT_MODELS["planner"]


def test_nats_url_default_and_override() -> None:
    assert nats_url_from_env({}) == "nats://127.0.0.1:4222"
    assert nats_url_from_env({"CREW_NATS_URL": "nats://example:1"}) == "nats://example:1"


@pytest.mark.parametrize("argv", [[], ["wizard"], ["planner", "extra"]])
def test_module_entry_point_rejects_bad_arguments(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert agents_main(argv) == 2
    assert "usage: python -m crew.agents" in capsys.readouterr().err

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from crew import doctor as d
from crew.cli import app
from crew.config import CrewConfig, RepoCfg, Secrets
from crew.workspace.manager import WorkspaceManager

from .git_helpers import make_git_repo

runner = CliRunner()
PY = f'"{sys.executable}"'


def write_toml(tmp_path: Path, repo: Path, *, test_cmd: str, nats: str = "nats://127.0.0.1:1") -> Path:
    toml = tmp_path / "crew.toml"
    toml.write_text(
        f"""
[nats]
url = "{nats}"

[workspace]
root = "{(tmp_path / "wt").as_posix()}"

[[repos]]
name = "sample-repo"
path = "{repo.as_posix()}"
base_branch = "main"
test_cmd = '{test_cmd}'
""",
        "utf-8",
    )
    return toml


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREW_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)


def by_name(checks: list[d.Check], prefix: str) -> d.Check:
    return next(c for c in checks if c.name.startswith(prefix))


# ================================================================================ doctor


async def test_doctor_reports_missing_config_with_a_fix(tmp_path: Path) -> None:
    checks = await d.run_checks(tmp_path / "nope.toml", run_tests=False)
    cfg = by_name(checks, "config")
    assert cfg.status == "fail" and "crew.toml.example" in cfg.hint
    assert d.exit_code(checks) == 1
    assert not any(c.name == "nats" for c in checks), "nothing else is checked without a config"


async def test_doctor_all_green_with_real_nats_and_repo(nats_url: str, tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "repos")
    toml = write_toml(tmp_path, repo, test_cmd=f"{PY} -c pass", nats=nats_url)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", "utf-8")
    checks = await d.run_checks(toml, run_tests=True, secrets=Secrets(_env_file=None), dist=dist)
    assert by_name(checks, "nats").status in ("ok", "warn")  # warn only if streams were never created
    assert by_name(checks, "config").status == "ok"
    assert by_name(checks, "repo:sample-repo").status == "ok"
    assert by_name(checks, "test_cmd:sample-repo").status == "ok"
    assert by_name(checks, "workspace").status == "ok"
    assert d.exit_code(checks) == 0


async def test_doctor_nats_down_tells_how_to_start_it(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "repos")
    toml = write_toml(tmp_path, repo, test_cmd=f"{PY} -c pass", nats="nats://127.0.0.1:1")
    checks = await d.run_checks(toml, run_tests=False)
    nats = by_name(checks, "nats")
    assert nats.status == "fail" and "inacessível" in nats.detail and "docker compose" in nats.hint
    assert d.exit_code(checks) == 1


async def test_doctor_repo_problems_are_specific(tmp_path: Path) -> None:
    cfg = CrewConfig(
        repos=[
            RepoCfg(name="missing", path=tmp_path / "nope", test_cmd="x"),
            RepoCfg(name="plain", path=tmp_path, test_cmd="x"),
            RepoCfg(name="nobranch", path=make_git_repo(tmp_path / "r"), base_branch="develop", test_cmd="x"),
        ]
    )
    missing = await d.check_repo(cfg, "missing", run_tests=False)
    plain = await d.check_repo(cfg, "plain", run_tests=False)
    nobranch = await d.check_repo(cfg, "nobranch", run_tests=False)
    assert "não existe" in missing[0].detail and missing[0].status == "fail"
    assert "não é um repositório git" in plain[0].detail
    assert "develop" in nobranch[0].detail and "base_branch" in nobranch[0].hint


async def test_doctor_test_cmd_outcomes(tmp_path: Path) -> None:
    passing = await d.check_test_cmd("r", f"{PY} -c pass", tmp_path)
    failing = await d.check_test_cmd("r", f"{PY} -c \"import sys; print('boom'); sys.exit(3)\"", tmp_path)
    assert passing.status == "ok"
    assert failing.status == "warn" and "código 3" in failing.detail and "boom" in failing.detail


async def test_doctor_claude_auth_warns_when_an_api_key_would_bill_the_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    check = await d.check_claude_auth(Secrets(_env_file=None))
    assert check.status == "warn" and "cobrar na API" in check.detail


async def test_doctor_claude_auth_reads_the_cli_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(d, "find_claude_cli", lambda: "claude.exe")

    def fake_run(payload: str) -> object:
        def run(*_a: object, **_k: object) -> object:
            return type("P", (), {"stdout": payload.encode(), "returncode": 0})()

        return run

    logged_in = '{"loggedIn": true, "authMethod": "claude.ai", "subscriptionType": "pro"}'
    monkeypatch.setattr(d.subprocess, "run", fake_run(logged_in))
    ok_check = await d.check_claude_auth(Secrets(_env_file=None))
    assert ok_check.status == "ok" and "pro" in ok_check.detail
    monkeypatch.setattr(d.subprocess, "run", fake_run('{"loggedIn": false}'))
    out = await d.check_claude_auth(Secrets(_env_file=None))
    assert out.status == "fail" and "claude auth login" in out.hint
    monkeypatch.setattr(d.subprocess, "run", fake_run("not json"))
    assert (await d.check_claude_auth(Secrets(_env_file=None))).status == "warn"


def test_render_includes_hints_only_when_not_ok() -> None:
    lines = d.render(
        [d.ok("a", "fine"), d.warn("b", "meh", "do x"), d.fail("c", "bad", "do y")], lambda t, _s: t
    )
    text = "\n".join(lines)
    assert "OK   a: fine" in text and "-> do x" in text and "-> do y" in text
    assert "1 problema(s) bloqueante(s), 1 aviso(s)" in text
    assert "->" not in lines[0]


def test_doctor_cli_exit_code_and_output(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "repos")
    toml = write_toml(tmp_path, repo, test_cmd=f"{PY} -c pass")  # nats unreachable -> blocking failure
    result = runner.invoke(app, ["doctor", "--config", str(toml), "--skip-tests"])
    assert result.exit_code == 1
    assert "FAIL" in result.output and "nats" in result.output and "docker compose" in result.output


def test_doctor_cli_without_config(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--config", str(tmp_path / "missing.toml"), "--skip-tests"])
    assert result.exit_code == 1 and "config" in result.output


# ================================================================================ cleanup


def test_cleanup_cli_removes_worktree_and_refuses_dirty(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "repos")
    toml = write_toml(tmp_path, repo, test_cmd="x")
    cfg = CrewConfig(
        workspace={"root": tmp_path / "wt"},  # type: ignore[arg-type]
        repos=[RepoCfg(name="sample-repo", path=repo, test_cmd="x")],
    )
    mgr = WorkspaceManager(cfg.workspace.root)
    ws = asyncio.run(mgr.create("T-9", cfg.repos[0]))
    (ws.path / "wip.py").write_text("x\n", "utf-8")

    dirty = runner.invoke(app, ["cleanup", "T-9", "--config", str(toml)])
    assert dirty.exit_code == 1 and "--force" in dirty.output and ws.path.exists()

    forced = runner.invoke(app, ["cleanup", "T-9", "--config", str(toml), "--force"])
    assert forced.exit_code == 0 and "removido" in forced.output and not ws.path.exists()

    again = runner.invoke(app, ["cleanup", "T-9", "--config", str(toml)])
    assert again.exit_code == 1 and "nenhum worktree" in again.output


def test_cleanup_cli_rejects_path_traversal(tmp_path: Path) -> None:
    toml = write_toml(tmp_path, make_git_repo(tmp_path / "repos"), test_cmd="x")
    result = runner.invoke(app, ["cleanup", "../../etc", "--config", str(toml)])
    assert result.exit_code == 1 and "nenhum worktree" in result.output


# ================================================================================ up / svc argument handling


def test_svc_rejects_unknown_service() -> None:
    result = runner.invoke(app, ["svc", "frontend"])
    assert result.exit_code == 2 and "serviço desconhecido" in result.output


def test_up_without_config_explains(tmp_path: Path) -> None:
    result = runner.invoke(app, ["up", "--fake-agents", "--config", str(tmp_path / "x.toml")])
    assert result.exit_code == 1 and "não existe" in result.output


def test_up_help_lists_the_fake_flags() -> None:
    out = runner.invoke(app, ["up", "--help"]).output
    for flag in ("--fake-agents", "--fake-speed", "--fake-escalate"):
        assert flag in out


async def test_doctor_docker_only_when_a_repo_uses_the_sandbox(tmp_path: Path) -> None:
    from crew.config import RepoCfg

    plain = CrewConfig(repos=[RepoCfg(name="a", path=tmp_path, test_cmd="x")])
    assert await d.check_docker(plain) is None
    boxed = CrewConfig(repos=[RepoCfg(name="a", path=tmp_path, test_cmd="x", sandbox_image="node:22")])
    check = await d.check_docker(boxed)
    assert check is not None and check.name == "docker"


async def test_doctor_frontend_needs_the_build(tmp_path: Path) -> None:
    missing = d.check_frontend_dist(tmp_path / "dist")
    assert missing.status == "fail" and "npm run build" in missing.hint
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("x", "utf-8")
    assert d.check_frontend_dist(tmp_path / "dist").status == "ok"
    assert d.check_frontend_dist(None).status == "ok", "gateway without UI is a deliberate choice"


def test_doctor_warns_per_repo_without_sandbox_image(tmp_path: Path) -> None:
    cfg = CrewConfig(
        repos=[
            RepoCfg(name="open", path=tmp_path, test_cmd="x"),
            RepoCfg(name="boxed", path=tmp_path, test_cmd="x", sandbox_image="node:22"),
        ]
    )
    checks = d.check_sandbox(cfg)
    assert [c.name for c in checks] == ["sandbox:open"]
    assert checks[0].status == "warn" and "sandbox_image" in checks[0].hint


def test_init_demo_creates_a_git_repo_and_prints_the_block(tmp_path: Path) -> None:
    dest = tmp_path / "demo"
    result = runner.invoke(app, ["init-demo", "--dest", str(dest)])
    assert result.exit_code == 0, result.output
    assert (dest / ".git").is_dir()
    assert "[[repos]]" in result.output and 'name = "demo"' in result.output
    assert "-m pytest -q" in result.output and dest.as_posix() in result.output
    again = runner.invoke(app, ["init-demo", "--dest", str(dest)])
    assert again.exit_code == 1, "refuses a non-empty destination"

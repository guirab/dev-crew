"""Sandbox (D41) and setup (D40): docker arguments, sandboxed tools/guards, host setup, real container."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from crew import sandbox
from crew.agents import runtool
from crew.agents.guards import check_tool, policy_for
from crew.agents.runner import build_options
from crew.agents.settings import AgentRuntimeSettings
from crew.agents.specs import SPECS
from crew.agents.submit import make_submit_tool
from crew.config import RepoCfg
from crew.workspace.manager import WorkspaceError, WorkspaceManager

from .agents.factories import POSIX_WS, make_job, make_repo
from .git_helpers import make_git_repo

PY = sys.executable

# ------------------------------------------------------------------ docker arguments


def layout(tmp: Path, *, worktree: bool = True) -> sandbox.GitLayout:
    common = tmp / "repo" / ".git"
    return sandbox.GitLayout(
        common_dir=common, git_dir=common / "worktrees" / "T-7" if worktree else common, autocrlf="true"
    )


def env_of(args: list[str]) -> dict[str, str]:
    pairs = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
    return dict(p.split("=", 1) for p in pairs)


def test_names_are_docker_safe_and_deterministic() -> None:
    assert sandbox.container_name("T-7", "Meu Repo") == "crew-meu-repo-t-7"
    assert sandbox.volume_name("T-7", "web", "frontend/node_modules") == "crew-web-t-7-frontend-node-modules"


def test_run_args_mount_worktree_rw_git_ro_and_deps_in_volumes(tmp_path: Path) -> None:
    ws = tmp_path / "wt" / "T-7"
    args = sandbox.run_args("T-7", "web", "node:22", ws, layout(tmp_path), ("frontend/node_modules",))
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "--mount"]
    assert f"type=bind,source={ws},target=/work" in mounts
    assert f"type=bind,source={tmp_path / 'repo' / '.git'},target=/repo.git,readonly" in mounts
    assert (
        "type=volume,source=crew-web-t-7-frontend-node-modules,target=/work/frontend/node_modules" in mounts
    )
    env = env_of(args)
    assert env["GIT_DIR"] == "/repo.git/worktrees/T-7" and env["GIT_WORK_TREE"] == "/work"
    assert env["GIT_CONFIG_KEY_0"] == "safe.directory" and env["GIT_CONFIG_VALUE_0"] == "*"
    assert env["GIT_CONFIG_KEY_1"] == "core.autocrlf" and env["GIT_CONFIG_VALUE_1"] == "true"
    assert args[args.index("--entrypoint") + 1 :] == ["sleep", "node:22", "infinity"]


def test_run_args_inplace_mode_points_git_dir_at_the_mount(tmp_path: Path) -> None:
    args = sandbox.run_args("T-7", "web", "img", tmp_path, layout(tmp_path, worktree=False), ())
    assert env_of(args)["GIT_DIR"] == "/repo.git"


def test_deps_dirs_must_be_relative() -> None:
    base: dict[str, Any] = {"name": "r", "path": ".", "test_cmd": "x"}
    assert RepoCfg(**base, deps_dirs=["frontend\\node_modules/"]).deps_dirs == ["frontend/node_modules"]
    for bad in ("/abs", "C:/x", "../up", ""):
        with pytest.raises(ValidationError):
            RepoCfg(**base, deps_dirs=[bad])


# ------------------------------------------------------------------ agents: tools and guards


def test_without_sandbox_the_agent_keeps_bash() -> None:
    job = make_job("tester", workspace=POSIX_WS)
    assert runtool.effective_tools(SPECS["tester"], job) == SPECS["tester"].tools


@pytest.mark.parametrize("agent", ["developer", "tester", "reviewer"])
def test_sandbox_swaps_bash_for_run_in_options(agent: str) -> None:
    spec = SPECS[agent]  # type: ignore[index]
    job = make_job(agent, workspace=POSIX_WS, repo=make_repo(sandbox=True))  # type: ignore[arg-type]
    submit = make_submit_tool(spec.output, spec.submit_name, check=spec.check)
    opts = build_options(spec, job, AgentRuntimeSettings(model="m"), POSIX_WS, submit, resumed=False)
    assert "Bash" not in opts.tools and "Bash" in opts.disallowed_tools
    assert runtool.RUN_FULL_NAME in opts.allowed_tools
    server: Any = opts.mcp_servers["crew"]  # type: ignore[index]
    assert server["type"] == "sdk"


def test_interviewer_without_bash_gets_no_run_tool() -> None:
    job = make_job("interviewer", workspace=POSIX_WS, repo=make_repo(sandbox=True))
    assert runtool.RUN_FULL_NAME not in runtool.effective_tools(SPECS["interviewer"], job)


def test_bash_guards_apply_to_the_run_tool() -> None:
    job = make_job("developer", workspace=POSIX_WS, repo=make_repo(sandbox=True))
    pol = policy_for(SPECS["developer"], job, POSIX_WS)
    assert check_tool(pol, runtool.RUN_FULL_NAME, {"command": "python -m pytest -q"}).allowed
    assert not check_tool(pol, runtool.RUN_FULL_NAME, {"command": "git commit -am x"}).allowed
    assert not check_tool(pol, runtool.RUN_FULL_NAME, {"command": "npm install left-pad"}).allowed
    assert not check_tool(pol, "Bash", {"command": "ls"}).allowed, "host Bash is gone in sandbox mode"


async def test_run_tool_reports_exit_code_and_output(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, float]] = []

    async def fake_exec(name: str, command: str, timeout_s: float) -> sandbox.ExecResult:
        calls.append((name, command, timeout_s))
        return sandbox.ExecResult(1, "1 failed")

    monkeypatch.setattr(sandbox, "exec_command", fake_exec)
    job = make_job("tester", workspace=POSIX_WS, repo=make_repo(sandbox=True))
    tool = runtool.make_run_tool(job)
    out = await tool.handler({"command": "pytest -q", "timeout_s": 99999})
    assert out["content"][0]["text"] == "exit code: 1\n1 failed"
    assert calls == [("crew-sample-repo-t-1", "pytest -q", runtool.MAX_TIMEOUT_S)]
    assert (await tool.handler({"command": " "})).get("is_error")


# ------------------------------------------------------------------ setup on the host (no sandbox)


async def test_host_setup_runs_in_the_worktree_and_failure_is_a_workspace_error(tmp_path: Path) -> None:
    repo_path = make_git_repo(tmp_path / "repos")
    manager = WorkspaceManager(tmp_path / "wt", fetch=False)
    ok_repo = RepoCfg(
        name="sample-repo", path=repo_path, test_cmd="x", setup_cmd=f"\"{PY}\" -c \"open('marker', 'w')\""
    )
    ws = await manager.create("T-1", ok_repo)
    await manager.prepare(ws, ok_repo)
    assert (ws.path / "marker").is_file()

    bad = ok_repo.model_copy(update={"setup_cmd": f'"{PY}" -c "import sys; print(\'boom\'); sys.exit(3)"'})
    with pytest.raises(WorkspaceError, match="setup falhou") as err:
        await manager.prepare(ws, bad)
    assert "código 3" in str(err.value) and "boom" in str(err.value)


async def test_without_setup_or_sandbox_prepare_is_a_no_op(tmp_path: Path) -> None:
    repo_path = make_git_repo(tmp_path / "repos")
    manager = WorkspaceManager(tmp_path / "wt", fetch=False)
    repo = RepoCfg(name="sample-repo", path=repo_path, test_cmd="x")
    ws = await manager.create("T-1", repo)
    await manager.prepare(ws, repo)


# ------------------------------------------------------------------ real container (opt-in)

DOCKER_IMAGE = os.environ.get("CREW_TEST_SANDBOX_IMAGE", "node:22")


@pytest.mark.docker
@pytest.mark.skipif(
    not os.environ.get("CREW_TEST_DOCKER") or shutil.which("docker") is None,
    reason="opt-in: CREW_TEST_DOCKER=1 (pulls an image, needs Docker Desktop)",
)
async def test_real_sandbox_isolates_the_worktree(tmp_path: Path) -> None:
    repo_path = make_git_repo(tmp_path / "repos")
    (repo_path / ".git" / "info").mkdir(exist_ok=True)
    (repo_path / ".git" / "info" / "exclude").write_text("deps/\n", "utf-8")  # like node_modules
    manager = WorkspaceManager(tmp_path / "wt", fetch=False)
    repo = RepoCfg(
        name="sbx",
        path=repo_path,
        test_cmd="x",
        sandbox_image=DOCKER_IMAGE,
        setup_cmd="mkdir -p deps && echo installed > deps/ok",
        deps_dirs=["deps"],
    )
    ws = await manager.create("T-1", repo)
    name = sandbox.container_name("T-1", "sbx")
    try:
        await manager.prepare(ws, repo)
        run = sandbox.exec_command
        assert (await run(name, "cat deps/ok", 30)).output.strip() == "installed"
        assert not (ws.path / "deps" / "ok").exists(), "deps live in the volume, not in the worktree"
        assert (await run(name, "git status --porcelain", 30)).output.strip() == "", "checkout is clean"
        (ws.path / "novo.txt").write_text("x", "utf-8")
        assert "novo.txt" in (await run(name, "git status --porcelain", 30)).output
        assert (await run(name, "git commit -qam x", 30)).exit_code != 0, ".git is read-only"
        host = await run(name, "test -e /c/Users -o -e /mnt/c && echo visible || echo hidden", 30)
        assert host.output.strip() == "hidden", "the rest of the machine is not mounted"
        offline = await run(name, "getent hosts registry.npmjs.org || echo offline", 30)
        assert "offline" in offline.output
        await manager.prepare(ws, repo)  # idempotent after a restart: setup is not re-run
    finally:
        await sandbox.remove("T-1", "sbx", ("deps",))

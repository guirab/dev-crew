"""Tool-level guards (Read/Glob/Grep/Write/Edit/Bash dispatch) and the PreToolUse hook itself."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from crew.agents import guards
from crew.agents.guards import GuardPolicy, check_tool, for_agent, policy_for
from crew.agents.specs import SPECS
from crew.agents.submit import full_tool_name

from .factories import DEFAULT_GLOBS, POSIX_WS, WINDOWS_WS, make_job, make_repo

FLAVORS = pytest.mark.parametrize("ws", [WINDOWS_WS, POSIX_WS], ids=["windows", "posix"])


def policy(agent: str, ws: str, globs: list[str] | None = None) -> GuardPolicy:
    job = make_job(agent, repo=make_repo(test_globs=globs or DEFAULT_GLOBS))  # type: ignore[arg-type]
    return policy_for(SPECS[agent], job, ws)  # type: ignore[index]


def allowed(pol: GuardPolicy, tool: str, **tool_input: Any) -> bool:
    return check_tool(pol, tool, tool_input).allowed


def join(ws: str, rel: str) -> str:
    sep = "\\" if "\\" in ws else "/"
    return ws + sep + rel.replace("/", sep)


# ---------------------------------------------------------------------------------- tool availability
def test_each_agent_gets_exactly_its_tools() -> None:
    expected = {
        "interviewer": {"Read", "Glob", "Grep"},
        "planner": {"Read", "Glob", "Grep", "Bash"},
        "developer": {"Read", "Glob", "Grep", "Write", "Edit", "Bash"},
        "tester": {"Read", "Glob", "Grep", "Write", "Edit", "Bash"},
        "reviewer": {"Read", "Glob", "Grep", "Bash"},
    }
    for agent, tools in expected.items():
        pol = policy(agent, POSIX_WS)
        submit = full_tool_name(SPECS[agent].submit_name)  # type: ignore[index]
        assert pol.tools == tools | {submit}, agent


@pytest.mark.parametrize("agent", ["interviewer", "planner", "reviewer"])
@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_read_only_agents_cannot_write(agent: str, tool: str) -> None:
    assert not allowed(policy(agent, POSIX_WS), tool, file_path="x.py", notebook_path="x.ipynb")


@pytest.mark.parametrize(
    "tool",
    ["WebFetch", "WebSearch", "Task", "Agent", "PowerShell", "Skill", "TodoWrite", "KillShell", "Whatever"],
)
@pytest.mark.parametrize("agent", ["interviewer", "planner", "developer", "tester", "reviewer"])
def test_unknown_and_network_tools_are_denied(agent: str, tool: str) -> None:
    pol = policy(agent, POSIX_WS)
    d = check_tool(pol, tool, {"url": "http://x", "prompt": "x"})
    assert not d.allowed
    assert tool in (d.reason or "")


def test_only_the_agents_own_submit_tool_is_allowed() -> None:
    pol = policy("planner", POSIX_WS)
    assert allowed(pol, "mcp__crew__submit_plan", summary="x")
    assert not allowed(pol, "mcp__crew__submit_review")
    assert not allowed(pol, "mcp__other__thing")
    assert not allowed(pol, "mcp__azure__wit_update_work_item")


# ---------------------------------------------------------------------------------- Write / Edit
@FLAVORS
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_developer_write_confinement(ws: str, tool: str) -> None:
    pol = policy("developer", ws)
    assert allowed(pol, tool, file_path="src/a.py")
    assert allowed(pol, tool, file_path=join(ws, "src/a.py"))
    assert allowed(pol, tool, file_path="./src/../src/a.py")
    assert allowed(pol, tool, file_path=join(ws, "tests/test_a.py"))
    assert not allowed(pol, tool, file_path="../x.py")
    assert not allowed(pol, tool, file_path="src/../../x.py")
    assert not allowed(pol, tool, file_path="/etc/passwd")
    assert not allowed(pol, tool, file_path="C:/Windows/x.txt")
    assert not allowed(pol, tool, file_path=ws + "-evil/x.py")
    assert not allowed(pol, tool, file_path="~/x.py")
    assert not allowed(pol, tool, file_path="$HOME/x.py")
    assert not allowed(pol, tool, file_path=".git/config")
    assert not allowed(pol, tool, file_path=join(ws, ".git/hooks/pre-commit"))
    assert not allowed(pol, tool, file_path="sub/.git/config")
    assert not allowed(pol, tool, file_path=".env")
    assert not allowed(pol, tool, file_path="config/.env.local")
    assert allowed(pol, tool, file_path=".env.example")
    assert allowed(pol, tool, file_path=".gitignore")
    assert allowed(pol, tool, file_path=".github/workflows/ci.yml")
    assert not allowed(pol, tool)  # no path
    assert not allowed(pol, tool, file_path="")
    assert not allowed(pol, tool, file_path=42)


def test_notebook_edit_checks_notebook_path() -> None:
    pol = GuardPolicy(workspace=POSIX_WS, tools=frozenset({"NotebookEdit"}), write="workspace")
    assert allowed(pol, "NotebookEdit", notebook_path="a.ipynb")
    assert not allowed(pol, "NotebookEdit", notebook_path="../a.ipynb")
    assert not allowed(pol, "NotebookEdit", file_path="a.ipynb")


@FLAVORS
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_tester_writes_only_test_files(ws: str, tool: str) -> None:
    pol = policy("tester", ws)
    for ok in ("tests/test_a.py", "tests/unit/test_b.py", "tests/conftest.py", "pkg/test_c.py"):
        assert allowed(pol, tool, file_path=ok), ok
        assert allowed(pol, tool, file_path=join(ws, ok)), ok
    for bad in ("src/a.py", "shop/report.py", "conftest.py", "pyproject.toml", "tests", "../tests/test_a.py"):
        assert not allowed(pol, tool, file_path=bad), bad


def test_tester_denial_tells_to_report_as_failure() -> None:
    d = check_tool(policy("tester", POSIX_WS), "Write", {"file_path": "src/a.py"})
    assert not d.allowed
    assert "failure" in (d.reason or "")


def test_tester_globs_are_configurable_per_repo() -> None:
    pol = policy("tester", POSIX_WS, globs=["spec/**", "**/*.spec.rb"])
    assert allowed(pol, "Write", file_path="spec/a_spec.rb")
    assert allowed(pol, "Write", file_path="lib/a.spec.rb")
    assert not allowed(pol, "Write", file_path="tests/test_a.py")


def test_write_case_insensitivity_follows_the_path_flavor() -> None:
    assert allowed(policy("tester", WINDOWS_WS), "Write", file_path="Tests/Test_A.py")
    assert not allowed(policy("tester", POSIX_WS), "Write", file_path="Tests/a.py")


# ---------------------------------------------------------------------------------- Read / Glob / Grep
@FLAVORS
def test_read_confinement(ws: str) -> None:
    for agent in ("interviewer", "planner", "developer", "tester", "reviewer"):
        pol = policy(agent, ws)
        assert allowed(pol, "Read", file_path="src/a.py")
        assert allowed(pol, "Read", file_path=join(ws, "README.md"))
        assert allowed(pol, "Read", file_path=".env.example")
        assert not allowed(pol, "Read", file_path="../x")
        assert not allowed(pol, "Read", file_path="/etc/passwd")
        assert not allowed(pol, "Read", file_path="~/.ssh/id_rsa")
        assert not allowed(pol, "Read", file_path=".env")
        assert not allowed(pol, "Read", file_path=join(ws, "config/.env.production"))
        assert not allowed(pol, "Read", file_path="certs/server.pem")
        assert not allowed(pol, "Read", file_path=".ssh/config")
        assert not allowed(pol, "Read")


@FLAVORS
def test_glob_and_grep_scopes(ws: str) -> None:
    pol = policy("planner", ws)
    assert allowed(pol, "Glob", pattern="**/*.py")
    assert allowed(pol, "Glob", pattern="src/**/*.ts", path="web")
    assert not allowed(pol, "Glob", pattern="../**/*.py")
    assert not allowed(pol, "Glob", pattern="/etc/*")
    assert not allowed(pol, "Glob", pattern="*.py", path="/etc")
    assert not allowed(pol, "Glob", pattern="*.py", path="..")
    assert allowed(pol, "Grep", pattern="def foo", path="src", glob="*.py")
    assert allowed(pol, "Grep", pattern="../not/a/path/but/regex")  # content pattern, not a path
    assert not allowed(pol, "Grep", pattern="x", path="/etc")
    assert not allowed(pol, "Grep", pattern="x", glob="../../*")
    assert not allowed(pol, "Grep", pattern="x", path=".ssh")


def test_bash_cannot_disable_the_sandbox_flag() -> None:
    pol = policy("developer", POSIX_WS)
    assert allowed(pol, "Bash", command="ls")
    assert not allowed(pol, "Bash", command="ls", dangerouslyDisableSandbox=True)


def test_bash_without_a_usable_command_is_denied() -> None:
    pol = policy("developer", POSIX_WS)
    assert not allowed(pol, "Bash")
    assert not allowed(pol, "Bash", command="")
    assert not allowed(pol, "Bash", command=5)


def _link_outside(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    out = tmp_path / "out"
    ws.mkdir()
    out.mkdir()
    (out / "secret.txt").write_text("x", encoding="utf-8")
    try:
        os.symlink(out, ws / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("symlinks not permitted on this host")
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(ws / "link"), str(out)], capture_output=True, check=False
        )
        if made.returncode != 0:
            pytest.skip("neither symlinks nor junctions available")
    return ws


def test_links_leaving_the_worktree_are_caught_everywhere(tmp_path: Path) -> None:
    ws = str(_link_outside(tmp_path))
    reviewer, developer = policy("reviewer", ws), policy("developer", ws)
    assert not allowed(reviewer, "Read", file_path="link/secret.txt")
    assert not allowed(developer, "Write", file_path="link/new.txt")
    assert not allowed(reviewer, "Bash", command="cat link/secret.txt")
    assert not allowed(developer, "Bash", command="echo x > link/new.txt")
    assert allowed(reviewer, "Read", file_path="normal.txt")


# ---------------------------------------------------------------------------------- the hook
def hook_for(agent: str, ws: str = POSIX_WS, on_block: Any = None) -> Any:
    spec = SPECS[agent]  # type: ignore[index]
    hooks = for_agent(spec, make_job(agent), ws, on_block)
    assert list(hooks) == ["PreToolUse"]
    (matcher,) = hooks["PreToolUse"]
    assert matcher.matcher is None  # every tool goes through the guard
    (fn,) = matcher.hooks
    return fn


def event(name: object, tool_input: object) -> dict[str, Any]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "transcript_path": "t",
        "cwd": POSIX_WS,
        "tool_name": name,
        "tool_input": tool_input,
        "tool_use_id": "tu_1",
    }


async def test_hook_allows_with_empty_output() -> None:
    hook = hook_for("developer")
    assert await hook(event("Bash", {"command": "pytest -q"}), "tu_1", {"signal": None}) == {}
    assert await hook(event("Read", {"file_path": "src/a.py"}), "tu_1", {"signal": None}) == {}


async def test_hook_denies_with_the_documented_output_shape() -> None:
    hook = hook_for("developer")
    out = await hook(event("Bash", {"command": "git commit -m x"}), "tu_1", {"signal": None})
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": out["hookSpecificOutput"]["permissionDecisionReason"],
        }
    }
    assert "git" in out["hookSpecificOutput"]["permissionDecisionReason"]


async def test_hook_reports_every_block() -> None:
    blocked: list[str] = []

    async def on_block(reason: str) -> None:
        blocked.append(reason)

    hook = hook_for("developer", on_block=on_block)
    await hook(event("Bash", {"command": "ls"}), "1", {"signal": None})
    await hook(event("Bash", {"command": "curl x"}), "2", {"signal": None})
    await hook(event("Write", {"file_path": "../x"}), "3", {"signal": None})
    assert len(blocked) == 2
    assert "rede" in blocked[0]
    assert "worktree" in blocked[1]


@pytest.mark.parametrize(
    ("name", "tool_input"),
    [(None, {}), (5, {}), ("Bash", None), ("Bash", "ls"), ("Bash", ["ls"])],
)
async def test_hook_denies_malformed_calls(name: object, tool_input: object) -> None:
    out = await hook_for("developer")(event(name, tool_input), "1", {"signal": None})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


async def test_hook_fails_closed_when_the_guard_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(guards, "check_tool", boom)
    out = await hook_for("developer")(event("Bash", {"command": "ls"}), "1", {"signal": None})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "erro interno" in out["hookSpecificOutput"]["permissionDecisionReason"]


async def test_hook_denies_the_reviewer_every_write() -> None:
    hook = hook_for("reviewer")
    for tool, tool_input in [
        ("Write", {"file_path": "x.py"}),
        ("Edit", {"file_path": "x.py"}),
        ("Bash", {"command": "echo x > y"}),
        ("Bash", {"command": "git commit -m x"}),
        ("WebFetch", {"url": "http://x"}),
    ]:
        out = await hook(event(tool, tool_input), "1", {"signal": None})
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", tool

"""Deterministic Tester verdict (D70): the suite's exit code overrides an ``ok`` from the agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew.agents import testgate
from crew.contracts import TestFailure, TestResult
from crew.gitbash import find_git_bash

from .factories import make_job, make_repo

pytestmark = pytest.mark.skipif(find_git_bash() is None, reason="precisa de bash")

GREEN = TestResult(ok=True, passed=3, total=3, command="pytest")


def job(tmp_path: Path, test_cmd: str, lint_cmd: str | None = None):  # type: ignore[no-untyped-def]
    return make_job("tester", workspace=tmp_path, repo=make_repo(test_cmd=test_cmd, lint_cmd=lint_cmd))


async def test_green_suite_keeps_the_agent_verdict(tmp_path: Path) -> None:
    assert await testgate.enforce(GREEN, job(tmp_path, "true", "true")) == GREEN


async def test_red_suite_turns_ok_into_a_failure_with_the_output_tail(tmp_path: Path) -> None:
    out = await testgate.enforce(GREEN, job(tmp_path, "echo boom; exit 3", "true"))
    assert not out.ok
    [failure] = out.failures
    assert failure.test == "[dev-crew] testes: `echo boom; exit 3`"
    assert failure.message.startswith("exit code 3\n") and "boom" in failure.message
    assert out.passed == 3  # the agent's counts stay, only the verdict changes


async def test_red_lint_fails_too(tmp_path: Path) -> None:
    out = await testgate.enforce(GREEN, job(tmp_path, "true", "exit 1"))
    assert [f.test for f in out.failures] == ["[dev-crew] lint: `exit 1`"]


async def test_long_output_is_cut_to_the_contract_limit(tmp_path: Path) -> None:
    out = await testgate.enforce(GREEN, job(tmp_path, "seq 1 5000; exit 1"))
    assert len(out.failures[0].message) <= testgate.MESSAGE_MAX
    assert out.failures[0].message.endswith("5000")


async def test_commands_run_in_the_worktree(tmp_path: Path) -> None:
    (tmp_path / "marker.txt").write_text("x", "utf-8")
    assert (await testgate.enforce(GREEN, job(tmp_path, "test -f marker.txt"))).ok


async def test_agent_failures_are_kept_without_rerunning(tmp_path: Path) -> None:
    red = TestResult(
        ok=False, passed=0, total=1, command="pytest", failures=[TestFailure(test="t", message="m")]
    )
    (tmp_path / "ran").unlink(missing_ok=True)
    assert await testgate.enforce(red, job(tmp_path, "touch ran")) == red
    assert not (tmp_path / "ran").exists()

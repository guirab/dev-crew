"""Deterministic Tester verdict (D70): the suite's exit code, not the agent's word, says the slice is green.

After a Tester job the worker reruns the repo's ``test_cmd`` and ``lint_cmd`` itself: in the task's
container when the repo has a sandbox, else on the host through Git Bash. ``ok`` stays true only if the
agent said ok **and** both commands exit 0. When the agent already reported failures its result is kept:
it may have found something the suite does not catch.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import structlog

from .. import sandbox
from ..contracts import AgentJob, TestFailure, TestResult
from ..gitbash import find_git_bash

log = structlog.get_logger(__name__)

TIMEOUT_S = 1800
MESSAGE_MAX = 400  # TestFailure.message limit


async def _run(job: AgentJob, command: str) -> sandbox.ExecResult:
    if job.repo.sandbox:
        name = sandbox.container_name(sandbox.workspace_key(job.task_id, job.epic_id), job.repo.name)
        return await sandbox.exec_command(name, command, TIMEOUT_S)
    bash = find_git_bash()
    if bash is None:
        raise sandbox.SandboxError("bash não encontrado para conferir os testes")

    def run() -> sandbox.ExecResult:
        assert job.workspace_path is not None
        try:
            res = subprocess.run(
                [bash, "-lc", f"{command} 2>&1"],
                cwd=Path(job.workspace_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return sandbox.ExecResult(124, f"[dev-crew] comando interrompido após {TIMEOUT_S}s")
        return sandbox.ExecResult(res.returncode, res.stdout + res.stderr)

    return await asyncio.to_thread(run)


def _failure(label: str, command: str, res: sandbox.ExecResult) -> TestFailure:
    head = f"exit code {res.exit_code}\n"
    output = res.output.strip()  # the end of the output is where the errors are
    return TestFailure(
        test=f"[dev-crew] {label}: `{command}`", message=head + output[-(MESSAGE_MAX - len(head)) :]
    )


async def red_commands(job: AgentJob) -> list[TestFailure]:
    """One failure per repo command (tests, then lint) that does not exit 0."""
    failures: list[TestFailure] = []
    for label, command in (("testes", job.repo.test_cmd), ("lint", job.repo.lint_cmd)):
        if not command:
            continue
        res = await _run(job, command)
        if res.exit_code != 0:
            failures.append(_failure(label, command, res))
    return failures


async def enforce(result: TestResult, job: AgentJob) -> TestResult:
    """``result`` with ``ok`` downgraded when the agent said ok but the suite or the lint is red."""
    if not result.ok or not job.workspace_path:
        return result
    try:
        failures = await red_commands(job)
    except sandbox.SandboxError as e:
        failures = [TestFailure(test="[dev-crew] conferência dos testes", message=str(e)[:MESSAGE_MAX])]
    if not failures:
        return result
    log.warning("tester_verdict_overridden", task=job.task_id, epic=job.epic_id, failures=len(failures))
    return result.model_copy(update={"ok": False, "failures": failures})

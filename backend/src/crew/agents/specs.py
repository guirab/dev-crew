"""Static description of each agent: tools, limits, output model and result post-processing."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from ..contracts import (
    AgentJob,
    AgentName,
    DevResult,
    InterviewResult,
    Plan,
    ReviewResult,
    TestResult,
)

BashMode = Literal["none", "readonly", "full"]
"""``none``: no Bash. ``readonly``: allowlisted read-only commands. ``full``: denylist policy."""

WriteMode = Literal["none", "workspace", "tests_only"]

PermissionMode = Literal["default", "acceptEdits"]

DEFAULT_TEST_GLOBS: tuple[str, ...] = (
    "tests/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/*.test.{ts,tsx,js,jsx}",
    "**/*.spec.{ts,tsx,js,jsx}",
    "**/__tests__/**",
)

# Tools that must never reach the model, even if a future default turns them on.
DISALLOWED_TOOLS: tuple[str, ...] = ("WebFetch", "WebSearch", "Agent", "Task", "PowerShell", "Skill")

_COMMIT_SUBJECT = re.compile(
    r"^(feat|fix|refactor|perf|test|docs|chore|build|ci|style|revert)(\([\w./-]+\))?!?: \S.*$"
)
COMMIT_SUBJECT_MAX = 72


@dataclass(frozen=True)
class AgentSpec[OutT: BaseModel]:
    name: AgentName
    output: type[OutT]
    submit_name: str
    tools: tuple[str, ...]
    bash: BashMode
    write: WriteMode
    max_turns: int
    budget_cap_usd: float
    resume_across_rounds: bool
    permission_mode: PermissionMode
    default_model: str
    check: Callable[[OutT], str | None] | None = None
    finalize: Callable[[OutT, AgentJob], OutT] | None = None

    @property
    def writes_files(self) -> bool:
        return self.write != "none"


# ---------------- semantic checks (run after Pydantic validation) ----------------
def check_interview(r: InterviewResult) -> str | None:
    if r.kind == "question":
        if not r.questions:
            return "kind='question' exige ao menos uma pergunta em questions (a fronteira inteira)."
        if r.spec is not None:
            return "kind='question' não deve trazer spec."
        topics = [q.topic for q in r.questions]
        if len(set(topics)) != len(topics):
            return "cada pergunta da rodada precisa de um topic diferente."
        for q in r.questions:
            if q.options and q.recommendation not in q.options:
                return f"[{q.topic}] a recommendation precisa ser uma das options."
    else:
        if r.spec is None:
            return "kind='done' exige a spec consolidada."
        if r.questions:
            return "kind='done' não deve trazer questions."
    return None


def check_plan(r: Plan) -> str | None:
    if not r.steps:
        return "steps não pode ser vazio."
    if not r.acceptance_criteria:
        return "acceptance_criteria não pode ser vazio."
    return None


def check_dev(r: DevResult) -> str | None:
    return None if r.summary.strip() else "summary não pode ser vazio."


def check_test(r: TestResult) -> str | None:
    if r.passed > r.total:
        return "passed não pode ser maior que total."
    if r.ok and r.failures:
        return "ok=true não combina com failures não vazio."
    if not r.ok and not r.failures:
        return "ok=false exige ao menos uma failure (nome do teste + mensagem curta)."
    return None


def check_review(r: ReviewResult) -> str | None:
    # a major that was fixed in a later round stays in the list as ``resolved`` and no longer blocks
    has_major = any(c.severity == "major" and not c.resolved for c in r.comments)
    if r.verdict == "approved":
        if has_major:
            return "há comentário major não resolvido: o verdict deve ser changes_requested."
        if not r.commit_message or not r.commit_message.strip():
            return "verdict=approved exige commit_message."
        subject = r.commit_message.strip().splitlines()[0]
        if len(subject) > COMMIT_SUBJECT_MAX:
            return f"assunto do commit com {len(subject)} caracteres (máximo {COMMIT_SUBJECT_MAX})."
        if not _COMMIT_SUBJECT.match(subject):
            return "assunto do commit fora do padrão Conventional Commits (ex.: 'feat(relatorio): ...')."
    elif not has_major:
        return "changes_requested exige ao menos um comentário major; sem major o verdict é approved."
    return None


# ---------------- finalizers (deterministic fixes the agent should not have to get right) ----------------
def finalize_interview(r: InterviewResult, job: AgentJob) -> InterviewResult:
    if r.spec is None:
        return r
    # identity fields come from the job, never from the model
    spec = r.spec.model_copy(update={"repo": job.spec.repo})
    return r.model_copy(update={"spec": spec})


def finalize_dev(r: DevResult, job: AgentJob) -> DevResult:
    return r.model_copy(update={"round": job.attempt})


def finalize_test(r: TestResult, job: AgentJob) -> TestResult:
    return r if r.command.strip() else r.model_copy(update={"command": job.repo.test_cmd})


_READ = ("Read", "Glob", "Grep")

SPECS: dict[AgentName, AgentSpec[Any]] = {
    "interviewer": AgentSpec(
        name="interviewer",
        output=InterviewResult,
        submit_name="submit_interview",
        tools=_READ,
        bash="none",
        write="none",
        max_turns=15,
        budget_cap_usd=0.5,
        resume_across_rounds=True,
        permission_mode="default",
        default_model="claude-sonnet-5-5",
        check=check_interview,
        finalize=finalize_interview,
    ),
    "planner": AgentSpec(
        name="planner",
        output=Plan,
        submit_name="submit_plan",
        tools=(*_READ, "Bash"),
        bash="readonly",
        write="none",
        max_turns=30,
        budget_cap_usd=2.0,
        resume_across_rounds=True,
        permission_mode="default",
        default_model="claude-opus-5-5",
        check=check_plan,
    ),
    "developer": AgentSpec(
        name="developer",
        output=DevResult,
        submit_name="submit_dev_result",
        tools=(*_READ, "Write", "Edit", "Bash"),
        bash="full",
        write="workspace",
        max_turns=60,
        budget_cap_usd=3.0,
        resume_across_rounds=True,
        permission_mode="acceptEdits",
        default_model="claude-sonnet-5-5",
        check=check_dev,
        finalize=finalize_dev,
    ),
    "tester": AgentSpec(
        name="tester",
        output=TestResult,
        submit_name="submit_test_result",
        tools=(*_READ, "Write", "Edit", "Bash"),
        bash="full",
        write="tests_only",
        max_turns=40,
        budget_cap_usd=1.5,
        resume_across_rounds=True,
        permission_mode="acceptEdits",
        default_model="claude-sonnet-5-5",
        check=check_test,
        finalize=finalize_test,
    ),
    "reviewer": AgentSpec(
        name="reviewer",
        output=ReviewResult,
        submit_name="submit_review",
        tools=(*_READ, "Bash"),
        bash="readonly",
        write="none",
        max_turns=30,
        budget_cap_usd=2.0,
        resume_across_rounds=True,
        permission_mode="default",
        default_model="claude-opus-5-5",
        check=check_review,
    ),
}


def effective_test_globs(job: AgentJob) -> tuple[str, ...]:
    """Per-repo globs from ``crew.toml`` (via the job), else the defaults."""
    return tuple(job.repo.test_globs) or DEFAULT_TEST_GLOBS

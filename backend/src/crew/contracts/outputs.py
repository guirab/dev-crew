"""Structured outputs produced by each agent (captured via submit_* tools).

Every output carries a ``type`` literal so ``AgentOutput`` is a discriminated union.
"""

from typing import Annotated, Literal

from pydantic import Field

from .common import Contract, FileChange
from .task import TaskSpec


class InterviewQuestion(Contract):
    topic: str
    question: str
    recommendation: str
    options: list[str] = []  # selectable answers; the recommendation is one of them when present
    rationale: str | None = None


class InterviewTurn(Contract):
    question: InterviewQuestion
    answer: str
    accepted_recommendation: bool
    round: int = 1


class InterviewResult(Contract):
    """One round of the interview: the whole decision frontier at once, or the closed spec."""

    type: Literal["interview"] = "interview"
    kind: Literal["question", "done"]
    questions: list[InterviewQuestion] = []
    spec: TaskSpec | None = None


class PlanFile(Contract):
    path: str
    change: FileChange


class Plan(Contract):
    type: Literal["plan"] = "plan"
    summary: str
    steps: list[str]
    files: list[PlanFile]
    acceptance_criteria: list[str]
    risks: list[str] = []
    test_strategy: str


class DevResult(Contract):
    type: Literal["dev"] = "dev"
    round: int
    summary: str
    files_changed: list[PlanFile]
    notes: str | None = None


class TestFailure(Contract):
    __test__ = False  # not a pytest class

    test: str
    message: str = Field(max_length=400)


class TestResult(Contract):
    __test__ = False  # not a pytest class

    type: Literal["test"] = "test"
    ok: bool
    passed: int
    total: int
    failures: list[TestFailure] = []
    coverage: float | None = Field(default=None, ge=0, le=1, description="fração 0..1 (0.87 = 87%)")
    command: str
    tests_written: list[str] = []


class ReviewComment(Contract):
    severity: Literal["major", "minor", "nit"]
    file: str
    line: int | None = None
    text: str
    resolved: bool = False


class ReviewResult(Contract):
    type: Literal["review"] = "review"
    verdict: Literal["approved", "changes_requested"]
    comments: list[ReviewComment] = []
    commit_message: str | None = None


AgentOutput = Annotated[
    InterviewResult | Plan | DevResult | TestResult | ReviewResult,
    Field(discriminator="type"),
]

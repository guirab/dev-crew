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


EpicSize = Literal["S", "M", "L"]


class Epic(Contract):
    """A vertical slice of a split plan (D53): delivers and is tested on its own, in its own worktree.

    Epics without a dependency path between them run in parallel, so they must not share files.
    """

    id: str = Field(pattern=r"^E\d+$")  # E0 = foundation of a new project, then E1, E2...
    title: str
    goal: str
    steps: list[str]
    files: list[PlanFile]
    depends_on: list[str] = []
    acceptance_criteria: list[str]
    size: EpicSize = "M"


class ProjectSetup(Contract):
    """Commands of a brand-new project, decided by the Planner (D58) and saved to the repo registry."""

    stack: str
    setup_cmd: str | None = None
    test_cmd: str
    lint_cmd: str | None = None
    sandbox_image: str | None = None
    deps_dirs: list[str] = []


class Plan(Contract):
    type: Literal["plan"] = "plan"
    summary: str
    steps: list[str]
    files: list[PlanFile]
    acceptance_criteria: list[str]
    risks: list[str] = []
    test_strategy: str
    execution: Literal["single", "epics"] = "single"
    split_rationale: str = ""  # why one execution or why these epics: shown to the user before approval
    epics: list[Epic] = []
    project_setup: ProjectSetup | None = None
    # libraries the work adds ("name: why"): approving the plan lets dev-crew install them
    new_dependencies: list[str] = []
    essential_code: str | None = None  # code example only when essential (API contract, critical signature)


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


class StandardsResult(Contract):
    """The project standards base (D82): written by the agent, or found already in the vault.

    The agent always submits ``created``; the orchestrator builds ``existing`` itself, without a job.
    A new project (D58) has no result: its stage is ``skipped``.
    """

    type: Literal["standards"] = "standards"
    status: Literal["created", "existing"] = "created"
    summary: str  # pt-BR, 1-2 sentences; for ``existing``: "Usando a base existente (<caminho>)"
    files: list[str] = []  # paths relative to the ``standards/`` folder
    decisions: list[str] = []  # questions the skill would ask the user, answered by dev-crew with evidence
    notes: str | None = None


AgentOutput = Annotated[
    InterviewResult | StandardsResult | Plan | DevResult | TestResult | ReviewResult,
    Field(discriminator="type"),
]

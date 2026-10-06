"""TaskView: the snapshot the orchestrator publishes and the UI renders verbatim."""

from typing import Literal

from pydantic import AwareDatetime

from .common import Contract, EdgeKey, EdgeStatus, FileChange, StageStatus, TaskPhase
from .estimate import Estimate
from .outputs import DevResult, EpicSize, InterviewQuestion, InterviewTurn, Plan, ReviewResult, TestResult
from .usage import UsageLimit


class LogLine(Contract):
    ts: AwareDatetime
    text: str


class StageView(Contract):
    status: StageStatus
    now: str | None = None
    logs: list[LogLine] = []


class Stages(Contract):
    manual: StageView
    interviewer: StageView
    planner: StageView
    approval: StageView
    developer: StageView
    tester: StageView
    reviewer: StageView
    done: StageView


class Counters(Contract):
    dev_round: int = 0
    test_attempt: int = 0
    max_test_attempts: int = 3
    review_round: int = 0
    max_review_rounds: int = 2


class InterviewView(Contract):
    turns: list[InterviewTurn] = []
    pending: list[InterviewQuestion] = []  # the round waiting for answers
    decisions: list[str] = []


class Escalation(Contract):
    stage: Literal["interviewer", "planner", "developer", "tester", "reviewer"]
    reason: str
    epic_id: str | None = None  # the lane that escalated, in a split plan


class LaneStages(Contract):
    developer: StageView
    tester: StageView
    reviewer: StageView


EpicStatus = Literal[
    "pending",  # not chosen to run yet
    "waiting",  # chosen, its dependencies are not merged yet
    "preparing",  # worktree/sandbox being set up
    "running",
    "escalated",
    "limited",
    "merging",
    "merged",
    "failed",
]


class EpicView(Contract):
    """One lane of a split plan: an epic, or the integration lane that resolves a merge conflict."""

    id: str
    kind: Literal["epic", "integration"] = "epic"
    title: str
    goal: str = ""
    size: EpicSize = "M"
    depends_on: list[str] = []
    status: EpicStatus
    stages: LaneStages
    edges: dict[EdgeKey, EdgeStatus] = {}
    active_edge: EdgeKey | None = None
    counters: Counters
    dev_rounds: list[DevResult] = []
    test_runs: list[TestResult] = []
    review: ReviewResult | None = None
    escalation: Escalation | None = None
    branch: str | None = None
    worktree_path: str | None = None
    commit: str | None = None  # sha merged into the task branch
    commit_message: str | None = None
    cost_usd: float = 0.0
    tokens: int = 0


class FinalFile(Contract):
    path: str
    status: FileChange
    added: int
    removed: int


class EpicCommit(Contract):
    epic_id: str
    sha: str
    message: str


class FinalReport(Contract):
    branch: str
    worktree_path: str
    files: list[FinalFile]
    commit_message: str
    duration_s: float
    cost_usd: float
    tokens: int = 0
    commits: list[EpicCommit] = []  # split plan: one commit per merged epic, already on ``branch`` (D54)
    pending_epics: list[str] = []  # epics the user chose not to run (they stay in the saved plan)
    plan_doc: str | None = None  # docs/plano/T-n.md inside the worktree (D57)


class TaskView(Contract):
    task_id: str
    title: str
    description: str
    repo: str
    phase: TaskPhase
    stages: Stages
    edges: dict[EdgeKey, EdgeStatus] = {}
    active_edge: EdgeKey | None = None
    counters: Counters
    interview: InterviewView | None = None
    plan: Plan | None = None
    dev_rounds: list[DevResult] = []
    test_runs: list[TestResult] = []
    review: ReviewResult | None = None
    escalation: Escalation | None = None
    final: FinalReport | None = None
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    cost_usd: float = 0.0
    tokens: int = 0  # input + output tokens of every finished job
    limit: UsageLimit | None = None  # set while phase == "limited"
    estimate: Estimate | None = None  # computed when the plan arrives (D56)
    epics: list[EpicView] = []  # split plan lanes; empty for a single execution

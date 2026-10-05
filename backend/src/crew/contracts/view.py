"""TaskView: the snapshot the orchestrator publishes and the UI renders verbatim."""

from typing import Literal

from pydantic import AwareDatetime

from .common import Contract, EdgeKey, EdgeStatus, FileChange, StageStatus, TaskPhase
from .outputs import DevResult, InterviewQuestion, InterviewTurn, Plan, ReviewResult, TestResult


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


class FinalFile(Contract):
    path: str
    status: FileChange
    added: int
    removed: int


class FinalReport(Contract):
    branch: str
    worktree_path: str
    files: list[FinalFile]
    commit_message: str
    duration_s: float
    cost_usd: float


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

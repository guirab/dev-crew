"""Task state kept by the orchestrator and its projection to ``TaskView``.

``TaskState`` is a plain (mutable) pydantic model so it round-trips through SQLite as JSON.
``machine.decide`` never mutates its input: it works on a deep copy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ..contracts import (
    AgentName,
    Counters,
    DevResult,
    EdgeKey,
    EdgeStatus,
    Epic,
    EpicStatus,
    EpicView,
    Escalation,
    Estimate,
    Feedback,
    FinalReport,
    InterviewQuestion,
    InterviewTurn,
    InterviewView,
    LaneStages,
    LogLine,
    Plan,
    RepoContext,
    ReviewResult,
    StageKey,
    Stages,
    StageStatus,
    StageView,
    TaskPhase,
    TaskSpec,
    TaskView,
    TestResult,
    UsageLimit,
)
from ..contracts.common import STAGES, TERMINAL_PHASES

MAX_STAGE_LOGS = 50

EscalationKind = Literal["test_limit", "review_limit", "agent_failed", "workspace", "merge"]
Boot = Literal["create_workspace", "build_report"]
"""Side-effecting step in flight that is not an agent job; re-issued on restart."""


class Limits(BaseModel):
    """Quality loops only: there is no cost or time cap (D51)."""

    max_test_attempts: int = 3
    max_review_rounds: int = 2


class StageState(BaseModel):
    status: StageStatus = "idle"
    now: str | None = None
    logs: list[LogLine] = Field(default_factory=list)


class PendingJob(BaseModel):
    """A job that could not be (or failed to be) executed; resumed by an escalation action."""

    agent: AgentName
    feedback: Feedback | None = None
    edge: EdgeKey | None = None
    now: str | None = None


class EscalationState(BaseModel):
    kind: EscalationKind
    stage: AgentName
    reason: str
    pending: PendingJob | None = None


def _blank_stages() -> dict[StageKey, StageState]:
    return {k: StageState() for k in STAGES}


LANE_STAGES: tuple[StageKey, ...] = ("developer", "tester", "reviewer")


def _lane_stages() -> dict[StageKey, StageState]:
    return {k: StageState() for k in LANE_STAGES}


class LaneState(BaseModel):
    """One lane of a split plan (D53-D55): an epic in its own worktree, or the integration lane that
    resolves the merge conflict of an epic in the task worktree.

    It carries the same pipeline fields as ``TaskState`` (stages, edges, counters, job bookkeeping), so the
    Developer → Tester → Reviewer logic of the machine runs on either.
    """

    id: str
    kind: Literal["epic", "integration"] = "epic"
    title: str
    status: EpicStatus
    limits: Limits = Field(default_factory=Limits)
    merge_of: str | None = None  # integration lane: the epic whose merge conflicted

    stages: dict[StageKey, StageState] = Field(default_factory=_lane_stages)
    edges: dict[EdgeKey, EdgeStatus] = Field(default_factory=dict)
    active_edge: EdgeKey | None = None

    dev_round: int = 0
    test_attempt: int = 0
    review_round: int = 0
    dev_rounds: list[DevResult] = Field(default_factory=list)
    test_runs: list[TestResult] = Field(default_factory=list)
    reviews: list[ReviewResult] = Field(default_factory=list)
    review: ReviewResult | None = None
    escalation: EscalationState | None = None

    current_job_id: UUID | None = None
    current_agent: AgentName | None = None
    inflight: PendingJob | None = None
    limited_pending: PendingJob | None = None
    attempts: dict[AgentName, int] = Field(default_factory=dict)
    sessions: dict[AgentName, str] = Field(default_factory=dict)

    workspace_path: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None
    cost_usd: float = 0.0
    tokens: int = 0

    def to_view(self, epic: Epic | None) -> EpicView:
        def stage(key: StageKey) -> StageView:
            st = self.stages[key]
            return StageView(status=st.status, now=st.now, logs=st.logs[-MAX_STAGE_LOGS:])

        escalation = (
            Escalation(stage=self.escalation.stage, reason=self.escalation.reason, epic_id=self.id)
            if self.status == "escalated" and self.escalation is not None
            else None
        )
        return EpicView(
            id=self.id,
            kind=self.kind,
            title=self.title,
            goal=epic.goal if epic else "",
            size=epic.size if epic else "M",
            depends_on=list(epic.depends_on) if epic else [],
            status=self.status,
            stages=LaneStages(
                developer=stage("developer"), tester=stage("tester"), reviewer=stage("reviewer")
            ),
            edges=dict(self.edges),
            active_edge=self.active_edge,
            counters=Counters(
                dev_round=self.dev_round,
                test_attempt=self.test_attempt,
                max_test_attempts=self.limits.max_test_attempts,
                review_round=self.review_round,
                max_review_rounds=self.limits.max_review_rounds,
            ),
            dev_rounds=list(self.dev_rounds),
            test_runs=list(self.test_runs),
            review=self.review,
            escalation=escalation,
            branch=self.branch,
            worktree_path=self.workspace_path,
            commit=self.commit_sha,
            commit_message=self.commit_message,
            cost_usd=round(self.cost_usd, 6),
            tokens=self.tokens,
        )


class TaskState(BaseModel):
    task_id: str
    title: str
    description: str
    repo: RepoContext
    limits: Limits = Field(default_factory=Limits)
    phase: TaskPhase
    spec: TaskSpec
    workspace_path: str | None = None
    branch: str | None = None
    boot: Boot | None = None

    stages: dict[StageKey, StageState] = Field(default_factory=_blank_stages)
    edges: dict[EdgeKey, EdgeStatus] = Field(default_factory=dict)
    active_edge: EdgeKey | None = None

    dev_round: int = 0
    test_attempt: int = 0
    review_round: int = 0

    interview_turns: list[InterviewTurn] = Field(default_factory=list)
    pending_questions: list[InterviewQuestion] = Field(default_factory=list)
    interview_round: int = 0
    decisions: list[str] = Field(default_factory=list)

    plan: Plan | None = None
    estimate: Estimate | None = None
    dev_rounds: list[DevResult] = Field(default_factory=list)
    test_runs: list[TestResult] = Field(default_factory=list)
    reviews: list[ReviewResult] = Field(default_factory=list)
    review: ReviewResult | None = None
    escalation: EscalationState | None = None
    final: FinalReport | None = None

    current_job_id: UUID | None = None
    current_agent: AgentName | None = None
    inflight: PendingJob | None = None
    job_seq: int = 0
    attempts: dict[AgentName, int] = Field(default_factory=dict)
    sessions: dict[AgentName, str] = Field(default_factory=dict)

    limit: UsageLimit | None = None  # phase == "limited": the subscription quota ran out (D50)
    limited_pending: PendingJob | None = None  # the job to re-run on resume_after_limit

    # split plan (D53-D57)
    lanes: dict[str, LaneState] = Field(default_factory=dict)  # epics in plan order, then integration lanes
    chosen: list[str] = Field(default_factory=list)  # epics the user asked to run
    merge_queue: list[str] = Field(default_factory=list)  # approved epics waiting for their merge
    merging: str | None = None  # epic being merged (one at a time: the task worktree is shared)
    plan_doc: str | None = None  # docs/plano/T-n.md

    started_at: datetime
    ended_at: datetime | None = None
    cost_usd: float = 0.0
    tokens: int = 0

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

    @property
    def split(self) -> bool:
        return bool(self.lanes)

    def epic(self, epic_id: str) -> Epic | None:
        if self.plan is None:
            return None
        return next((e for e in self.plan.epics if e.id == epic_id), None)

    def to_view(self) -> TaskView:
        stages = Stages.model_validate(
            {
                k: StageView(status=st.status, now=st.now, logs=st.logs[-MAX_STAGE_LOGS:])
                for k, st in self.stages.items()
            }
        )
        interview = InterviewView(
            turns=list(self.interview_turns),
            pending=list(self.pending_questions),
            decisions=list(self.decisions),
        )
        escalation = (
            Escalation(stage=self.escalation.stage, reason=self.escalation.reason)
            if self.phase == "escalated" and self.escalation is not None
            else None
        )
        lanes = [lane.to_view(self.epic(lane.id)) for lane in self.lanes.values()]
        if escalation is None and self.phase == "escalated":
            escalation = next((v.escalation for v in lanes if v.escalation is not None), None)
        return TaskView(
            task_id=self.task_id,
            title=self.title,
            description=self.description,
            repo=self.repo.name,
            phase=self.phase,
            stages=stages,
            edges=dict(self.edges),
            active_edge=self.active_edge,
            counters=Counters(
                dev_round=self.dev_round,
                test_attempt=self.test_attempt,
                max_test_attempts=self.limits.max_test_attempts,
                review_round=self.review_round,
                max_review_rounds=self.limits.max_review_rounds,
            ),
            interview=interview,
            plan=self.plan,
            dev_rounds=list(self.dev_rounds),
            test_runs=list(self.test_runs),
            review=self.review,
            escalation=escalation,
            final=self.final,
            started_at=self.started_at,
            ended_at=self.ended_at,
            cost_usd=round(self.cost_usd, 6),
            tokens=self.tokens,
            limit=self.limit if self.phase == "limited" else None,
            estimate=self.estimate,
            epics=lanes,
        )

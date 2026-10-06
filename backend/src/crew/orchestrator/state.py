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
    Escalation,
    Feedback,
    FinalReport,
    InterviewQuestion,
    InterviewTurn,
    InterviewView,
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
)
from ..contracts.common import STAGES, TERMINAL_PHASES

MAX_STAGE_LOGS = 50

EscalationKind = Literal["test_limit", "review_limit", "agent_failed", "budget"]
Boot = Literal["create_workspace", "build_report"]
"""Side-effecting step in flight that is not an agent job; re-issued on restart."""


class Limits(BaseModel):
    max_test_attempts: int = 3
    max_review_rounds: int = 2
    budget_usd: float = 5.0
    job_timeout_s: float = 20 * 60.0


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

    started_at: datetime
    ended_at: datetime | None = None
    cost_usd: float = 0.0

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL_PHASES

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
        )

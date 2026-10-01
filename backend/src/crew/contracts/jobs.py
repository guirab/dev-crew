"""Jobs dispatched by the orchestrator to agent workers."""

from typing import Literal
from uuid import UUID

from .common import AgentName, Contract
from .outputs import InterviewTurn, Plan, ReviewResult, TestResult
from .task import RepoContext, TaskSpec


class Feedback(Contract):
    kind: Literal["test_failures", "review_comments", "human_instruction", "plan_adjust"]
    test: TestResult | None = None
    review: ReviewResult | None = None
    text: str | None = None


class AgentJob(Contract):
    job_id: UUID
    task_id: str
    agent: AgentName
    attempt: int
    repo: RepoContext
    spec: TaskSpec
    plan: Plan | None = None
    feedback: Feedback | None = None
    interview_history: list[InterviewTurn] = []
    workspace_path: str | None = None
    resume_session_id: str | None = None
    budget_usd: float

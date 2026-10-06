"""Commands sent by the UI (via gateway) to the orchestrator over ``crew.cmd``."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from .common import Contract
from .view import TaskView


class StartTask(Contract):
    type: Literal["start_task"] = "start_task"
    repo: str
    title: str
    description: str = ""


class AnswerInterview(Contract):
    """Answers the whole pending round, in order. ``None`` accepts that question's recommendation."""

    type: Literal["answer_interview"] = "answer_interview"
    answers: list[str | None]


class ApprovePlan(Contract):
    """Approve the plan. In a split plan ``epics`` are the ones to run now (empty = all of them)."""

    type: Literal["approve_plan"] = "approve_plan"
    epics: list[str] = []


class RunEpics(Contract):
    """Split plan: run the next batch of epics (D53)."""

    type: Literal["run_epics"] = "run_epics"
    epics: list[str]


class FinishTask(Contract):
    """Split plan: stop here; epics not run stay pending in the saved plan."""

    type: Literal["finish_task"] = "finish_task"


class AdjustPlan(Contract):
    type: Literal["adjust_plan"] = "adjust_plan"
    text: str


class EscalationAction(Contract):
    type: Literal["escalation"] = "escalation"
    action: Literal["instruct", "more_attempts", "replan"]
    text: str | None = None
    epic_id: str | None = None  # the escalated lane, in a split plan


class CancelTask(Contract):
    type: Literal["cancel_task"] = "cancel_task"


class ResumeAfterLimit(Contract):
    """Re-run the jobs stopped by the subscription usage limit (D50)."""

    type: Literal["resume_after_limit"] = "resume_after_limit"


class CreateProject(Contract):
    """New project from scratch (D58): folder + git repo, registered, then the normal flow."""

    type: Literal["create_project"] = "create_project"
    name: str
    parent_dir: str
    title: str
    description: str = ""


Command = Annotated[
    StartTask
    | AnswerInterview
    | ApprovePlan
    | AdjustPlan
    | EscalationAction
    | CancelTask
    | ResumeAfterLimit
    | RunEpics
    | FinishTask
    | CreateProject,
    Field(discriminator="type"),
]
CommandAdapter: TypeAdapter[Command] = TypeAdapter(Command)


class CommandReply(Contract):
    ok: bool
    error: str | None = None
    view: TaskView | None = None

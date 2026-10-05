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
    type: Literal["approve_plan"] = "approve_plan"


class AdjustPlan(Contract):
    type: Literal["adjust_plan"] = "adjust_plan"
    text: str


class EscalationAction(Contract):
    type: Literal["escalation"] = "escalation"
    action: Literal["instruct", "more_attempts", "replan"]
    text: str | None = None


class CancelTask(Contract):
    type: Literal["cancel_task"] = "cancel_task"


Command = Annotated[
    StartTask | AnswerInterview | ApprovePlan | AdjustPlan | EscalationAction | CancelTask,
    Field(discriminator="type"),
]
CommandAdapter: TypeAdapter[Command] = TypeAdapter(Command)


class CommandReply(Contract):
    ok: bool
    error: str | None = None
    view: TaskView | None = None

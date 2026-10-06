"""Messages pushed by the gateway to the browser over ``/ws``."""

from typing import Annotated, Literal

from pydantic import Field

from .common import Contract
from .events import AgentProgress
from .view import TaskView


class WsView(Contract):
    type: Literal["view"] = "view"
    data: TaskView | None


class WsProgress(Contract):
    type: Literal["progress"] = "progress"
    task_id: str
    data: AgentProgress


WsMessage = Annotated[WsView | WsProgress, Field(discriminator="type")]

"""Events published on CREW_EVENTS and the envelope that wraps them."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field

from .common import AgentName, Contract, EventSource
from .outputs import AgentOutput
from .view import TaskView

EventKind = Literal["progress", "result", "failed", "view"]


class AgentProgress(Contract):
    agent: AgentName
    job_id: UUID
    kind: Literal["status", "tool", "text"]
    text: str


class AgentResultEvt(Contract):
    agent: AgentName
    job_id: UUID
    output: AgentOutput
    cost_usd: float = 0.0
    session_id: str | None = None
    duration_s: float = 0.0


class AgentFailedEvt(Contract):
    agent: AgentName
    job_id: UUID
    error: str
    retryable: bool = False


EVENT_PAYLOADS: dict[EventKind, type[Contract]] = {
    "progress": AgentProgress,
    "result": AgentResultEvt,
    "failed": AgentFailedEvt,
    "view": TaskView,
}


class Envelope(Contract):
    """Wire envelope. ``payload`` is decoded according to ``type`` (see ``decode_payload``)."""

    id: UUID = Field(default_factory=uuid4)
    ts: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    task_id: str
    type: EventKind
    source: EventSource
    payload: dict[str, Any]

    def decode_payload(self) -> Contract:
        return EVENT_PAYLOADS[self.type].model_validate(self.payload)

    @classmethod
    def wrap(cls, task_id: str, kind: EventKind, payload: Contract, source: EventSource) -> "Envelope":
        expected = EVENT_PAYLOADS[kind]
        if not isinstance(payload, expected):
            raise TypeError(f"event kind {kind!r} expects {expected.__name__}, got {type(payload).__name__}")
        return cls(task_id=task_id, type=kind, source=source, payload=payload.model_dump(mode="json"))

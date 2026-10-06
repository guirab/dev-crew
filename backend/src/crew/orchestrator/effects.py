"""Side effects requested by the state machine and executed by ``service``."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..contracts import AgentJob, AgentName


@dataclass(frozen=True)
class Persist:
    """Save the task (and append to the event log) before anything else happens."""


@dataclass(frozen=True)
class PublishView:
    """Publish ``state.to_view()`` on ``crew.evt.<task>.view``."""


@dataclass(frozen=True)
class CreateWorkspace:
    task_id: str
    repo: str


@dataclass(frozen=True)
class DispatchJob:
    job: AgentJob


@dataclass(frozen=True)
class CancelJobs:
    """Tell running agents to stop (``crew.ctl.<task>.cancel``) and drop queued jobs."""

    task_id: str
    agent: AgentName | None = None


@dataclass(frozen=True)
class BuildFinalReport:
    task_id: str
    repo: str
    workspace_path: str


@dataclass(frozen=True)
class Reject:
    """The command was refused; the state is unchanged. ``error`` goes into ``CommandReply``."""

    error: str


@dataclass(frozen=True)
class LogStale:
    """An event for a job/task that is not current was ignored."""

    task_id: str
    what: str
    job_id: UUID | None = None


Effect = (
    Persist | PublishView | CreateWorkspace | DispatchJob | CancelJobs | BuildFinalReport | Reject | LogStale
)

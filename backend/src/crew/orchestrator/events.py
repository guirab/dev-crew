"""Inputs of the state machine. Everything carries ``at`` so ``decide`` needs no clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..contracts import (
    AgentFailedEvt,
    AgentProgress,
    AgentResultEvt,
    Command,
    FinalFile,
    RepoContext,
)
from .state import Limits


@dataclass(frozen=True)
class StartParams:
    """Data the service resolves from config for a ``start_task`` (``None`` = unknown repo)."""

    task_id: str
    repo: RepoContext
    limits: Limits


@dataclass(frozen=True)
class CommandReceived:
    command: Command
    at: datetime
    start: StartParams | None = None


@dataclass(frozen=True)
class AgentResult:
    task_id: str
    evt: AgentResultEvt
    at: datetime


@dataclass(frozen=True)
class AgentFailed:
    task_id: str
    evt: AgentFailedEvt
    at: datetime


@dataclass(frozen=True)
class AgentProgressed:
    task_id: str
    evt: AgentProgress
    at: datetime


@dataclass(frozen=True)
class WorkspaceReady:
    task_id: str
    path: str
    branch: str
    at: datetime


@dataclass(frozen=True)
class WorkspaceFailed:
    task_id: str
    error: str
    at: datetime


@dataclass(frozen=True)
class ReportBuilt:
    task_id: str
    files: list[FinalFile]
    at: datetime
    error: str | None = None


@dataclass(frozen=True)
class JobTimedOut:
    task_id: str
    job_id: UUID
    at: datetime


Event = (
    CommandReceived
    | AgentResult
    | AgentFailed
    | AgentProgressed
    | WorkspaceReady
    | WorkspaceFailed
    | ReportBuilt
    | JobTimedOut
)

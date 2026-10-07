"""Side effects requested by the state machine and executed by ``service``."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ..contracts import AgentJob, AgentName, ProjectSetup


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
    plan_doc: str | None = None  # markdown to save in docs/plano/T-n.md first (D57)
    commit_doc: bool = False  # split plan: the doc is committed on the task branch


@dataclass(frozen=True)
class WritePlanDoc:
    """Save the plan in the project (D57); committed in a split plan."""

    task_id: str
    repo: str
    workspace_path: str
    markdown: str
    commit: bool


@dataclass(frozen=True)
class CreateEpicWorkspace:
    """Worktree (+ sandbox/setup) of an epic, from the task branch. Answers ``EpicWorkspaceReady/Failed``."""

    task_id: str
    repo: str
    epic_id: str
    task_path: str
    prepare: bool = True  # False in a new project: nothing to install before E0 writes the manifests


@dataclass(frozen=True)
class RunSetup:
    """New project (D58): install the dependencies in a pipe's worktree before its first Tester.

    Answers ``SetupFinished``. ``epic_id`` is the lane, ``None`` the task itself.
    """

    task_id: str
    epic_id: str | None
    path: str
    command: str


@dataclass(frozen=True)
class SaveProjectSetup:
    """New project (D58): the approved plan decided the commands; save them in the project registry."""

    task_id: str
    repo: str
    setup: ProjectSetup


@dataclass(frozen=True)
class MergeEpic:
    """Commit the approved epic in its worktree and merge it into the task branch. Answers ``EpicMerged``."""

    task_id: str
    repo: str
    epic_id: str
    task_path: str
    commit_message: str
    merge_message: str


@dataclass(frozen=True)
class FinishMerge:
    """Conclude the merge the integration lane resolved. Answers ``EpicMerged``."""

    task_id: str
    repo: str
    epic_id: str
    task_path: str
    message: str


@dataclass(frozen=True)
class RemoveEpicWorkspace:
    """Drop a merged epic's worktree, branch and container (fire and forget)."""

    task_id: str
    repo: str
    epic_id: str
    task_path: str


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
    Persist
    | PublishView
    | CreateWorkspace
    | DispatchJob
    | CancelJobs
    | BuildFinalReport
    | Reject
    | LogStale
    | WritePlanDoc
    | CreateEpicWorkspace
    | MergeEpic
    | FinishMerge
    | RemoveEpicWorkspace
    | RunSetup
    | SaveProjectSetup
)

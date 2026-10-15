"""One line of the task history (GET /api/tasks), read from the ``task`` table. Computed by the backend."""

from pydantic import AwareDatetime

from .common import Contract, FileChange, TaskPhase


class TaskSummary(Contract):
    task_id: str
    title: str
    repo: str
    phase: TaskPhase
    running: bool  # the phase is not terminal (done, cancelled, failed)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None
    duration_s: float  # started_at → ended_at; while running, started_at → now
    cost_usd: float = 0.0
    tokens: int = 0
    commit_message: str | None = None  # suggested commit message of the final report, when there is one
    files_changed: int | None = None  # files in the final report, when there is one
    summary: str  # first line of the commit message; without a final report, the task description


class FileDiff(Contract):
    """Patch of one file of the final report (GET /api/tasks/{id}/diff?path=), computed on demand."""

    path: str
    status: FileChange
    patch: str  # unified diff vs. the task base; empty when binary
    binary: bool = False
    truncated: bool = False  # cut at MAX_PATCH_BYTES, on a line break

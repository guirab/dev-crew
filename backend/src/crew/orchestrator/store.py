"""SQLite persistence (SQLModel): tasks (full state as JSON), jobs and an append-only event log.

The sync API is intentionally tiny; the service calls it through ``asyncio.to_thread``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy import Engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from ..contracts import AgentJob
from .state import TaskState

log = structlog.get_logger(__name__)

JobStatus = str  # dispatched | done | failed | cancelled


class TaskRow(SQLModel, table=True):
    __tablename__ = "task"

    task_id: str = Field(primary_key=True)
    seq: int = Field(index=True)
    phase: str
    state_json: str
    created_at: str
    updated_at: str


class JobRow(SQLModel, table=True):
    __tablename__ = "job"

    job_id: str = Field(primary_key=True)
    task_id: str = Field(index=True)
    agent: str
    attempt: int
    status: str
    cost_usd: float = 0.0
    created_at: str
    finished_at: str | None = None


class EventLogRow(SQLModel, table=True):
    __tablename__ = "event_log"

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True)
    ts: str
    kind: str
    payload: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _seq(task_id: str) -> int:
    return int(task_id.removeprefix("T-"))


class Store:
    def __init__(self, path: Path | None) -> None:
        """``path=None`` keeps everything in memory (tests)."""
        if path is None:
            self.engine: Engine = create_engine(
                "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        SQLModel.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    # ------------------------------------------------------------------ tasks

    def save_task(self, state: TaskState) -> None:
        now = _now()
        with Session(self.engine) as s:
            row = s.get(TaskRow, state.task_id)
            if row is None:
                row = TaskRow(
                    task_id=state.task_id,
                    seq=_seq(state.task_id),
                    phase=state.phase,
                    state_json=state.model_dump_json(),
                    created_at=now,
                    updated_at=now,
                )
            else:
                row.phase = state.phase
                row.state_json = state.model_dump_json()
                row.updated_at = now
            s.add(row)
            s.commit()

    def load_task(self, task_id: str) -> TaskState | None:
        with Session(self.engine) as s:
            row = s.get(TaskRow, task_id)
            return TaskState.model_validate_json(row.state_json) if row else None

    def load_latest(self) -> TaskState | None:
        """The most recent task (highest sequence), terminal or not.

        A row saved by an older, incompatible contract is skipped (``None``) instead of crashing the
        orchestrator on every boot; it stays in the database for inspection.
        """
        with Session(self.engine) as s:
            row = s.exec(select(TaskRow).order_by(col(TaskRow.seq).desc())).first()
            if row is None:
                return None
            try:
                return TaskState.model_validate_json(row.state_json)
            except ValidationError as e:
                log.warning("task_state_incompatible", task_id=row.task_id, errors=e.error_count())
                return None

    def next_task_id(self) -> str:
        with Session(self.engine) as s:
            row = s.exec(select(TaskRow).order_by(col(TaskRow.seq).desc())).first()
            return f"T-{(row.seq if row else 0) + 1}"

    # ------------------------------------------------------------------ jobs

    def record_job(self, job: AgentJob) -> None:
        with Session(self.engine) as s:
            s.merge(
                JobRow(
                    job_id=str(job.job_id),
                    task_id=job.task_id,
                    agent=job.agent,
                    attempt=job.attempt,
                    status="dispatched",
                    created_at=_now(),
                )
            )
            s.commit()

    def finish_job(self, job_id: str, status: JobStatus, cost_usd: float = 0.0) -> None:
        with Session(self.engine) as s:
            row = s.get(JobRow, job_id)
            if row is None:
                return
            row.status = status
            row.cost_usd = cost_usd
            row.finished_at = _now()
            s.add(row)
            s.commit()

    def jobs(self, task_id: str) -> list[JobRow]:
        with Session(self.engine) as s:
            return list(
                s.exec(select(JobRow).where(JobRow.task_id == task_id).order_by(col(JobRow.created_at)))
            )

    # ------------------------------------------------------------------ event log

    def log_event(self, task_id: str, kind: str, payload: str) -> None:
        with Session(self.engine) as s:
            s.add(EventLogRow(task_id=task_id, ts=_now(), kind=kind, payload=payload))
            s.commit()

    def event_log(self, task_id: str) -> list[EventLogRow]:
        with Session(self.engine) as s:
            return list(
                s.exec(
                    select(EventLogRow).where(EventLogRow.task_id == task_id).order_by(col(EventLogRow.id))
                )
            )

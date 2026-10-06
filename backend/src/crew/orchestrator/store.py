"""SQLite persistence (SQLModel): tasks (full state as JSON), jobs and an append-only event log.

The sync API is intentionally tiny; the service calls it through ``asyncio.to_thread``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError
from sqlalchemy import Engine, event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, col, create_engine, select

from ..contracts import AccountUsage, AgentJob, TokenUsage
from .state import TaskState

log = structlog.get_logger(__name__)

JobStatus = str  # dispatched | done | failed | limited | cancelled


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
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0  # cache reads + writes
    models: str = ""  # comma-separated models that worked on the job
    created_at: str
    finished_at: str | None = None


class UsageSampleRow(SQLModel, table=True):
    """One reading of the subscription usage, paired with what the crew had spent so far (D56).

    Consecutive readings in the same window give "% of the window per US$ of crew work", the ratio the
    estimate uses. The user's own Claude use moves the percentages too, so the ratio errs on the high side.
    """

    __tablename__ = "usage_sample"

    fetched_at: str = Field(primary_key=True)
    session_pct: float | None = None
    session_resets_at: str | None = None
    weekly_pct: float | None = None
    weekly_resets_at: str | None = None
    crew_cost_usd: float = 0.0


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
        self._migrate()

    def _migrate(self) -> None:
        """``create_all`` never alters existing tables: add the columns newer versions introduced."""
        with self.engine.begin() as conn:
            for table in SQLModel.metadata.sorted_tables:
                existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table.name}")'))}
                for column in table.columns:
                    if column.name in existing:
                        continue
                    ddl = column.type.compile(dialect=self.engine.dialect)
                    default = getattr(column.default, "arg", None)
                    literal = f" DEFAULT {default!r}" if isinstance(default, (int, float, str)) else ""
                    conn.execute(
                        text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}{literal}')
                    )
                    log.info("db_column_added", table=table.name, column=column.name)

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

    def finish_job(
        self,
        job_id: str,
        status: JobStatus,
        cost_usd: float = 0.0,
        usage: list[TokenUsage] | None = None,
    ) -> None:
        with Session(self.engine) as s:
            row = s.get(JobRow, job_id)
            if row is None:
                return
            row.status = status
            row.cost_usd = cost_usd
            for u in usage or []:
                row.input_tokens += u.input_tokens
                row.output_tokens += u.output_tokens
                row.cache_tokens += u.cache_read_tokens + u.cache_write_tokens
            row.models = ",".join(sorted({u.model for u in usage or []}))
            row.finished_at = _now()
            s.add(row)
            s.commit()

    def jobs(self, task_id: str) -> list[JobRow]:
        with Session(self.engine) as s:
            return list(
                s.exec(select(JobRow).where(JobRow.task_id == task_id).order_by(col(JobRow.created_at)))
            )

    def real_jobs(self) -> list[JobRow]:
        """Finished jobs of real agents (fake runs record ``fake-*`` models; older rows record none)."""
        with Session(self.engine) as s:
            rows = s.exec(select(JobRow).where(JobRow.status == "done", JobRow.models != ""))
            return [r for r in rows if not any(m.startswith("fake-") for m in r.models.split(","))]

    def crew_cost(self) -> float:
        with Session(self.engine) as s:
            return float(sum(r.cost_usd for r in s.exec(select(JobRow))))

    # ------------------------------------------------------------------ usage samples

    def record_usage(self, usage: AccountUsage) -> bool:
        """Store a reading unless it was already stored (same ``fetched_at``). Returns whether it was new."""
        if usage.fetched_at is None or (usage.session_pct is None and usage.weekly_pct is None):
            return False
        key = usage.fetched_at.isoformat()
        with Session(self.engine) as s:
            if s.get(UsageSampleRow, key) is not None:
                return False
        cost = self.crew_cost()
        with Session(self.engine) as s:
            s.add(
                UsageSampleRow(
                    fetched_at=key,
                    session_pct=usage.session_pct,
                    session_resets_at=usage.session_resets_at.isoformat()
                    if usage.session_resets_at
                    else None,
                    weekly_pct=usage.weekly_pct,
                    weekly_resets_at=usage.weekly_resets_at.isoformat() if usage.weekly_resets_at else None,
                    crew_cost_usd=cost,
                )
            )
            s.commit()
        return True

    def usage_samples(self) -> list[UsageSampleRow]:
        with Session(self.engine) as s:
            return list(s.exec(select(UsageSampleRow).order_by(col(UsageSampleRow.fetched_at))))

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

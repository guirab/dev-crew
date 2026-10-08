"""SQLite store: an incompatible persisted task must not take the orchestrator down on boot."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlmodel import Session

from crew import contracts as c
from crew.orchestrator.state import TaskState
from crew.orchestrator.store import HISTORY_LIMIT, Store, TaskRow

from .core_helpers import Driver


def test_load_latest_returns_the_newest_task() -> None:
    store = Store(None)
    d = Driver(task_id="T-3")
    d.boot()
    store.save_task(d.s)
    loaded = store.load_latest()
    assert loaded is not None and loaded.task_id == "T-3"
    assert store.next_task_id() == "T-4"


def test_load_latest_skips_a_state_saved_by_an_older_contract() -> None:
    store = Store(None)
    legacy = '{"task_id": "T-9", "source": "azure", "phase": "planning"}'
    with Session(store.engine) as s:
        s.add(
            TaskRow(task_id="T-9", seq=9, phase="planning", state_json=legacy, created_at="x", updated_at="x")
        )
        s.commit()
    assert store.load_latest() is None, "boot starts clean instead of crash-looping"
    assert store.next_task_id() == "T-10", "new tasks never reuse the old id"


def _saved(store: Store, task_id: str, **update: object) -> TaskState:
    d = Driver(task_id=task_id)
    d.boot()
    state = d.s.model_copy(update=update)
    store.save_task(state)
    return state


def _final(commit_message: str, files: int = 2) -> c.FinalReport:
    return c.FinalReport(
        branch="crew/T-1",
        worktree_path="/wt/T-1",
        files=[c.FinalFile(path=f"f{i}.py", status="M", added=1, removed=0) for i in range(files)],
        commit_message=commit_message,
        duration_s=5.0,
        cost_usd=0.5,
    )


def test_list_tasks_on_an_empty_database() -> None:
    assert Store(None).list_tasks() == []


def test_list_tasks_is_newest_first_and_capped_at_50() -> None:
    store = Store(None)
    for n in range(1, 56):
        _saved(store, f"T-{n}")
    tasks = store.list_tasks()
    assert len(tasks) == HISTORY_LIMIT == 50
    assert [t.task_id for t in tasks] == [f"T-{n}" for n in range(55, 5, -1)]
    assert [t.task_id for t in store.list_tasks(limit=3)] == ["T-55", "T-54", "T-53"]


def test_list_tasks_without_a_final_report_uses_the_description() -> None:
    store = Store(None)
    _saved(store, "T-1", cost_usd=0.1234567, tokens=900)
    (t,) = store.list_tasks()
    assert (t.task_id, t.title, t.repo, t.phase, t.running) == (
        "T-1",
        "Exportar pedidos em CSV",
        "sample-repo",
        "interviewing",
        True,
    )
    assert (t.summary, t.commit_message, t.files_changed, t.ended_at) == ("d", None, None, None)
    assert (t.cost_usd, t.tokens) == (0.123457, 900)
    assert t.duration_s > 0, "a task in progress counts up to now"


def test_list_tasks_summarizes_the_final_report() -> None:
    store = Store(None)
    started = _saved(store, "T-1").started_at
    ended = started + timedelta(seconds=125.4)
    _saved(
        store,
        "T-1",
        phase="done",
        ended_at=ended,
        final=_final("feat: filtro de datas\n\nCorpo longo.", files=3),
    )
    (t,) = store.list_tasks()
    assert (t.phase, t.running, t.ended_at) == ("done", False, ended)
    assert (t.summary, t.files_changed) == ("feat: filtro de datas", 3)
    assert t.commit_message == "feat: filtro de datas\n\nCorpo longo."
    assert t.duration_s == 125.4


def test_list_tasks_includes_terminal_phases_without_a_report() -> None:
    store = Store(None)
    for n, phase in enumerate(("cancelled", "failed"), start=1):
        started = _saved(store, f"T-{n}").started_at
        _saved(store, f"T-{n}", phase=phase, ended_at=started)
    assert [(t.task_id, t.phase, t.running, t.duration_s) for t in store.list_tasks()] == [
        ("T-2", "failed", False, 0.0),
        ("T-1", "cancelled", False, 0.0),
    ]


def test_list_tasks_skips_an_incompatible_row() -> None:
    store = Store(None)
    _saved(store, "T-1")
    with Session(store.engine) as s:
        s.add(
            TaskRow(task_id="T-2", seq=2, phase="planning", state_json="{}", created_at="x", updated_at="x")
        )
        s.commit()
    _saved(store, "T-3")
    assert [t.task_id for t in store.list_tasks()] == ["T-3", "T-1"]


def test_old_database_gets_the_new_job_columns(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "crew.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE job (job_id VARCHAR PRIMARY KEY, task_id VARCHAR, agent VARCHAR, attempt INTEGER,"
        " status VARCHAR, cost_usd FLOAT, created_at VARCHAR, finished_at VARCHAR)"
    )
    con.execute("INSERT INTO job VALUES ('j1', 'T-1', 'developer', 1, 'done', 0.5, 'x', NULL)")
    con.commit()
    con.close()

    store = Store(db)
    (row,) = store.jobs("T-1")
    assert (row.cost_usd, row.input_tokens, row.output_tokens, row.models) == (0.5, 0, 0, "")
    store.close()


def test_finish_job_records_tokens(tmp_path: Path) -> None:
    from crew.contracts import TokenUsage

    from .agents.factories import make_job

    store = Store(None)
    job = make_job("developer", task_id="T-1")
    store.record_job(job)
    usage = [
        TokenUsage(model="b", input_tokens=10, output_tokens=2, cache_read_tokens=7, cache_write_tokens=1),
        TokenUsage(model="a", input_tokens=5, output_tokens=1),
    ]
    store.finish_job(str(job.job_id), "done", 0.3, usage)
    (row,) = store.jobs("T-1")
    assert (row.input_tokens, row.output_tokens, row.cache_tokens, row.models) == (15, 3, 8, "a,b")

"""SQLite store: an incompatible persisted task must not take the orchestrator down on boot."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from crew.orchestrator.store import Store, TaskRow

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

"""SQLite store: an incompatible persisted task must not take the orchestrator down on boot."""

from __future__ import annotations

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

"""GET /api/tasks over ASGI with a real Store (no NATS needed)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
from pydantic import TypeAdapter

from crew import contracts as c
from crew.config import CrewConfig, RepoCfg
from crew.gateway.app import Gateway
from crew.orchestrator.store import HISTORY_LIMIT, Store

from .core_helpers import Driver
from .git_helpers import make_git_repo


def _client(tmp_path: Path, store: Store | None) -> httpx.AsyncClient:
    cfg = CrewConfig(repos=[RepoCfg(name="r", path=tmp_path, test_cmd="pytest -q")])
    transport = httpx.ASGITransport(app=Gateway(MagicMock(), cfg, dist=None, store=store).app)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1")


def _save(store: Store, task_id: str) -> None:
    d = Driver(task_id=task_id)
    d.boot()
    store.save_task(d.s)


async def test_tasks_empty_store_returns_an_empty_list(tmp_path: Path) -> None:
    async with _client(tmp_path, Store(None)) as http:
        r = await http.get("/api/tasks")
    assert r.status_code == 200 and r.json() == []


async def test_tasks_lists_saved_tasks_newest_first_as_task_summary(tmp_path: Path) -> None:
    store = Store(None)
    for n in (1, 2, 3):
        _save(store, f"T-{n}")
    async with _client(tmp_path, store) as http:
        r = await http.get("/api/tasks")
    assert r.status_code == 200
    items = TypeAdapter(list[c.TaskSummary]).validate_python(r.json())
    assert [i.task_id for i in items] == ["T-3", "T-2", "T-1"]
    assert all(i.running and i.duration_s >= 0 for i in items)


async def test_tasks_is_capped_at_the_history_limit(tmp_path: Path) -> None:
    store = Store(None)
    for n in range(1, HISTORY_LIMIT + 6):
        _save(store, f"T-{n}")
    async with _client(tmp_path, store) as http:
        r = await http.get("/api/tasks")
    ids = [i["task_id"] for i in r.json()]
    assert len(ids) == HISTORY_LIMIT == 50
    assert ids[0] == "T-55" and ids[-1] == "T-6"


async def test_tasks_without_a_store_is_empty(tmp_path: Path) -> None:
    async with _client(tmp_path, None) as http:
        r = await http.get("/api/tasks")
    assert r.status_code == 200 and r.json() == []


async def test_task_by_id_returns_the_saved_task_view(tmp_path: Path) -> None:
    store = Store(None)
    _save(store, "T-1")
    _save(store, "T-2")
    async with _client(tmp_path, store) as http:
        r = await http.get("/api/tasks/T-1")
        missing = await http.get("/api/tasks/T-9")
    assert r.status_code == 200
    assert c.TaskView.model_validate(r.json()).task_id == "T-1"
    assert missing.status_code == 404 and missing.json()["detail"] == "tarefa não encontrada"


async def test_task_by_id_without_a_store_is_not_found(tmp_path: Path) -> None:
    async with _client(tmp_path, None) as http:
        r = await http.get("/api/tasks/T-1")
    assert r.status_code == 404


def _save_done(store: Store, worktree: Path) -> None:
    d = Driver(task_id="T-1")
    d.boot()
    d.s.final = c.FinalReport(
        branch="crew/T-1",
        worktree_path=str(worktree),
        files=[c.FinalFile(path="app.py", status="M", added=1, removed=1)],
        commit_message="feat: x",
        duration_s=1.0,
        cost_usd=0.0,
    )
    store.save_task(d.s)


async def test_task_diff_returns_the_patch_of_a_reported_file(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "repos")
    (repo / "app.py").write_text("a\nB\nc\n", "utf-8")
    store = Store(None)
    _save_done(store, repo)
    async with _client(tmp_path, store) as http:
        r = await http.get("/api/tasks/T-1/diff", params={"path": "app.py"})
        outside = await http.get("/api/tasks/T-1/diff", params={"path": "README.md"})
        traversal = await http.get("/api/tasks/T-1/diff", params={"path": "../secret"})
        no_task = await http.get("/api/tasks/T-9/diff", params={"path": "app.py"})
    assert r.status_code == 200
    diff = c.FileDiff.model_validate(r.json())
    assert (diff.path, diff.status, diff.binary, diff.truncated) == ("app.py", "M", False, False)
    assert "+B" in diff.patch
    # only files of the report, never an arbitrary path
    assert outside.status_code == traversal.status_code == no_task.status_code == 404


async def test_task_diff_after_the_worktree_was_removed(tmp_path: Path) -> None:
    store = Store(None)
    _save_done(store, tmp_path / "gone")
    async with _client(tmp_path, store) as http:
        r = await http.get("/api/tasks/T-1/diff", params={"path": "app.py"})
    assert r.status_code == 404 and "worktree removido" in r.json()["detail"]

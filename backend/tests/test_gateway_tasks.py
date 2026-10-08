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

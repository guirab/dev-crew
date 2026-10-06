"""Gateway over real HTTP/WebSocket (uvicorn in-process) in front of the orchestrator + fake agents."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import websockets
from pydantic import TypeAdapter
from websockets.exceptions import InvalidStatus

from crew import contracts as c
from crew.gateway.hub import QUEUE_SIZE, Hub, _Client
from crew.orchestrator import machine as m

from .rig import Rig, start_rig

pytestmark = pytest.mark.nats

WS_MESSAGE = TypeAdapter(c.WsMessage)
ORIGIN = "http://localhost:5173"


@pytest.fixture
async def rig(nats_url: str, tmp_path: Path) -> AsyncIterator[Rig]:
    r = await start_rig(nats_url, tmp_path, gateway=True)
    try:
        yield r
    finally:
        await r.aclose()


def client(rig: Rig) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=rig.base_url, timeout=30)


async def ws_url(rig: Rig) -> str:
    return f"ws://127.0.0.1:{rig.cfg.gateway.port}/ws"


async def next_msg(ws: websockets.ClientConnection, timeout: float = 20) -> c.WsView | c.WsProgress:
    raw = await asyncio.wait_for(ws.recv(), timeout)
    return WS_MESSAGE.validate_json(raw)


# ================================================================================ REST


async def test_get_repos(rig: Rig) -> None:
    async with client(rig) as http:
        r = await http.get("/api/repos")
    assert r.status_code == 200 and r.json() == [{"name": "sample-repo", "base_branch": "main"}]


async def test_get_task_null_then_view_after_start(rig: Rig) -> None:
    async with client(rig) as http:
        assert (await http.get("/api/task")).json() is None
        r = await http.post(
            "/api/commands",
            json={"type": "start_task", "repo": "sample-repo", "title": "x"},
        )
        assert r.status_code == 200
        reply = c.CommandReply.model_validate(r.json())
        assert reply.ok and reply.view is not None and reply.view.task_id == "T-1"
        view = c.TaskView.model_validate((await http.get("/api/task")).json())
        assert view.task_id == "T-1" and view.phase == "interviewing"


async def test_commands_status_mapping(rig: Rig) -> None:
    async with client(rig) as http:
        start = {"type": "start_task", "repo": "sample-repo", "title": "CSV"}
        assert (await http.post("/api/commands", json=start)).status_code == 200
        dup = await http.post("/api/commands", json=start)
        assert dup.status_code == 409 and dup.json() == {
            "ok": False,
            "error": m.ERR_ACTIVE_TASK,
            "view": None,
        }
        await http.post("/api/commands", json={"type": "cancel_task"})
        unknown = await http.post("/api/commands", json={"type": "start_task", "repo": "nope", "title": "x"})
        assert unknown.status_code == 422 and unknown.json()["error"] == m.ERR_UNKNOWN_REPO
        no_task = await http.post("/api/commands", json={"type": "approve_plan"})
        assert no_task.status_code == 409 and no_task.json()["error"] == m.ERR_NO_TASK
        empty = await http.post("/api/commands", json={"type": "adjust_plan", "text": "x"})
        assert empty.status_code == 409


@pytest.mark.parametrize(
    "body",
    [{"type": "nope"}, {"type": "start_task", "source": "ftp", "repo": "x"}, {"type": "adjust_plan"}, []],
)
async def test_invalid_command_body_is_422(rig: Rig, body: object) -> None:
    async with client(rig) as http:
        r = await http.post("/api/commands", json=body)
    assert r.status_code == 422


async def test_service_unavailable_is_503_not_500(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, gateway=True, orchestrator=False, agents=False)
    try:
        async with client(rig) as http:
            assert (await http.get("/api/task")).status_code == 503
            r = await http.post("/api/commands", json={"type": "approve_plan"})
            assert r.status_code == 503 and "indisponível" in r.json()["detail"]
    finally:
        await rig.aclose()


# ================================================================================ security


async def test_host_header_allow_list_blocks_dns_rebinding(rig: Rig) -> None:
    async with client(rig) as http:
        r = await http.get("/api/repos", headers={"Host": "evil.example.com"})
    assert r.status_code == 400


async def test_cross_origin_post_is_rejected_and_cors_is_dev_only(rig: Rig) -> None:
    async with client(rig) as http:
        evil = await http.post(
            "/api/commands", json={"type": "approve_plan"}, headers={"Origin": "http://evil.example"}
        )
        assert evil.status_code == 403
        ok = await http.post("/api/commands", json={"type": "approve_plan"}, headers={"Origin": ORIGIN})
        assert ok.status_code == 409  # allowed origin reaches the handler (no task yet)

        pre = await http.options(
            "/api/commands",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert pre.headers["access-control-allow-origin"] == ORIGIN
        bad = await http.options(
            "/api/commands",
            headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in bad.headers


async def test_security_headers_present(rig: Rig) -> None:
    async with client(rig) as http:
        r = await http.get("/api/repos")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


async def test_websocket_rejects_foreign_origin(rig: Rig) -> None:
    with pytest.raises(InvalidStatus):
        async with websockets.connect(await ws_url(rig), origin="http://evil.example"):
            pass  # pragma: no cover
    async with websockets.connect(await ws_url(rig), origin=ORIGIN) as ws:
        first = await next_msg(ws)
        assert isinstance(first, c.WsView)


async def test_docs_and_openapi_are_not_exposed(rig: Rig) -> None:
    async with client(rig) as http:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await http.get(path)).status_code == 404


# ================================================================================ WebSocket


async def test_ws_snapshot_then_live_views_and_progress_until_done(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, gateway=True, speed=200.0)
    try:
        async with websockets.connect(await ws_url(rig)) as ws:
            first = await next_msg(ws)
            assert isinstance(first, c.WsView) and first.data is None, "no task yet: snapshot is null"

            async with client(rig) as http:
                start = {"type": "start_task", "repo": "sample-repo", "title": "CSV"}
                assert (await http.post("/api/commands", json=start)).status_code == 200
                msgs: list[c.WsView | c.WsProgress] = []
                approved = False
                answered = 0
                while True:
                    msg = await next_msg(ws, timeout=30)
                    msgs.append(msg)
                    if isinstance(msg, c.WsView) and msg.data is not None:
                        iv = msg.data.interview
                        if iv is not None and iv.pending and len(iv.turns) == answered:
                            answered += len(iv.pending)
                            answer = {"type": "answer_interview", "answers": [None] * len(iv.pending)}
                            r = await http.post("/api/commands", json=answer)
                            assert r.status_code == 200
                        if msg.data.phase == "awaiting_approval" and not approved:
                            approved = True
                            r = await http.post("/api/commands", json={"type": "approve_plan"})
                            assert r.status_code == 200
                        if msg.data.phase == "done":
                            break

        views = [m_ for m_ in msgs if isinstance(m_, c.WsView) and m_.data is not None]
        progress = [m_ for m_ in msgs if isinstance(m_, c.WsProgress)]
        assert progress, "agent progress is forwarded between snapshots"
        assert all(p.task_id == "T-1" and p.data.text for p in progress)
        assert views[-1].data is not None and views[-1].data.final is not None
        phases = [v.data.phase for v in views if v.data is not None]
        assert phases[0] == "interviewing" and phases[-1] == "done" and "awaiting_approval" in phases
    finally:
        await rig.aclose()


async def test_ws_late_joiner_gets_latest_snapshot_and_all_clients_get_updates(
    nats_url: str, tmp_path: Path
) -> None:
    rig = await start_rig(nats_url, tmp_path, gateway=True)
    try:
        await rig.ok(c.StartTask(repo="sample-repo", title="CSV"))
        waiting = await rig.wait_for(lambda v: v.interview is not None and bool(v.interview.pending))
        async with (
            websockets.connect(await ws_url(rig)) as late,
            websockets.connect(await ws_url(rig)) as late2,
        ):
            for ws in (late, late2):
                snap = await next_msg(ws)
                assert isinstance(snap, c.WsView) and snap.data is not None
                assert snap.data.task_id == "T-1" and snap.data.interview is not None
                assert snap.data.interview.pending == waiting.interview.pending  # type: ignore[union-attr]
            assert waiting.interview is not None
            await rig.ok(c.AnswerInterview(answers=[None] * len(waiting.interview.pending)))
            for ws in (late, late2):
                while True:
                    msg = await next_msg(ws)
                    if (
                        isinstance(msg, c.WsView)
                        and msg.data
                        and msg.data.interview
                        and msg.data.interview.turns
                    ):
                        break
        assert rig.gateway is not None
        await asyncio.sleep(0.2)
        assert rig.gateway.hub.client_count == 0, "clients are unregistered on disconnect"
    finally:
        await rig.aclose()


async def test_ws_ignores_client_messages(rig: Rig) -> None:
    async with websockets.connect(await ws_url(rig)) as ws:
        await next_msg(ws)
        await ws.send(json.dumps({"type": "approve_plan"}))
        await ws.send("garbage")
        await asyncio.sleep(0.2)
        assert (await rig.current()) is None, "the socket is read-only: commands go through POST"


async def test_hub_slow_consumer_is_resynced_with_the_latest_snapshot() -> None:
    hub = Hub(bus=MagicMock())
    client_ = _Client(MagicMock())
    for i in range(QUEUE_SIZE + 5):
        hub._offer(client_, json.dumps({"type": "progress", "n": i}))
    msgs = []
    while not client_.queue.empty():
        msgs.append(json.loads(client_.queue.get_nowait()))
    # backlog dropped, a fresh snapshot comes first, live messages continue after it
    assert msgs[0] == {"type": "view", "data": None}
    assert len(msgs) < 10 and msgs[-1] == {"type": "progress", "n": QUEUE_SIZE + 4}


# ================================================================================ static frontend


async def test_serves_frontend_dist_when_present(nats_url: str, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>crew</title>", "utf-8")
    rig = await start_rig(nats_url, tmp_path, gateway=True, dist=dist)
    try:
        async with client(rig) as http:
            page = await http.get("/")
            assert page.status_code == 200 and "<title>crew</title>" in page.text
            assert (await http.get("/api/repos")).status_code == 200, "API routes win over the static mount"
    finally:
        await rig.aclose()


async def test_no_dist_means_no_root_route(rig: Rig) -> None:
    async with client(rig) as http:
        assert (await http.get("/")).status_code == 404

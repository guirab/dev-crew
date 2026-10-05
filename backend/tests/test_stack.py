"""`crew up` assembled in-process (same code path as the CLI): HTTP commands in, views out, until done."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from crew import contracts as c
from crew.bus import Bus
from crew.config import CrewConfig, NatsCfg, Secrets
from crew.stack import (
    StackError,
    StackOptions,
    agent_factories,
    load_agent_runtime,
    run_stack,
    supervise,
    validate_service_name,
)

from .rig import _wait_port, make_config

pytestmark = pytest.mark.nats


class Stack:
    def __init__(
        self, cfg: CrewConfig, http: httpx.AsyncClient, task: asyncio.Task[None], stop: asyncio.Event
    ):
        self.cfg, self.http, self.task, self.stop = cfg, http, task, stop

    async def post(self, body: dict[str, object]) -> httpx.Response:
        return await self.http.post("/api/commands", json=body)

    async def view(self) -> c.TaskView | None:
        data = (await self.http.get("/api/task")).json()
        return None if data is None else c.TaskView.model_validate(data)

    async def until(self, pred, timeout: float = 40) -> c.TaskView:  # type: ignore[no-untyped-def]
        async def poll() -> c.TaskView:
            while True:
                v = await self.view()
                if v is not None and pred(v):
                    return v
                await asyncio.sleep(0.05)

        return await asyncio.wait_for(poll(), timeout)

    async def phase(self, phase: str, timeout: float = 40) -> c.TaskView:
        return await self.until(lambda v: v.phase == phase, timeout)


@pytest.fixture
async def make_stack(nats_url: str, tmp_path: Path):  # type: ignore[no-untyped-def]
    started: list[Stack] = []

    async def make(*, speed: float = 5000.0, escalate: bool = False) -> Stack:
        cfg = make_config(tmp_path).model_copy(update={"nats": NatsCfg(url=nats_url)})
        stop = asyncio.Event()
        opts = StackOptions(
            fake_agents=True,
            fake_speed=speed,
            fake_escalate=escalate,
            builtin_fakes=True,
            db=tmp_path / "crew.db",
            dist=None,
        )
        # fresh streams per test (the nats-server is shared by the whole session)
        bus = await Bus.connect(nats_url)
        await bus.ensure_streams()
        for stream in ("CREW_JOBS", "CREW_EVENTS"):
            await bus.js.purge_stream(stream)
        await bus.close()
        task = asyncio.create_task(run_stack(cfg, Secrets(), opts, stop))
        await _wait_port(cfg.gateway.port, timeout=15)
        http = httpx.AsyncClient(base_url=f"http://127.0.0.1:{cfg.gateway.port}", timeout=30)
        st = Stack(cfg, http, task, stop)
        started.append(st)
        return st

    yield make

    for st in started:
        st.stop.set()
        await st.http.aclose()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(st.task, 20)


async def answer_interview(st: Stack, *, last: str | None = None) -> None:
    """The builtin fake interviewer asks 2 rounds (2 + 1 questions); accept all but optionally the last."""
    for round_size, answered in ((2, 0), (1, 2)):
        await st.until(
            lambda v, n=answered: (
                v.interview is not None and bool(v.interview.pending) and len(v.interview.turns) == n
            )
        )
        answers: list[str | None] = [None] * round_size
        if round_size == 1:
            answers[-1] = last
        assert (await st.post({"type": "answer_interview", "answers": answers})).status_code == 200


async def test_up_plan_adjustment_to_done(make_stack) -> None:  # type: ignore[no-untyped-def]
    st: Stack = await make_stack()
    repos = (await st.http.get("/api/repos")).json()
    assert repos[0]["name"] == "sample-repo"
    start = await st.post({"type": "start_task", "repo": "sample-repo", "title": "Filtro de datas"})
    assert start.status_code == 200
    await answer_interview(st)
    await st.phase("awaiting_approval")
    adjust = await st.post({"type": "adjust_plan", "text": "sem tocar em auth"})
    assert adjust.status_code == 200
    await st.until(
        lambda v: v.phase == "awaiting_approval" and v.plan is not None and "sem tocar" in v.plan.summary
    )
    assert (await st.post({"type": "approve_plan"})).status_code == 200
    done = await st.phase("done")
    assert done.final is not None and done.final.files and done.final.commit_message
    assert done.stages.done.status == "done" and done.review is not None and done.review.verdict == "approved"


async def test_up_manual_path_with_interview_to_done(make_stack) -> None:  # type: ignore[no-untyped-def]
    st: Stack = await make_stack()
    r = await st.post({"type": "start_task", "repo": "sample-repo", "title": "Exportar CSV"})
    assert r.status_code == 200
    await answer_interview(st, last="sem libs novas")
    await st.phase("awaiting_approval")
    await st.post({"type": "approve_plan"})
    done = await st.phase("done")
    assert done.final is not None
    assert done.interview is not None and done.interview.decisions[-1] == "Restrições: sem libs novas"


async def test_up_escalation_then_instruct_to_done(make_stack) -> None:  # type: ignore[no-untyped-def]
    st: Stack = await make_stack(escalate=True)
    await st.post({"type": "start_task", "repo": "sample-repo", "title": "Erro 500 ao salvar"})
    await answer_interview(st)
    await st.phase("awaiting_approval")
    await st.post({"type": "approve_plan"})
    esc = await st.phase("escalated")
    assert esc.escalation is not None and esc.escalation.stage == "tester"
    assert (await st.post({"type": "escalation", "action": "instruct"})).status_code == 422  # text required
    assert (
        await st.post({"type": "escalation", "action": "instruct", "text": "use fake timers"})
    ).status_code == 200
    done = await st.phase("done")
    assert done.final is not None


async def test_up_cancel_then_new_task(make_stack) -> None:  # type: ignore[no-untyped-def]
    st: Stack = await make_stack(speed=2.0)
    await st.post({"type": "start_task", "repo": "sample-repo", "title": "Exportar CSV"})
    await st.phase("interviewing")
    assert (await st.post({"type": "cancel_task"})).status_code == 200
    cancelled = await st.phase("cancelled")
    assert cancelled.ended_at is not None
    second = await st.post({"type": "start_task", "repo": "sample-repo", "title": "outra"})
    assert second.status_code == 200 and second.json()["view"]["task_id"] == "T-2"


# ---------------------------------------------------------------------------------- wiring helpers


def test_service_name_validation() -> None:
    for ok in ("orchestrator", "gateway", "agent:planner"):
        assert validate_service_name(ok) == ok
    for bad in ("agent:nobody", "azure", "web", ""):
        with pytest.raises(StackError):
            validate_service_name(bad)


def test_real_agents_need_the_agents_runtime_but_not_an_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = make_config(tmp_path)
    runtime = load_agent_runtime()
    if runtime is None:
        with pytest.raises(StackError, match="agentes reais indisponíveis"):
            agent_factories(None, cfg, Secrets(), StackOptions(), asyncio.Event())  # type: ignore[arg-type]
    else:
        # no key = subscription login; must build the factories instead of raising
        factories = agent_factories(None, cfg, Secrets(_env_file=None), StackOptions(), asyncio.Event())  # type: ignore[arg-type]
        assert factories


async def test_supervisor_restarts_a_crashing_service_and_stops_cleanly() -> None:
    stop = asyncio.Event()
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("worker died")
        stop.set()

    await asyncio.wait_for(supervise("flaky", flaky, stop, backoff=(0.01,)), 5)
    assert calls == 3


async def test_supervisor_propagates_cancellation() -> None:
    stop = asyncio.Event()

    async def forever() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(supervise("x", forever, stop))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cli_up_process_serves_the_gateway_with_fakes(nats_url: str, tmp_path: Path) -> None:
    """The real entry point (`python -m crew.cli up`): config file, logging, flags, fake wiring."""
    cfg = make_config(tmp_path)
    toml = tmp_path / "crew.toml"
    repo = cfg.repos[0]
    toml.write_text(
        f'[nats]\nurl = "{nats_url}"\n[gateway]\nport = {cfg.gateway.port}\n'
        f'[workspace]\nroot = "{cfg.workspace.root.as_posix()}"\n'
        f'[[repos]]\nname = "sample-repo"\npath = "{repo.path.as_posix()}"\ntest_cmd = "echo ok"\n',
        "utf-8",
    )
    env = {**os.environ, "CREW_HOME": str(tmp_path / "home"), "CREW_CONFIG": str(toml)}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "crew.cli",
            "up",
            "--fake-agents",
            "--builtin-fakes",
            "--no-frontend",
        ],
        env=env,
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await _wait_port(cfg.gateway.port, timeout=30)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{cfg.gateway.port}", timeout=20) as http:
            assert (await http.get("/api/repos")).json()[0]["name"] == "sample-repo"
            assert (await http.get("/api/task")).json() is None
    finally:
        proc.kill()
        proc.wait(timeout=10)

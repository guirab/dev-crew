"""Test rig: orchestrator + fake agents on a real nats-server, driven through the bus only."""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nats.aio.msg import Msg
from pydantic import TypeAdapter

from crew import contracts as c
from crew.bus import Bus
from crew.bus import subjects as s
from crew.config import CrewConfig, GatewayCfg, LimitsCfg, RepoCfg, WorkspaceCfg
from crew.gateway.app import Gateway
from crew.orchestrator.devfakes import FakeCrew
from crew.orchestrator.service import OrchestratorService
from crew.orchestrator.store import Store
from crew.workspace.manager import WorkspaceManager

from .git_helpers import make_git_repo

VIEW_OR_NONE = TypeAdapter(c.TaskView | None)
WAIT_S = 30.0


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_config(
    tmp_path: Path, repo_path: Path | None = None, port: int | None = None, **limits: Any
) -> CrewConfig:
    repo = repo_path or make_git_repo(tmp_path / "repos")
    return CrewConfig(
        gateway=GatewayCfg(port=port or free_port()),
        workspace=WorkspaceCfg(root=tmp_path / "worktrees"),
        limits=LimitsCfg(**limits),
        repos=[RepoCfg(name="sample-repo", path=repo, base_branch="main", test_cmd="pytest -q")],
    )


@dataclass
class Rig:
    bus: Bus
    cfg: CrewConfig
    store: Store
    stop: asyncio.Event
    views: list[c.TaskView] = field(default_factory=list)
    progress: list[c.AgentProgress] = field(default_factory=list)
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    svc: OrchestratorService | None = None
    fake: FakeCrew | None = None
    gateway: Gateway | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.cfg.gateway.port}"

    # ------------------------------------------------------------------ observation

    async def _on_view(self, msg: Msg) -> None:
        env = c.Envelope.model_validate_json(msg.data)
        view = c.TaskView.model_validate(env.payload)
        async with self._changed:
            self.views.append(view)
            self._changed.notify_all()

    async def _on_progress(self, msg: Msg) -> None:
        env = c.Envelope.model_validate_json(msg.data)
        self.progress.append(c.AgentProgress.model_validate(env.payload))

    async def wait_for(self, pred: Callable[[c.TaskView], bool], timeout: float = WAIT_S) -> c.TaskView:
        async def _poll() -> c.TaskView:
            async with self._changed:
                while True:
                    for v in reversed(self.views):
                        if pred(v):
                            return v
                    await self._changed.wait()

        try:
            return await asyncio.wait_for(_poll(), timeout)
        except TimeoutError:
            last = self.views[-1] if self.views else None
            raise AssertionError(
                f"timeout waiting for view; last phase={last.phase if last else None}, "
                f"phases seen={self.phases()}"
            ) from None

    async def wait_phase(self, phase: c.TaskPhase, timeout: float = WAIT_S) -> c.TaskView:
        return await self.wait_for(lambda v: v.phase == phase, timeout)

    def phases(self) -> list[str]:
        """Phase of each published view with consecutive duplicates removed."""
        out: list[str] = []
        for v in self.views:
            if not out or out[-1] != v.phase:
                out.append(v.phase)
        return out

    # ------------------------------------------------------------------ commands

    async def cmd(self, command: c.Command) -> c.CommandReply:
        return await self.bus.request(s.CMD, command, c.CommandReply, timeout=20)

    async def ok(self, command: c.Command) -> c.TaskView:
        reply = await self.cmd(command)
        assert reply.ok and reply.view is not None, reply
        return reply.view

    async def current(self) -> c.TaskView | None:
        raw = await self.bus.request_raw(s.STATE_CURRENT, timeout=5)
        return VIEW_OR_NONE.validate_json(raw)

    # ------------------------------------------------------------------ lifecycle

    def spawn(self, coro: Awaitable[None], name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coro, name=name)  # type: ignore[arg-type]
        self.tasks.append(task)
        return task

    async def aclose(self) -> None:
        self.stop.set()
        for t in self.tasks:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(t, 10)
        for t in self.tasks:
            if not t.done():
                t.cancel()
        await self.bus.close()
        self.store.close()


async def start_rig(
    nats_url: str,
    tmp_path: Path,
    *,
    speed: float = 5000.0,
    escalate: bool = False,
    agents: bool = True,
    gateway: bool = False,
    dist: Path | None = None,
    orchestrator: bool = True,
    store: Store | None = None,
    cfg: CrewConfig | None = None,
    clean: bool = True,
    **limits: Any,
) -> Rig:
    cfg = cfg or make_config(tmp_path, **limits)
    bus = await Bus.connect(nats_url, name="rig")
    await bus.ensure_streams()
    if clean:
        for stream in (s.STREAM_JOBS, s.STREAM_EVENTS):
            await bus.js.purge_stream(stream)
    rig = Rig(bus=bus, cfg=cfg, store=store or Store(None), stop=asyncio.Event())
    await bus.subscribe_core(s.evt_kind_wildcard("view"), rig._on_view)
    await bus.subscribe_core(s.evt_kind_wildcard("progress"), rig._on_progress)

    if agents:
        rig.fake = FakeCrew(bus, speed=speed, escalate=escalate)
        rig.spawn(rig.fake.run(rig.stop), "fake-agents")
    if orchestrator:
        await start_orchestrator(rig)
    if gateway:
        rig.gateway = Gateway(bus, cfg, dist=dist)
        rig.spawn(rig.gateway.run(rig.stop), "gateway")
        await _wait_port(cfg.gateway.port)
    return rig


async def _wait_port(port: int, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.05)
            continue
        writer.close()
        return
    raise RuntimeError(f"port {port} never opened")


async def start_orchestrator(rig: Rig, stop: asyncio.Event | None = None) -> asyncio.Task[None]:
    rig.svc = OrchestratorService(
        rig.bus, rig.cfg, rig.store, WorkspaceManager(rig.cfg.workspace.root, rig.cfg.workspace.mode)
    )
    task = rig.spawn(rig.svc.run(stop or rig.stop), "orchestrator")
    for _ in range(100):  # wait until it answers
        try:
            await rig.current()
            break
        except Exception:
            await asyncio.sleep(0.05)
    return task

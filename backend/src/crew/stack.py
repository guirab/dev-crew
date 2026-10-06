"""Composition root: wires the services of ``crew up`` / ``crew svc`` onto one NATS connection each.

Every service is a coroutine ``run(stop)`` that talks only through the bus, so the same code runs in one
process (``up``) or one process per service (``svc``).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from .bus import Bus
from .config import CrewConfig, Secrets, db_path
from .contracts import AGENTS, AgentName
from .gateway.app import DEFAULT_DIST, Gateway
from .orchestrator.devfakes import FakeCrew
from .orchestrator.service import OrchestratorService
from .orchestrator.store import Store
from .workspace.manager import WorkspaceManager

log = structlog.get_logger(__name__)

SERVICE_NAMES = ("orchestrator", "gateway")
BACKOFF_S = (1.0, 2.0, 5.0, 10.0)
STABLE_AFTER_S = 60.0


class StackError(RuntimeError):
    """Cannot start: the message tells the user what to do (pt-BR)."""


@dataclass(frozen=True)
class StackOptions:
    fake_agents: bool = False
    fake_speed: float = 1.0
    fake_escalate: bool = False
    builtin_fakes: bool = False  # force crew.orchestrator.devfakes even when Stream B's service exists
    db: Path | None = None
    dist: Path | None = DEFAULT_DIST


# ====================================================================== supervision


async def supervise(
    name: str,
    factory: Callable[[], Awaitable[None]],
    stop: asyncio.Event,
    *,
    backoff: tuple[float, ...] = BACKOFF_S,
) -> None:
    """Run ``factory()`` until ``stop``; restart it with backoff when it crashes.

    Needed because a worker that dies silently (e.g. nats-py fetch timeouts) would leave the crew stuck.
    """
    attempt = 0
    while not stop.is_set():
        started = time.monotonic()
        try:
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("service_crashed", service=name)
        if time.monotonic() - started > STABLE_AFTER_S:
            attempt = 0
        delay = backoff[min(attempt, len(backoff) - 1)]
        attempt += 1
        log.warning("service_restarting", service=name, in_s=delay)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), delay)


# ====================================================================== agents


@dataclass(frozen=True)
class AgentRuntime:
    """Stream B's worker entry point, imported lazily (it may not be merged yet)."""

    run_agent: Callable[..., Awaitable[None]]
    settings_cls: type[Any]


def load_agent_runtime() -> AgentRuntime | None:
    """``crew.agents.service.run_agent`` + ``crew.agents.settings.AgentRuntimeSettings`` or ``None``."""
    try:
        service = importlib.import_module("crew.agents.service")
        settings = importlib.import_module("crew.agents.settings")
    except ModuleNotFoundError as e:
        if e.name in {"crew.agents.service", "crew.agents.settings"}:
            return None
        raise  # a real missing dependency inside Stream B's code: do not hide it
    return AgentRuntime(run_agent=service.run_agent, settings_cls=settings.AgentRuntimeSettings)


def agent_factories(
    bus: Bus,
    cfg: CrewConfig,
    secrets: Secrets,
    opts: StackOptions,
    stop: asyncio.Event,
    agents: tuple[AgentName, ...] = AGENTS,
) -> dict[str, Callable[[], Awaitable[None]]]:
    """One restartable factory per agent worker."""
    runtime = None if opts.builtin_fakes else load_agent_runtime()

    if runtime is None:
        if not opts.fake_agents:
            raise StackError(
                "agentes reais indisponíveis: crew.agents.service não existe nesta build. "
                "Use --fake-agents ou espere o merge do Stream B."
            )
        log.warning("using_builtin_fake_agents", reason="crew.agents.service ausente ou --builtin-fakes")
        crew = FakeCrew(bus, speed=opts.fake_speed, escalate=opts.fake_escalate)
        # the fakes share one scenario script (counters), so they run as ONE restartable unit
        return {"fake-agents": lambda: crew.run(stop, agents)}

    if not opts.fake_agents:
        # No key = the CLI uses the Claude subscription login (`claude auth login`). A key bills the API.
        key = secrets.anthropic_api_key
        if key is not None:
            os.environ.setdefault("ANTHROPIC_API_KEY", key.get_secret_value())  # the Agent SDK reads the env
        if os.environ.get("ANTHROPIC_API_KEY"):
            log.warning("anthropic_api_key_set", detail="agentes vão cobrar na API, não na assinatura")

    def make(agent: AgentName) -> Callable[[], Awaitable[None]]:
        async def run() -> None:
            settings = runtime.settings_cls(
                model=cfg.model_for(agent),
                fake=opts.fake_agents,
                fake_speed=opts.fake_speed,
                fake_escalate=opts.fake_escalate,
            )
            await runtime.run_agent(bus, agent, settings=settings, stop=stop)

        return run

    return {f"agent:{a}": make(a) for a in agents}


# ====================================================================== other services


def build_orchestrator(bus: Bus, cfg: CrewConfig, opts: StackOptions) -> tuple[OrchestratorService, Store]:
    store = Store(opts.db or db_path())
    workspace = WorkspaceManager(cfg.workspace.root, cfg.workspace.mode)
    return OrchestratorService(bus, cfg, store, workspace), store


# ====================================================================== run


async def run_stack(
    cfg: CrewConfig,
    secrets: Secrets,
    opts: StackOptions,
    stop: asyncio.Event,
    *,
    only: str | None = None,
) -> None:
    """Run everything (``only=None``) or a single service (``orchestrator|gateway|agent:<name>``)."""
    bus = await Bus.connect(cfg.nats.url, name=f"crew-{only or 'up'}")
    await bus.ensure_streams()
    store: Store | None = None
    tasks: list[asyncio.Task[None]] = []

    def launch(name: str, factory: Callable[[], Awaitable[None]]) -> None:
        tasks.append(asyncio.create_task(supervise(name, factory, stop), name=name))

    try:
        if only in (None, "orchestrator"):
            svc, store = build_orchestrator(bus, cfg, opts)
            launch("orchestrator", lambda: svc.run(stop))
        if only in (None, "gateway"):
            gateway = Gateway(bus, cfg, dist=opts.dist)
            launch("gateway", lambda: gateway.run(stop))
        if only is None or only.startswith("agent:"):
            selected = AGENTS if only is None else (_agent_name(only),)
            for name, factory in agent_factories(bus, cfg, secrets, opts, stop, selected).items():
                launch(name, factory)
        if not tasks:
            raise StackError(f"nada para executar em {only!r} com esta configuração")
        log.info("stack_started", services=[t.get_name() for t in tasks])
        done_early = asyncio.create_task(_first_failure(tasks, stop))
        try:
            await stop.wait()
        finally:
            done_early.cancel()
    finally:
        stop.set()
        _, pending = await asyncio.wait(tasks, timeout=15) if tasks else (set(), set())
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await bus.close()
        if store is not None:
            store.close()
        log.info("stack_stopped")


async def _first_failure(tasks: list[asyncio.Task[None]], stop: asyncio.Event) -> None:
    """A service that exits with an error (not restartable) takes the whole process down loudly."""
    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for t in done:
        if not t.cancelled() and t.exception() is not None:
            log.error("service_failed", service=t.get_name(), error=str(t.exception()))
            stop.set()
            return


def _agent_name(spec: str) -> AgentName:
    name = spec.removeprefix("agent:")
    for a in AGENTS:
        if a == name:
            return a
    raise StackError(f"agente desconhecido: {name!r} (use um de: {', '.join(AGENTS)})")


def validate_service_name(name: str) -> str:
    if name in SERVICE_NAMES:
        return name
    if name.startswith("agent:"):
        _agent_name(name)
        return name
    raise StackError(f"serviço desconhecido: {name!r} (use orchestrator, gateway ou agent:<nome>)")

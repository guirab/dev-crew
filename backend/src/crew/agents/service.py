"""Agent worker service: consume ``crew.job.<agent>``, run the job, publish progress and the result."""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

import structlog

from ..bus import Bus, FatalJobError, JobControl, job_loop
from ..bus.subjects import cancel_subject
from ..contracts import AgentJob, AgentName, AgentProgress, AgentResultEvt
from . import prodguard
from .progress import ProgressLine, ProgressSink
from .runner import Runner, SdkRunner
from .settings import AgentRuntimeSettings
from .specs import effective_test_globs

log = structlog.get_logger(__name__)


def make_runner(settings: AgentRuntimeSettings) -> Runner:
    if settings.fake:
        from .fake import ScriptedRunner

        return ScriptedRunner(settings)
    return SdkRunner(settings)


async def run_agent(
    bus: Bus,
    agent: AgentName,
    *,
    settings: AgentRuntimeSettings,
    stop: asyncio.Event,
    runner: Runner | None = None,
    heartbeat_s: float = 30.0,
) -> None:
    """Process jobs one at a time until ``stop`` is set (concurrency 1 per process).

    ``runner`` and ``heartbeat_s`` exist for tests; production callers pass only the first four.
    """
    active = runner or make_runner(settings)

    async def handle(job: AgentJob, ctl: JobControl) -> None:
        await _handle_job(bus, agent, active, job)

    log.info("agent_worker_started", agent=agent, fake=settings.fake, model=settings.model)
    await job_loop(bus, agent, handle, stop=stop, heartbeat_s=heartbeat_s)


async def _handle_job(bus: Bus, agent: AgentName, runner: Runner, job: AgentJob) -> None:
    started = time.monotonic()

    async def emit(line: ProgressLine) -> None:
        # progress is best effort: a hiccup publishing it must never fail the job
        with contextlib.suppress(Exception):
            payload = AgentProgress(agent=agent, job_id=job.job_id, kind=line.kind, text=line.text)
            await bus.publish_event(job.task_id, "progress", payload, source=agent)

    sink: ProgressSink = emit
    await sink(ProgressLine("status", "iniciando"))

    cancelled = asyncio.Event()

    async def on_cancel(_msg: object) -> None:
        cancelled.set()

    guarded = _production_guard(job)
    before = await asyncio.to_thread(prodguard.snapshot, *guarded) if guarded else None
    sub = await bus.subscribe_core(cancel_subject(job.task_id), on_cancel)
    run_task = asyncio.create_task(runner.run(job, sink))
    cancel_task = asyncio.create_task(cancelled.wait())
    try:
        await asyncio.wait({run_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task
            raise FatalJobError("cancelled")
        outcome = run_task.result()  # re-raises RetryableJobError / FatalJobError / crashes
    except asyncio.CancelledError:  # the worker itself is shutting down
        run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await run_task
        raise
    finally:
        cancel_task.cancel()
        with contextlib.suppress(Exception):
            await sub.unsubscribe()

    if guarded and before is not None:
        touched = prodguard.changed(before, await asyncio.to_thread(prodguard.snapshot, *guarded))
        if touched:
            raise FatalJobError(prodguard.describe(touched))

    result = AgentResultEvt(
        agent=agent,
        job_id=job.job_id,
        output=outcome.output,
        cost_usd=outcome.cost_usd,
        session_id=outcome.session_id,
        duration_s=round(time.monotonic() - started, 3),
    )
    await bus.publish_event(job.task_id, "result", result, source=agent)


def _production_guard(job: AgentJob) -> tuple[Path, tuple[str, ...]] | None:
    """Tester jobs only (D42): worktree + test globs for the before/after production snapshot."""
    if job.agent != "tester" or not job.workspace_path:
        return None
    return Path(job.workspace_path), effective_test_globs(job)

"""Orchestrator service: the I/O shell around ``machine.decide``.

All inputs (commands, agent results, progress, async effect completions, timeouts) go through ONE inbox
consumed by ONE worker, so ``decide`` always sees a consistent state. Slow effects (worktree,
diff report) run as background tasks and post their completion back into the inbox.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from nats.aio.msg import Msg
from pydantic import BaseModel, ValidationError

from ..bus import Bus
from ..bus import subjects as s
from ..config import CrewConfig
from ..contracts import (
    AgentFailedEvt,
    AgentProgress,
    AgentResultEvt,
    CommandAdapter,
    CommandReply,
    Envelope,
    StartTask,
)
from ..workspace.manager import WorkspaceManager
from . import machine
from .effects import (
    BuildFinalReport,
    CancelJobs,
    CreateWorkspace,
    DispatchJob,
    Effect,
    LogStale,
    Persist,
    PublishView,
    Reject,
)
from .events import (
    AgentFailed,
    AgentProgressed,
    AgentResult,
    CommandReceived,
    Event,
    JobTimedOut,
    ReportBuilt,
    StartParams,
    WorkspaceFailed,
    WorkspaceReady,
)
from .state import Limits, TaskState
from .store import Store

log = structlog.get_logger(__name__)

COMMAND_TIMEOUT_S = 30.0


@dataclass
class _Item:
    event: Event
    reply: asyncio.Future[CommandReply | None] | None = None


Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OrchestratorService:
    def __init__(
        self,
        bus: Bus,
        cfg: CrewConfig,
        store: Store,
        workspace: WorkspaceManager,
        *,
        clock: Clock = _utcnow,
    ) -> None:
        self.bus = bus
        self.cfg = cfg
        self.store = store
        self.workspace = workspace
        self.clock = clock
        self.state: TaskState | None = None
        self._inbox: asyncio.Queue[_Item] = asyncio.Queue()
        self._bg: set[asyncio.Task[None]] = set()
        self._timers: dict[str, asyncio.Task[None]] = {}

    # ================================================================= lifecycle

    async def run(self, stop: asyncio.Event) -> None:
        """Serve until ``stop`` is set. Safe to cancel."""
        subs: list[Any] = []
        loops: list[asyncio.Task[None]] = []
        try:
            # recover BEFORE accepting any input, or a redelivered result would look stale
            await self._recover()
            subs = [
                await self.bus.serve(s.CMD, self._serve_cmd),
                await self.bus.serve(s.STATE_CURRENT, self._serve_state),
                await self.bus.subscribe_core(s.evt_kind_wildcard("progress"), self._on_progress_msg),
            ]
            loops = [
                asyncio.create_task(self._worker(), name="orchestrator-worker"),
                asyncio.create_task(self._consume_results(stop), name="orchestrator-consumer"),
            ]
            for t in loops:
                t.add_done_callback(_log_task_end)
            log.info("orchestrator_started", task=self.state.task_id if self.state else None)
            await stop.wait()
        finally:
            pending = [*loops, *self._bg, *self._timers.values()]
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for sub in subs:
                with contextlib.suppress(Exception):
                    await sub.unsubscribe()
            log.info("orchestrator_stopped")

    async def _recover(self) -> None:
        """Reload the last task, republish its view and re-issue non-agent steps that were in flight."""
        latest = await asyncio.to_thread(self.store.load_latest)
        if latest is None:
            return
        self.state = latest
        await self._publish_view()
        if latest.terminal:
            return
        log.info("recovering_task", task_id=latest.task_id, phase=latest.phase, boot=latest.boot)
        if latest.current_job_id is not None and latest.current_agent is not None:
            self._arm_timer(latest.task_id, latest.current_job_id, latest.limits.job_timeout_s)
        for effect in machine.recovery_effects(latest):
            await self._run_effect(effect)

    # ================================================================= inputs

    async def _serve_cmd(self, data: bytes) -> BaseModel:
        try:
            cmd = CommandAdapter.validate_json(data)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            return CommandReply(ok=False, error=f"comando inválido ({where}): {first['msg']}")
        fut: asyncio.Future[CommandReply | None] = asyncio.get_running_loop().create_future()
        await self._inbox.put(_Item(CommandReceived(command=cmd, at=self.clock()), fut))
        try:
            reply = await asyncio.wait_for(fut, COMMAND_TIMEOUT_S)
        except TimeoutError:
            return CommandReply(ok=False, error="orquestrador não respondeu a tempo")
        return reply or CommandReply(ok=False, error="comando sem resposta")

    async def _serve_state(self, _data: bytes) -> BaseModel | None:
        return self.state.to_view() if self.state is not None else None

    async def _on_progress_msg(self, msg: Msg) -> None:
        try:
            env = Envelope.model_validate_json(msg.data)
            payload = env.decode_payload()
        except ValidationError:
            log.warning("invalid_progress_event", subject=msg.subject)
            return
        if isinstance(payload, AgentProgress):
            await self._inbox.put(_Item(AgentProgressed(env.task_id, payload, self.clock())))

    async def _consume_results(self, stop: asyncio.Event) -> None:
        """Pull loop on the ``orchestrator`` durable (``crew.evt.*.result|failed``).

        Own loop instead of ``Bus.consume``: nats-py ``fetch`` can raise a bare ``asyncio.TimeoutError``
        when idle, which ``Bus.consume`` does not catch (see docs/contract-requests.md).
        """
        psub = await self.bus.js.pull_subscribe_bind(durable=s.ORCHESTRATOR_DURABLE, stream=s.STREAM_EVENTS)
        try:
            while not stop.is_set():
                try:
                    msgs = await psub.fetch(10, timeout=1.0)
                except TimeoutError:  # also covers nats.errors.TimeoutError (a subclass)
                    continue
                for msg in msgs:
                    try:
                        await self._on_evt_msg(msg)
                    except Exception:
                        log.exception("result_handler_failed", subject=msg.subject)
                        await msg.nak(delay=5)
        finally:
            with contextlib.suppress(Exception):
                await psub.unsubscribe()

    async def _on_evt_msg(self, msg: Msg) -> None:
        """Durable consumer of ``crew.evt.*.result|failed``. Ack only after the event was processed."""
        try:
            env = Envelope.model_validate_json(msg.data)
            payload = env.decode_payload()
        except ValidationError:
            log.error("invalid_agent_event", subject=msg.subject)
            await msg.term()
            return
        event: Event
        if isinstance(payload, AgentResultEvt):
            event = AgentResult(env.task_id, payload, self.clock())
        elif isinstance(payload, AgentFailedEvt):
            event = AgentFailed(env.task_id, payload, self.clock())
        else:
            await msg.term()
            return
        fut: asyncio.Future[CommandReply | None] = asyncio.get_running_loop().create_future()
        await self._inbox.put(_Item(event, fut))
        await fut  # raises if processing failed -> bus.consume naks and redelivers
        await msg.ack()

    # ================================================================= worker

    async def _worker(self) -> None:
        while True:
            item = await self._inbox.get()
            try:
                reply = await self._handle(item.event)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("orchestrator_handle_failed", event=type(item.event).__name__)
                if item.reply is not None and not item.reply.done():
                    item.reply.set_exception(e)
                continue
            if item.reply is not None and not item.reply.done():
                item.reply.set_result(reply)

    async def _handle(self, event: Event) -> CommandReply | None:
        event = self._prepare(event)
        new_state, effects = machine.decide(self.state, event)

        rejects = [e for e in effects if isinstance(e, Reject)]
        if rejects:
            log.info("command_rejected", error=rejects[0].error)
            return CommandReply(ok=False, error=rejects[0].error)

        # persist FIRST: a command is only acknowledged once it is durable
        if any(isinstance(e, Persist) for e in effects) and new_state is not None:
            await asyncio.to_thread(self._persist, new_state, event)
        self.state = new_state
        self._after_event(event)

        reply = (
            CommandReply(ok=True, view=new_state.to_view())
            if isinstance(event, CommandReceived) and new_state is not None
            else None
        )
        for effect in effects:
            if not isinstance(effect, Persist):
                await self._run_effect(effect)
        return reply

    def _prepare(self, event: Event) -> Event:
        """Fill what only the shell knows: task id and repo context of a ``start_task``."""
        if isinstance(event, CommandReceived) and isinstance(event.command, StartTask):
            cmd = event.command
            if not self.cfg.has_repo(cmd.repo):
                return event
            lim = self.cfg.limits
            params = StartParams(
                task_id=self.store.next_task_id(),
                repo=self.cfg.repo_context(cmd.repo),
                limits=Limits(
                    max_test_attempts=lim.max_test_attempts,
                    max_review_rounds=lim.max_review_rounds,
                    budget_usd=lim.budget_usd_per_task,
                    job_timeout_s=lim.job_timeout_min * 60,
                ),
            )
            return dataclasses.replace(event, start=params)
        return event

    def _persist(self, state: TaskState, event: Event) -> None:
        self.store.save_task(state)
        kind, payload = _loggable(event)
        if kind is not None:
            self.store.log_event(state.task_id, kind, payload)

    def _after_event(self, event: Event) -> None:
        """Bookkeeping that does not depend on the decision: job rows and timers."""
        if isinstance(event, AgentResult):
            self._disarm_timer(str(event.evt.job_id))
            self.store.finish_job(str(event.evt.job_id), "done", event.evt.cost_usd)
        elif isinstance(event, AgentFailed) and not event.evt.retryable:
            self._disarm_timer(str(event.evt.job_id))
            self.store.finish_job(str(event.evt.job_id), "failed")

    # ================================================================= effects

    async def _run_effect(self, effect: Effect) -> None:
        match effect:
            case Persist() | Reject():
                pass
            case PublishView():
                await self._publish_view()
            case DispatchJob():
                await self._dispatch(effect)
            case CancelJobs():
                await self._cancel_jobs(effect)
            case CreateWorkspace():
                self._spawn(self._create_workspace(effect), f"create-workspace-{effect.task_id}")
            case BuildFinalReport():
                self._spawn(self._build_report(effect), f"final-report-{effect.task_id}")
            case LogStale():
                log.info(
                    "stale_event_ignored", task_id=effect.task_id, what=effect.what, job_id=str(effect.job_id)
                )

    async def _publish_view(self) -> None:
        if self.state is None:
            return
        await self.bus.publish_event(self.state.task_id, "view", self.state.to_view(), source="orchestrator")

    async def _dispatch(self, effect: DispatchJob) -> None:
        job = effect.job
        await asyncio.to_thread(self.store.record_job, job)
        try:
            await self.bus.publish_job(job)
        except Exception as e:  # NATS down: surface as a failed job so the user can retry from the UI
            log.exception("dispatch_failed", job_id=str(job.job_id))
            failed = AgentFailedEvt(
                agent=job.agent, job_id=job.job_id, error=f"falha ao publicar o job: {e}", retryable=False
            )
            await self._inbox.put(_Item(AgentFailed(job.task_id, failed, self.clock())))
            return
        limits = self.state.limits.job_timeout_s if self.state is not None else Limits().job_timeout_s
        self._arm_timer(job.task_id, job.job_id, limits)
        log.info(
            "job_dispatched",
            task_id=job.task_id,
            agent=job.agent,
            job_id=str(job.job_id),
            attempt=job.attempt,
        )

    async def _cancel_jobs(self, effect: CancelJobs) -> None:
        await self.bus.publish_core(s.cancel_subject(effect.task_id))
        if effect.agent is not None:
            # a job that was queued but never picked up must not run later
            with contextlib.suppress(Exception):
                await self.bus.js.purge_stream(s.STREAM_JOBS, subject=s.job_subject(effect.agent))
        for job in await asyncio.to_thread(self.store.jobs, effect.task_id):
            if job.status == "dispatched":
                self._disarm_timer(job.job_id)
                await asyncio.to_thread(self.store.finish_job, job.job_id, "cancelled")
        log.info("jobs_cancelled", task_id=effect.task_id, agent=effect.agent)

    # ----------------------------------------------------------------- background effects

    def _spawn(self, coro: Coroutine[Any, Any, None], name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _create_workspace(self, effect: CreateWorkspace) -> None:
        at = self.clock
        try:
            repo = self.cfg.repo(effect.repo)
            ws = await self.workspace.create(effect.task_id, repo)
            await self.workspace.prepare(ws, repo)  # sandbox + setup_cmd: fails before any agent
            event: Event = WorkspaceReady(effect.task_id, str(ws.path), ws.branch, at())
        except Exception as e:  # WorkspaceError and anything unexpected both fail the task cleanly
            log.warning("workspace_failed", task_id=effect.task_id, error=str(e))
            event = WorkspaceFailed(effect.task_id, str(e), at())
        await self._inbox.put(_Item(event))

    async def _build_report(self, effect: BuildFinalReport) -> None:
        at = self.clock
        try:
            ws = dataclasses.replace(
                self.workspace.locate(effect.task_id, self.cfg.repo(effect.repo)),
                path=Path(effect.workspace_path),
            )
            files = await self.workspace.diff_report(ws)
            event = ReportBuilt(effect.task_id, files, at())
        except Exception as e:
            log.warning("report_failed", task_id=effect.task_id, error=str(e))
            event = ReportBuilt(effect.task_id, [], at(), error=str(e))
        await self._inbox.put(_Item(event))

    # ----------------------------------------------------------------- job timeout

    def _arm_timer(self, task_id: str, job_id: UUID, seconds: float) -> None:
        key = str(job_id)
        self._disarm_timer(key)

        async def _fire() -> None:
            await asyncio.sleep(seconds)
            self._timers.pop(key, None)
            await self._inbox.put(_Item(JobTimedOut(task_id, job_id, self.clock())))

        self._timers[key] = asyncio.create_task(_fire(), name=f"job-timeout-{key[:8]}")

    def _disarm_timer(self, key: str) -> None:
        t = self._timers.pop(key, None)
        if t is not None:
            t.cancel()


# ===================================================================== helpers


def _log_task_end(task: asyncio.Task[None]) -> None:
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.error("orchestrator_task_died", task=task.get_name(), error=repr(exc))


def _loggable(event: Event) -> tuple[str | None, str]:
    """What goes into the append-only event log (progress is too chatty and is skipped)."""
    match event:
        case CommandReceived():
            return "command", event.command.model_dump_json()
        case AgentResult():
            return "result", event.evt.model_dump_json()
        case AgentFailed():
            return "failed", event.evt.model_dump_json()
        case JobTimedOut():
            return "timeout", json.dumps({"job_id": str(event.job_id)})
        case WorkspaceReady():
            return "workspace_ready", json.dumps({"path": event.path, "branch": event.branch})
        case WorkspaceFailed():
            return "boot_failed", json.dumps({"error": event.error})
        case ReportBuilt():
            return "report_built", json.dumps([f.model_dump() for f in event.files])
        case AgentProgressed():
            return None, ""

"""Orchestrator service: the I/O shell around ``machine.decide``.

All inputs (commands, agent results, progress, async effect completions) go through ONE inbox
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

import structlog
from nats.aio.msg import Msg
from pydantic import BaseModel, ValidationError

from .. import folders, projects, sandbox
from ..bus import Bus
from ..bus import subjects as s
from ..config import CrewConfig, RepoCfg
from ..contracts import (
    AccountUsage,
    AddRepo,
    AgentFailedEvt,
    AgentProgress,
    AgentResultEvt,
    CommandAdapter,
    CommandReply,
    CreateProject,
    Envelope,
    Plan,
    StartTask,
)
from ..estimate import agent_costs, estimate_plan, ratios
from ..usage import UsageReader
from ..workspace import git
from ..workspace.manager import Workspace, WorkspaceManager, run_host_setup
from . import machine
from .effects import (
    BuildFinalReport,
    CancelJobs,
    CreateEpicWorkspace,
    CreateWorkspace,
    DispatchJob,
    Effect,
    FinishMerge,
    LogStale,
    MergeEpic,
    Persist,
    PublishView,
    Reject,
    RemoveEpicWorkspace,
    RunSetup,
    SaveProjectSetup,
    WritePlanDoc,
)
from .events import (
    AgentFailed,
    AgentProgressed,
    AgentResult,
    CommandReceived,
    EpicMerged,
    EpicWorkspaceFailed,
    EpicWorkspaceReady,
    Event,
    ReportBuilt,
    SetupFinished,
    StartParams,
    WorkspaceFailed,
    WorkspaceReady,
)
from .state import Limits, TaskState
from .store import Store

log = structlog.get_logger(__name__)

COMMAND_TIMEOUT_S = 30.0
PROGRESS_VIEW_EVERY_S = 2.0
SAMPLE_MAX_AGE_S = 15.0  # calibration readings: close to the job that just ended, not older than this


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
        usage: UsageReader | None = None,
    ) -> None:
        self.bus = bus
        self.cfg = cfg
        self.store = store
        self.workspace = workspace
        self.clock = clock
        self.usage = usage  # None: no account usage (tests); the estimate then has no percentages
        self.state: TaskState | None = None
        self._inbox: asyncio.Queue[_Item] = asyncio.Queue()
        self._bg: set[asyncio.Task[None]] = set()
        self._git_lock = asyncio.Lock()  # worktree/commit/merge on one repo, one at a time
        self._last_view_at = 0.0

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
            pending = [*loops, *self._bg]
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
        if isinstance(event, CommandReceived) and isinstance(event.command, AddRepo):
            return await self._add_repo(event.command)
        if isinstance(event, CommandReceived) and isinstance(event.command, CreateProject):
            created = await self._create_project(event.command)
            if isinstance(created, CommandReply):
                return created
            event = dataclasses.replace(event, command=created)
        event = await self._enrich(self._prepare(event))
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
        if isinstance(event, AgentProgressed) and new_state is not None and new_state.split:
            # lanes have no live progress stream of their own in the UI: refresh their view, throttled
            now = asyncio.get_running_loop().time()
            if now - self._last_view_at >= PROGRESS_VIEW_EVERY_S:
                await self._publish_view()
        return reply

    async def _create_project(self, cmd: CreateProject) -> StartTask | CommandReply:
        """New project (D58): folder + ``git init`` + first commit, registered, then a normal task."""
        if self.state is not None and not self.state.terminal:
            return CommandReply(ok=False, error=machine.ERR_ACTIVE_TASK)
        if not cmd.title.strip():
            return CommandReply(ok=False, error=machine.ERR_TITLE_REQUIRED)
        try:
            name = projects.validate_name(cmd.name)
            if self.cfg.has_repo(name):
                raise projects.ProjectError(f"já existe um repositório chamado {name!r}")
            path = projects.project_path(self.cfg, name, cmd.parent_dir)
            await self.workspace.init_repo(path, projects.initial_files(name, cmd.title, cmd.description))
        except Exception as e:  # ProjectError, WorkspaceError, OSError: all shown to the user
            log.warning("create_project_failed", name=cmd.name, error=str(e))
            return CommandReply(ok=False, error=str(e))
        repo = projects.new_repo(name, path)
        await asyncio.to_thread(projects.register, repo)
        self.cfg.repos.append(repo)
        log.info("project_created", name=name, path=str(path))
        return StartTask(repo=name, title=cmd.title, description=cmd.description)

    async def _add_repo(self, cmd: AddRepo) -> CommandReply:
        """Register an existing local git repo. Validates everything first; the registry changes last."""
        try:
            repo = await self._validated_added_repo(cmd)
            await asyncio.to_thread(projects.register, repo)
            self.cfg.repos.append(repo)
        except Exception as e:  # ProjectError, FolderError, WorkspaceError, OSError: all shown to the user
            log.warning("add_repo_failed", name=cmd.name, path=cmd.path, error=str(e))
            return CommandReply(ok=False, error=str(e))
        log.info("repo_added", name=repo.name, path=str(repo.path))
        return CommandReply(ok=True, view=self.state.to_view() if self.state else None)

    async def _validated_added_repo(self, cmd: AddRepo) -> RepoCfg:
        name = projects.validate_name(cmd.name)
        if self.cfg.has_repo(name):
            raise projects.ProjectError(f"já existe um repositório chamado {name!r}")
        if not cmd.test_cmd.strip():
            raise projects.ProjectError("informe o comando de teste (test_cmd)")
        base = cmd.base_branch.strip()
        if not base or base.startswith("-"):
            raise projects.ProjectError(f"nome de branch base inválido: {cmd.base_branch!r}")
        path = folders.check_folder(cmd.path)
        if folders.is_registered_path(self.cfg, path):
            raise projects.ProjectError(f"a pasta {path} já está cadastrada como repositório")
        repo = projects.added_repo(cmd, path)

        probe = await folders.probe(str(path), self.cfg)
        if probe.git == "inside_repo":
            raise projects.ProjectError(
                f"a pasta {path} é uma subpasta de outro repositório git: escolha a pasta raiz do repositório"
            )
        if probe.git in ("none", "empty"):
            if not cmd.init_git:
                what = (
                    "a pasta não é um repositório git"
                    if probe.git == "none"
                    else "o repositório não tem nenhum commit"
                )
                raise projects.ProjectError(
                    f"{what}: use 'inicializar o git' para criar um commit inicial vazio"
                )
            if not await git.ok(path, "check-ref-format", "--branch", base):
                raise projects.ProjectError(f"nome de branch base inválido: {base!r}")
            await self.workspace.init_empty_commit(path, base)
        if not await git.ok(path, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"):
            raise projects.ProjectError(f"a branch base {base!r} não existe em {path}")
        return repo

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
                    max_test_attempts=lim.max_test_attempts, max_review_rounds=lim.max_review_rounds
                ),
            )
            return dataclasses.replace(event, start=params)
        return event

    async def _enrich(self, event: Event) -> Event:
        """Async data the machine needs but cannot fetch: the cost estimate of a fresh plan."""
        if isinstance(event, AgentResult) and isinstance(event.evt.output, Plan):
            try:
                usage_now = await self._sample_usage()
                rows, samples = await asyncio.to_thread(
                    lambda: (self.store.real_jobs(), self.store.usage_samples())
                )
                estimate = estimate_plan(event.evt.output, agent_costs(rows), ratios(samples), usage_now)
                return dataclasses.replace(event, estimate=estimate)
            except Exception:  # an estimate must never block the plan
                log.exception("estimate_failed")
        return event

    async def _sample_usage(self) -> AccountUsage | None:
        """Read the account usage and keep the reading for calibration (no-op without a reader)."""
        if self.usage is None:
            return None
        usage = await self.usage.read(max_age_s=SAMPLE_MAX_AGE_S)
        await asyncio.to_thread(self.store.record_usage, usage)
        return usage

    def _persist(self, state: TaskState, event: Event) -> None:
        self.store.save_task(state)
        kind, payload = _loggable(event)
        if kind is not None:
            self.store.log_event(state.task_id, kind, payload)

    def _after_event(self, event: Event) -> None:
        """Bookkeeping that does not depend on the decision: job rows, usage readings."""
        if isinstance(event, AgentResult | AgentFailed) and self.usage is not None:
            self._spawn(self._sample_quietly(), "usage-sample")
        if isinstance(event, AgentResult):
            self.store.finish_job(str(event.evt.job_id), "done", event.evt.cost_usd, event.evt.usage)
        elif isinstance(event, AgentFailed) and not event.evt.retryable:
            self.store.finish_job(str(event.evt.job_id), "limited" if event.evt.limit else "failed")

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
            case WritePlanDoc():
                self._spawn(self._write_plan_doc(effect), f"plan-doc-{effect.task_id}")
            case CreateEpicWorkspace():
                self._spawn(self._create_epic_workspace(effect), f"epic-workspace-{effect.epic_id}")
            case MergeEpic():
                self._spawn(self._merge_epic(effect), f"merge-{effect.epic_id}")
            case FinishMerge():
                self._spawn(self._finish_merge(effect), f"finish-merge-{effect.epic_id}")
            case RemoveEpicWorkspace():
                self._spawn(self._remove_epic_workspace(effect), f"remove-epic-{effect.epic_id}")
            case RunSetup():
                self._spawn(self._run_setup(effect), f"setup-{effect.epic_id or effect.task_id}")
            case SaveProjectSetup():
                await self._save_project_setup(effect)
            case LogStale():
                log.info(
                    "stale_event_ignored", task_id=effect.task_id, what=effect.what, job_id=str(effect.job_id)
                )

    async def _publish_view(self) -> None:
        if self.state is None:
            return
        self._last_view_at = asyncio.get_running_loop().time()
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
        log.info(
            "job_dispatched",
            task_id=job.task_id,
            agent=job.agent,
            job_id=str(job.job_id),
            attempt=job.attempt,
        )

    async def _cancel_jobs(self, effect: CancelJobs) -> None:
        await self.bus.publish_core(s.cancel_subject(effect.task_id))
        # a job that was queued but never picked up must not run later (one task at a time: safe)
        subjects = [s.job_subject(effect.agent)] if effect.agent is not None else [s.JOBS_WILDCARD]
        for subject in subjects:
            with contextlib.suppress(Exception):
                await self.bus.js.purge_stream(s.STREAM_JOBS, subject=subject)
        for job in await asyncio.to_thread(self.store.jobs, effect.task_id):
            if job.status == "dispatched":
                await asyncio.to_thread(self.store.finish_job, job.job_id, "cancelled")
        log.info("jobs_cancelled", task_id=effect.task_id, agent=effect.agent)

    async def _sample_quietly(self) -> None:
        try:
            await self._sample_usage()
        except Exception:
            log.warning("usage_sample_failed", exc_info=True)

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

    def _task_ws(self, task_id: str, repo: str, path: str) -> Workspace:
        return dataclasses.replace(self.workspace.locate(task_id, self.cfg.repo(repo)), path=Path(path))

    async def _build_report(self, effect: BuildFinalReport) -> None:
        at = self.clock
        doc: str | None = None
        try:
            ws = self._task_ws(effect.task_id, effect.repo, effect.workspace_path)
            if effect.plan_doc is not None:
                try:
                    async with self._git_lock:
                        doc = await self.workspace.write_plan_doc(
                            ws, effect.task_id, effect.plan_doc, commit=effect.commit_doc
                        )
                except Exception as e:  # the report matters more than the doc
                    log.warning("plan_doc_failed", task_id=effect.task_id, error=str(e))
            files = await self.workspace.diff_report(ws)
            event = ReportBuilt(effect.task_id, files, at(), plan_doc=doc)
        except Exception as e:
            log.warning("report_failed", task_id=effect.task_id, error=str(e))
            event = ReportBuilt(effect.task_id, [], at(), error=str(e), plan_doc=doc)
        await self._inbox.put(_Item(event))

    async def _write_plan_doc(self, effect: WritePlanDoc) -> None:
        try:
            ws = self._task_ws(effect.task_id, effect.repo, effect.workspace_path)
            async with self._git_lock:
                await self.workspace.write_plan_doc(ws, effect.task_id, effect.markdown, commit=effect.commit)
        except Exception as e:  # best effort: the plan is also in the task state
            log.warning("plan_doc_failed", task_id=effect.task_id, error=str(e))

    async def _create_epic_workspace(self, effect: CreateEpicWorkspace) -> None:
        at = self.clock
        try:
            repo = self.cfg.repo(effect.repo)
            task = self._task_ws(effect.task_id, effect.repo, effect.task_path)
            async with self._git_lock:
                ws = await self.workspace.create_epic(task, effect.epic_id)
            if effect.prepare:  # its own sandbox + setup, outside the git lock
                await self.workspace.prepare(ws, repo)
            event: Event = EpicWorkspaceReady(effect.task_id, effect.epic_id, str(ws.path), ws.branch, at())
        except Exception as e:
            log.warning("epic_workspace_failed", task_id=effect.task_id, epic=effect.epic_id, error=str(e))
            event = EpicWorkspaceFailed(effect.task_id, effect.epic_id, str(e), at())
        await self._inbox.put(_Item(event))

    async def _merge_epic(self, effect: MergeEpic) -> None:
        at = self.clock
        try:
            task = self._task_ws(effect.task_id, effect.repo, effect.task_path)
            epic = self.workspace.locate_epic(task, effect.epic_id)
            async with self._git_lock:
                await self.workspace.commit_all(epic, effect.commit_message)
                outcome = await self.workspace.merge(task, epic.branch, effect.merge_message)
            event: Event = EpicMerged(
                effect.task_id, effect.epic_id, at(), sha=outcome.sha, conflicts=outcome.conflicts
            )
        except Exception as e:
            log.warning("merge_failed", task_id=effect.task_id, epic=effect.epic_id, error=str(e))
            event = EpicMerged(effect.task_id, effect.epic_id, at(), error=str(e))
        await self._inbox.put(_Item(event))

    async def _finish_merge(self, effect: FinishMerge) -> None:
        at = self.clock
        try:
            task = self._task_ws(effect.task_id, effect.repo, effect.task_path)
            async with self._git_lock:
                sha = await self.workspace.finish_merge(task, effect.message)
            event: Event = EpicMerged(effect.task_id, effect.epic_id, at(), sha=sha)
        except Exception as e:
            log.warning("finish_merge_failed", task_id=effect.task_id, epic=effect.epic_id, error=str(e))
            event = EpicMerged(effect.task_id, effect.epic_id, at(), error=str(e))
        await self._inbox.put(_Item(event))

    async def _run_setup(self, effect: RunSetup) -> None:
        error: str | None = None
        try:
            await run_host_setup(Path(effect.path), effect.command)
        except Exception as e:
            log.warning("setup_failed", task_id=effect.task_id, epic=effect.epic_id, error=str(e))
            error = str(e)
        await self._inbox.put(_Item(SetupFinished(effect.task_id, effect.epic_id, self.clock(), error)))

    async def _save_project_setup(self, effect: SaveProjectSetup) -> None:
        """The commands the Planner decided become the project's (registry + this process' config)."""
        try:
            repo = projects.with_setup(self.cfg.repo(effect.repo), effect.setup)
            await asyncio.to_thread(projects.register, repo)
            self.cfg.repos[:] = [repo if r.name == repo.name else r for r in self.cfg.repos]
            log.info("project_setup_saved", repo=repo.name, stack=effect.setup.stack)
        except Exception as e:  # the task goes on; the commands can be fixed in repos.toml
            log.warning("project_setup_failed", repo=effect.repo, error=str(e))

    async def _remove_epic_workspace(self, effect: RemoveEpicWorkspace) -> None:
        try:
            repo = self.cfg.repo(effect.repo)
            task = self._task_ws(effect.task_id, effect.repo, effect.task_path)
            epic = self.workspace.locate_epic(task, effect.epic_id)
            async with self._git_lock:
                await self.workspace.remove_epic(epic)
            if repo.sandbox_image and sandbox.docker_available():
                await sandbox.remove(epic.task_id, repo.name, tuple(repo.deps_dirs))
        except Exception as e:  # leftovers are cleaned by `crew cleanup`
            log.warning("remove_epic_failed", task_id=effect.task_id, epic=effect.epic_id, error=str(e))


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
        case WorkspaceReady():
            return "workspace_ready", json.dumps({"path": event.path, "branch": event.branch})
        case WorkspaceFailed():
            return "boot_failed", json.dumps({"error": event.error})
        case ReportBuilt():
            return "report_built", json.dumps([f.model_dump() for f in event.files])
        case EpicWorkspaceReady():
            return "epic_workspace_ready", json.dumps({"epic": event.epic_id, "path": event.path})
        case EpicWorkspaceFailed():
            return "epic_workspace_failed", json.dumps({"epic": event.epic_id, "error": event.error})
        case EpicMerged():
            payload = {"epic": event.epic_id, "sha": event.sha, "conflicts": list(event.conflicts)}
            return "epic_merged", json.dumps({**payload, "error": event.error})
        case SetupFinished():
            return "setup_finished", json.dumps({"epic": event.epic_id, "error": event.error})
        case AgentProgressed():
            return None, ""

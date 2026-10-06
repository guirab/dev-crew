"""run_agent against a real nats-server: result, progress, cancellation, retry, failure."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from crew.agents.progress import ProgressLine, ProgressSink
from crew.agents.runner import RunOutcome
from crew.agents.service import run_agent
from crew.agents.settings import AgentRuntimeSettings
from crew.bus import Bus, FatalJobError, RetryableJobError
from crew.bus.subjects import cancel_subject
from crew.contracts import (
    AGENTS,
    AgentFailedEvt,
    AgentJob,
    AgentName,
    AgentProgress,
    AgentResultEvt,
    DevResult,
    Envelope,
    InterviewResult,
    Plan,
    ReviewResult,
    TestResult,
)

from .factories import make_job

pytestmark = pytest.mark.nats

OUTPUT_TYPES: dict[AgentName, type] = {
    "interviewer": InterviewResult,
    "planner": Plan,
    "developer": DevResult,
    "tester": TestResult,
    "reviewer": ReviewResult,
}


def fake_settings(**kw: Any) -> AgentRuntimeSettings:
    return AgentRuntimeSettings(model="fake", fake=True, fake_speed=1000.0, **kw)


@dataclass
class Worker:
    bus: Bus
    task: asyncio.Task[None]
    stop: asyncio.Event
    events: Any
    seen: list[Envelope] = field(default_factory=list)

    async def next_event(self, timeout: float = 10.0) -> Envelope:
        msg = await self.events.next_msg(timeout=timeout)
        env = Envelope.model_validate_json(msg.data)
        self.seen.append(env)
        return env

    async def until(self, *kinds: str, timeout: float = 10.0) -> Envelope:
        async with asyncio.timeout(timeout):
            while True:
                env = await self.next_event(timeout)
                if env.type in kinds:
                    return env

    async def shutdown(self) -> None:
        self.stop.set()
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(self.task, 5)


@contextlib.asynccontextmanager
async def started(
    bus: Bus,
    agent: AgentName,
    task_id: str,
    *,
    runner: Any = None,
    settings: AgentRuntimeSettings | None = None,
) -> AsyncIterator[Worker]:
    stop = asyncio.Event()
    events = await bus.js.subscribe(f"crew.evt.{task_id}.>", ordered_consumer=True)
    task = asyncio.create_task(
        run_agent(
            bus,
            agent,
            settings=settings or fake_settings(),
            stop=stop,
            runner=runner,
            heartbeat_s=0.5,
        )
    )
    worker = Worker(bus, task, stop, events)
    try:
        yield worker
    finally:
        await worker.shutdown()
        with contextlib.suppress(Exception):
            await events.unsubscribe()


@pytest.mark.parametrize("agent", AGENTS)
async def test_fake_agent_processes_a_job_and_publishes_the_result(bus: Bus, agent: AgentName) -> None:
    job = make_job(agent, task_id=f"T-{agent}")
    async with started(bus, agent, job.task_id) as worker:
        await bus.publish_job(job)
        first = await worker.next_event()
        assert (first.type, first.source) == ("progress", agent)
        assert first.decode_payload() == AgentProgress(
            agent=agent, job_id=job.job_id, kind="status", text="iniciando"
        )
        result_env = await worker.until("result")

    assert result_env.task_id == job.task_id
    assert result_env.source == agent
    payload = result_env.decode_payload()
    assert isinstance(payload, AgentResultEvt)
    assert payload.agent == agent
    assert payload.job_id == job.job_id
    assert isinstance(payload.output, OUTPUT_TYPES[agent])
    assert payload.cost_usd > 0
    assert payload.session_id and payload.session_id.startswith(f"fake-{agent}-")
    assert payload.duration_s >= 0
    tool_lines = [e for e in worker.seen if e.type == "progress" and e.payload["kind"] == "tool"]
    assert tool_lines, "the scripted agent reports intermediate progress"
    assert not [e for e in worker.seen if e.type == "failed"]


async def test_interviewer_uses_the_history_to_pick_the_question(bus: Bus) -> None:
    from .factories import make_turn

    job = make_job("interviewer", task_id="T-iv", history=[make_turn("a"), make_turn("b")])
    async with started(bus, "interviewer", job.task_id) as worker:
        await bus.publish_job(job)
        env = await worker.until("result")
    payload = env.decode_payload()
    assert isinstance(payload, AgentResultEvt)
    assert isinstance(payload.output, InterviewResult)
    assert payload.output.kind == "question"
    assert [q.topic for q in payload.output.questions] == ["Restrições"]


async def test_escalate_mode_still_publishes_a_result_not_a_failure(bus: Bus) -> None:
    job = make_job("tester", task_id="T-esc", attempt=3)
    async with started(bus, "tester", job.task_id, settings=fake_settings(fake_escalate=True)) as worker:
        await bus.publish_job(job)
        env = await worker.until("result", "failed")
    assert env.type == "result"
    payload = env.decode_payload()
    assert isinstance(payload, AgentResultEvt)
    assert isinstance(payload.output, TestResult)
    assert payload.output.ok is False


async def test_jobs_are_processed_one_at_a_time_in_order(bus: Bus) -> None:
    first = make_job("planner", task_id="T-q1")
    second = make_job("planner", task_id="T-q2")
    events = await bus.js.subscribe("crew.evt.*.result", ordered_consumer=True)
    stop = asyncio.Event()
    task = asyncio.create_task(run_agent(bus, "planner", settings=fake_settings(), stop=stop))
    try:
        await bus.publish_job(first)
        await bus.publish_job(second)
        got = []
        for _ in range(2):
            msg = await events.next_msg(timeout=10)
            got.append(Envelope.model_validate_json(msg.data).task_id)
        assert got == ["T-q1", "T-q2"]
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)
        await events.unsubscribe()


# ---------------------------------------------------------------------------------- cancellation
class HangRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def run(self, job: AgentJob, emit: ProgressSink) -> RunOutcome:
        await emit(ProgressLine("tool", "Lendo algo"))
        self.started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


async def test_cancel_message_aborts_the_job_and_publishes_failed(bus: Bus) -> None:
    job = make_job("developer", task_id="T-cancel")
    runner = HangRunner()
    async with started(bus, "developer", job.task_id, runner=runner) as worker:
        await bus.publish_job(job)
        await asyncio.wait_for(runner.started.wait(), 10)
        await bus.publish_core(cancel_subject(job.task_id))
        env = await worker.until("failed", "result")

    assert env.type == "failed"
    payload = env.decode_payload()
    assert isinstance(payload, AgentFailedEvt)
    assert payload.error == "cancelled"
    assert payload.retryable is False
    assert payload.job_id == job.job_id
    assert runner.cancelled


async def test_cancel_for_another_task_is_ignored(bus: Bus) -> None:
    job = make_job("planner", task_id="T-keep")
    async with started(bus, "planner", job.task_id) as worker:
        await bus.publish_core(cancel_subject("T-other"))
        await bus.publish_job(job)
        env = await worker.until("failed", "result")
    assert env.type == "result"


async def test_worker_keeps_serving_after_a_cancelled_job(bus: Bus) -> None:
    hang = make_job("planner", task_id="T-c1")
    runner = HangRunner()
    async with started(bus, "planner", "T-c1", runner=runner) as worker:
        await bus.publish_job(hang)
        await asyncio.wait_for(runner.started.wait(), 10)
        await bus.publish_core(cancel_subject("T-c1"))
        assert (await worker.until("failed")).type == "failed"
        # the same worker process still consumes the queue
        runner.started.clear()
        await bus.publish_job(make_job("planner", task_id="T-c1"))
        await asyncio.wait_for(runner.started.wait(), 10)


# ---------------------------------------------------------------------------------- errors
class ScriptedFailures:
    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def run(self, job: AgentJob, emit: ProgressSink) -> RunOutcome:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        plan = (await _fake_plan(job, emit)).output
        return RunOutcome(output=plan, cost_usd=0.01, session_id="s")


async def _fake_plan(job: AgentJob, emit: ProgressSink) -> RunOutcome:
    from crew.agents.fake import ScriptedRunner

    return await ScriptedRunner(fake_settings()).run(job, emit)


async def test_fatal_error_publishes_failed_without_retry(bus: Bus) -> None:
    job = make_job("planner", task_id="T-fatal")
    runner = ScriptedFailures(FatalJobError("orçamento máximo do job excedido"))
    async with started(bus, "planner", job.task_id, runner=runner) as worker:
        await bus.publish_job(job)
        env = await worker.until("failed", "result")
        await asyncio.sleep(0.5)
    payload = env.decode_payload()
    assert isinstance(payload, AgentFailedEvt)
    assert payload.error == "orçamento máximo do job excedido"
    assert payload.retryable is False
    assert runner.calls == 1


async def test_retryable_error_redelivers_and_eventually_succeeds(bus: Bus) -> None:
    job = make_job("planner", task_id="T-retry")
    runner = ScriptedFailures(RetryableJobError("429 rate limit", delay=0.3))
    async with started(bus, "planner", job.task_id, runner=runner) as worker:
        await bus.publish_job(job)
        env = await worker.until("failed", "result", timeout=15)
    assert env.type == "result"
    assert runner.calls == 2
    assert not [e for e in worker.seen if e.type == "failed"]


async def test_unexpected_crash_is_reported_as_failed(bus: Bus) -> None:
    job = make_job("planner", task_id="T-crash")
    runner = ScriptedFailures(RuntimeError("boom"))
    async with started(bus, "planner", job.task_id, runner=runner) as worker:
        await bus.publish_job(job)
        env = await worker.until("failed", "result")
    payload = env.decode_payload()
    assert isinstance(payload, AgentFailedEvt)
    assert "RuntimeError: boom" in payload.error


async def test_run_agent_returns_when_stop_is_set(bus: Bus) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(run_agent(bus, "reviewer", settings=fake_settings(), stop=stop))
    await asyncio.sleep(0.3)
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, 5)


async def test_standalone_module_worker_serves_a_job(bus: Bus, nats_url: str) -> None:
    """`python -m crew.agents planner` as a real process, configured only through the environment."""
    job = make_job("planner", task_id="T-proc")
    env = {**os.environ, "CREW_NATS_URL": nats_url, "CREW_FAKE_AGENTS": "1", "CREW_FAKE_SPEED": "1000"}
    events = await bus.js.subscribe("crew.evt.T-proc.>", ordered_consumer=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "crew.agents", "planner"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await bus.publish_job(job)
        async with asyncio.timeout(30):
            while True:
                msg = await events.next_msg(timeout=30)
                envelope = Envelope.model_validate_json(msg.data)
                if envelope.type == "result":
                    break
        payload = envelope.decode_payload()
        assert isinstance(payload, AgentResultEvt)
        assert isinstance(payload.output, Plan)
    finally:
        proc.terminate()
        await asyncio.to_thread(proc.wait, 10)
        await events.unsubscribe()


# ------------------------------------------------------------------ diff after the Tester (D42)
class TouchRunner:
    """A tester that edits ``rel`` (a test file or production code) and reports a passing run."""

    def __init__(self, rel: str) -> None:
        self.rel = rel

    async def run(self, job: Any, emit: ProgressSink) -> RunOutcome:
        from pathlib import Path

        target = Path(job.workspace_path) / self.rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("changed by the tester\n", "utf-8")
        return RunOutcome(
            output=TestResult(ok=True, passed=1, total=1, command="pytest"), cost_usd=0.0, session_id=None
        )


@pytest.mark.parametrize(("rel", "expected"), [("tests/test_new.py", "result"), ("src/app.py", "failed")])
async def test_tester_touching_production_code_fails_the_job(
    bus: Bus, tmp_path: Any, rel: str, expected: str
) -> None:
    from ..git_helpers import make_git_repo

    repo = make_git_repo(tmp_path / "repo")
    job = make_job("tester", task_id=f"T-pg{len(rel)}", workspace=repo)
    async with started(bus, "tester", job.task_id, runner=TouchRunner(rel)) as worker:
        await bus.publish_job(job)
        env = await worker.until("failed", "result")
    assert env.type == expected
    if expected == "failed":
        payload = env.decode_payload()
        assert isinstance(payload, AgentFailedEvt)
        assert "alterou código de produção: src/app.py" in payload.error and not payload.retryable

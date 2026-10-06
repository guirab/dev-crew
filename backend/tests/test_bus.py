from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from nats.aio.msg import Msg

from crew import contracts as c
from crew.bus import Bus, FatalJobError, JobControl, RetryableJobError, job_loop
from crew.bus import subjects as s

pytestmark = pytest.mark.nats


def _job(agent: c.AgentName = "planner") -> c.AgentJob:
    return c.AgentJob(
        job_id=uuid4(),
        task_id="T-1",
        agent=agent,
        attempt=1,
        repo=c.RepoContext(name="r", base_branch="main", test_cmd="pytest", test_globs=["tests/**"]),
        spec=c.TaskSpec(title="t", description="d", repo="r"),
        budget_usd=1.0,
    )


async def _collect_events(bus: Bus, kind: c.EventKind) -> asyncio.Queue[c.Envelope]:
    q: asyncio.Queue[c.Envelope] = asyncio.Queue()

    async def cb(msg: Msg) -> None:
        await q.put(c.Envelope.model_validate_json(msg.data))

    await bus.subscribe_core(s.evt_kind_wildcard(kind), cb)
    return q


async def _run_loop_until(bus: Bus, agent: c.AgentName, handler, done: asyncio.Event) -> None:  # type: ignore[no-untyped-def]
    stop = asyncio.Event()
    task = asyncio.create_task(job_loop(bus, agent, handler, stop=stop, fetch_timeout=0.2))
    await asyncio.wait_for(done.wait(), timeout=10)
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_ensure_streams_idempotent(bus: Bus) -> None:
    await bus.ensure_streams()
    info = await bus.js.stream_info(s.STREAM_JOBS)
    assert info.config.subjects == [s.JOBS_WILDCARD]


async def test_job_success_publishes_result(bus: Bus) -> None:
    results = await _collect_events(bus, "result")
    done = asyncio.Event()
    job = _job()

    async def handler(j: c.AgentJob, ctl: JobControl) -> None:
        assert ctl.delivery == 1
        plan = c.Plan(summary="s", steps=["a"], files=[], acceptance_criteria=[], test_strategy="t")
        await bus.publish_event(
            j.task_id, "result", c.AgentResultEvt(agent=j.agent, job_id=j.job_id, output=plan), source=j.agent
        )
        done.set()

    await bus.publish_job(job)
    await _run_loop_until(bus, "planner", handler, done)
    env = await asyncio.wait_for(results.get(), timeout=5)
    evt = env.decode_payload()
    assert isinstance(evt, c.AgentResultEvt) and evt.job_id == job.job_id
    info = await bus.js.stream_info(s.STREAM_JOBS)
    assert info.state.messages == 0  # acked → removed from work queue


async def test_job_fatal_publishes_failed(bus: Bus) -> None:
    failed = await _collect_events(bus, "failed")
    done = asyncio.Event()

    async def handler(j: c.AgentJob, ctl: JobControl) -> None:
        done.set()
        raise FatalJobError("boom")

    job = _job("reviewer")
    await bus.publish_job(job)
    await _run_loop_until(bus, "reviewer", handler, done)
    evt = (await asyncio.wait_for(failed.get(), timeout=5)).decode_payload()
    assert isinstance(evt, c.AgentFailedEvt) and evt.error == "boom" and not evt.retryable


async def test_job_retryable_is_redelivered(bus: Bus) -> None:
    done = asyncio.Event()
    deliveries: list[int] = []

    async def handler(j: c.AgentJob, ctl: JobControl) -> None:
        deliveries.append(ctl.delivery)
        if ctl.delivery == 1:
            raise RetryableJobError("rate limited", delay=0.2)
        done.set()

    await bus.publish_job(_job("tester"))
    await _run_loop_until(bus, "tester", handler, done)
    assert deliveries == [1, 2]


async def test_duplicate_job_is_deduped(bus: Bus) -> None:
    job = _job("developer")
    await bus.publish_job(job)
    await bus.publish_job(job)
    info = await bus.js.stream_info(s.STREAM_JOBS)
    assert info.state.messages == 1


async def test_request_reply(bus: Bus) -> None:
    async def handler(body: bytes) -> c.CommandReply:
        cmd = c.CommandAdapter.validate_json(body)
        return c.CommandReply(ok=isinstance(cmd, c.ApprovePlan))

    await bus.serve(s.CMD, handler)
    reply = await bus.request(s.CMD, c.ApprovePlan(), c.CommandReply)
    assert reply.ok


async def test_job_loop_survives_idle_timeouts(bus: Bus) -> None:
    done = asyncio.Event()

    async def handler(j: c.AgentJob, ctl: JobControl) -> None:
        done.set()

    stop = asyncio.Event()
    task = asyncio.create_task(job_loop(bus, "interviewer", handler, stop=stop, fetch_timeout=0.1))
    await asyncio.sleep(1.0)  # ~10 empty fetches
    assert not task.done(), "job_loop died while idle"
    await bus.publish_job(_job("interviewer"))
    await asyncio.wait_for(done.wait(), timeout=10)
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_request_without_responders_raises_bus_error(bus: Bus) -> None:
    from crew.bus import BusError

    with pytest.raises(BusError):
        await bus.request("crew.nobody.home", c.ApprovePlan(), c.CommandReply, timeout=1)

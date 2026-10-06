"""Job loop shared by every agent worker: fetch, heartbeat, ack/nak/term, failure events."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from nats.aio.msg import Msg
from nats.errors import TimeoutError as NatsTimeoutError
from pydantic import ValidationError

from ..contracts import AgentFailedEvt, AgentJob, AgentName
from . import subjects as s
from .client import JOB_MAX_DELIVER, Bus

log = structlog.get_logger(__name__)


class RetryableJobError(Exception):
    """Transient failure (rate limit, network). The job is redelivered after ``delay`` seconds."""

    def __init__(self, message: str, delay: float = 30.0) -> None:
        super().__init__(message)
        self.delay = delay


class FatalJobError(Exception):
    """Permanent failure. A ``failed`` event is published and the job is terminated."""


JOB_BUDGET_EXCEEDED = "orçamento máximo do job excedido"
"""``failed`` error of a job stopped by its budget cap (the remaining task budget): the orchestrator
escalates it as ``budget`` so ``more_attempts`` can raise the task budget."""


@dataclass(frozen=True)
class JobControl:
    msg: Msg
    delivery: int  # 1-based delivery count for this job


JobHandler = Callable[[AgentJob, JobControl], Awaitable[None]]


async def _heartbeat(msg: Msg, every_s: float) -> None:
    while True:
        await asyncio.sleep(every_s)
        with contextlib.suppress(Exception):
            await msg.in_progress()


async def _publish_failed(bus: Bus, job: AgentJob, error: str, retryable: bool) -> None:
    evt = AgentFailedEvt(agent=job.agent, job_id=job.job_id, error=error, retryable=retryable)
    await bus.publish_event(job.task_id, "failed", evt, source=job.agent)


async def handle_job_message(
    bus: Bus, agent: AgentName, msg: Msg, handler: JobHandler, heartbeat_s: float = 30.0
) -> None:
    """Process one job message. The handler publishes its own ``result`` event on success."""
    try:
        job = AgentJob.model_validate_json(msg.data)
    except ValidationError:
        log.error("invalid_job_payload", agent=agent)
        await msg.term()
        return

    delivery = msg.metadata.num_delivered if msg.metadata else 1
    bound = log.bind(agent=agent, task_id=job.task_id, job_id=str(job.job_id), delivery=delivery)
    hb = asyncio.create_task(_heartbeat(msg, heartbeat_s))
    try:
        await handler(job, JobControl(msg=msg, delivery=delivery))
        await msg.ack()
        bound.info("job_done")
    except RetryableJobError as e:
        if delivery >= JOB_MAX_DELIVER:
            bound.warning("job_retry_exhausted", error=str(e))
            await _publish_failed(bus, job, f"retries exhausted: {e}", retryable=False)
            await msg.term()
        else:
            bound.warning("job_retry", error=str(e), delay=e.delay)
            await msg.nak(delay=e.delay)
    except FatalJobError as e:
        bound.error("job_fatal", error=str(e))
        await _publish_failed(bus, job, str(e), retryable=False)
        await msg.term()
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await msg.nak(delay=1)
        raise
    except Exception as e:
        bound.exception("job_crashed")
        await _publish_failed(bus, job, f"{type(e).__name__}: {e}", retryable=False)
        await msg.term()
    finally:
        hb.cancel()


async def job_loop(
    bus: Bus,
    agent: AgentName,
    handler: JobHandler,
    *,
    stop: asyncio.Event | None = None,
    heartbeat_s: float = 30.0,
    fetch_timeout: float = 1.0,
) -> None:
    """Consume ``crew.job.<agent>`` one job at a time until ``stop`` is set."""
    psub = await bus.js.pull_subscribe_bind(durable=s.agent_durable(agent), stream=s.STREAM_JOBS)
    log.info("job_loop_started", agent=agent)
    try:
        while stop is None or not stop.is_set():
            try:
                msgs = await psub.fetch(1, timeout=fetch_timeout)
            except (NatsTimeoutError, TimeoutError):  # nats-py may raise a bare asyncio.TimeoutError
                continue
            for m in msgs:
                await handle_job_message(bus, agent, m, handler, heartbeat_s)
    finally:
        with contextlib.suppress(Exception):
            await psub.unsubscribe()

"""Thin typed wrapper over nats-py (classic JetStream API)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import nats
import structlog
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg
from nats.errors import NoRespondersError
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js import JetStreamContext
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, RetentionPolicy, StreamConfig
from nats.js.errors import NotFoundError
from pydantic import BaseModel

from ..contracts import AGENTS, AgentJob, Contract, Envelope, EventKind, EventSource
from . import subjects as s

log = structlog.get_logger(__name__)

M = TypeVar("M", bound=BaseModel)

JOB_ACK_WAIT_S = 120.0
JOB_MAX_DELIVER = 3
JOB_BACKOFF_S = [10.0, 60.0]
EVENTS_MAX_AGE_S = 7 * 24 * 3600
EVENTS_MAX_BYTES = 512 * 1024 * 1024
DUPLICATE_WINDOW_S = 120.0


class BusError(RuntimeError):
    pass


class Bus:
    """Connection + JetStream context with typed helpers."""

    def __init__(self, nc: NATS, js: JetStreamContext) -> None:
        self.nc = nc
        self.js = js

    @classmethod
    async def connect(cls, url: str = "nats://127.0.0.1:4222", name: str = "crew") -> Bus:
        nc = await nats.connect(url, name=name, max_reconnect_attempts=-1, reconnect_time_wait=1)
        return cls(nc, nc.jetstream())

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.nc.drain()

    # ---------- setup ----------
    async def ensure_streams(self) -> None:
        """Create/update streams and durable consumers. Idempotent."""
        await self._upsert_stream(
            StreamConfig(
                name=s.STREAM_JOBS,
                subjects=[s.JOBS_WILDCARD],
                retention=RetentionPolicy.WORK_QUEUE,
                duplicate_window=DUPLICATE_WINDOW_S,
            )
        )
        await self._upsert_stream(
            StreamConfig(
                name=s.STREAM_EVENTS,
                subjects=[s.EVENTS_WILDCARD],
                retention=RetentionPolicy.LIMITS,
                max_age=EVENTS_MAX_AGE_S,
                max_bytes=EVENTS_MAX_BYTES,
                duplicate_window=DUPLICATE_WINDOW_S,
            )
        )
        for agent in AGENTS:
            await self.js.add_consumer(
                s.STREAM_JOBS,
                ConsumerConfig(
                    durable_name=s.agent_durable(agent),
                    filter_subject=s.job_subject(agent),
                    ack_policy=AckPolicy.EXPLICIT,
                    ack_wait=JOB_ACK_WAIT_S,
                    max_deliver=JOB_MAX_DELIVER,
                    backoff=JOB_BACKOFF_S,
                ),
            )
        await self.js.add_consumer(
            s.STREAM_EVENTS,
            ConsumerConfig(
                durable_name=s.ORCHESTRATOR_DURABLE,
                filter_subjects=[s.evt_kind_wildcard("result"), s.evt_kind_wildcard("failed")],
                ack_policy=AckPolicy.EXPLICIT,
                deliver_policy=DeliverPolicy.NEW,
                ack_wait=30.0,
            ),
        )

    async def _upsert_stream(self, cfg: StreamConfig) -> None:
        try:
            await self.js.stream_info(cfg.name or "")
            await self.js.update_stream(cfg)
        except NotFoundError:
            await self.js.add_stream(cfg)

    # ---------- publish ----------
    async def publish_job(self, job: AgentJob) -> None:
        await self.js.publish(
            s.job_subject(job.agent),
            job.model_dump_json().encode(),
            headers={"Nats-Msg-Id": str(job.job_id)},
        )

    async def publish_event(
        self, task_id: str, kind: EventKind, payload: Contract, source: EventSource
    ) -> Envelope:
        env = Envelope.wrap(task_id, kind, payload, source)
        await self.js.publish(
            s.evt_subject(task_id, kind),
            env.model_dump_json().encode(),
            headers={"Nats-Msg-Id": str(env.id)},
        )
        return env

    async def publish_core(self, subject: str, data: bytes = b"") -> None:
        await self.nc.publish(subject, data)

    # ---------- request / reply ----------
    async def request(
        self, subject: str, req: BaseModel | None, reply_model: type[M], timeout: float = 5.0
    ) -> M:
        data = req.model_dump_json().encode() if req is not None else b"{}"
        try:
            msg = await self.nc.request(subject, data, timeout=timeout)
        except (NatsTimeoutError, TimeoutError) as e:
            raise BusError(f"no reply on {subject} within {timeout}s") from e
        except NoRespondersError as e:
            raise BusError(f"no responders on {subject}") from e
        return reply_model.model_validate_json(msg.data)

    async def request_raw(self, subject: str, data: bytes = b"{}", timeout: float = 5.0) -> bytes:
        try:
            msg = await self.nc.request(subject, data, timeout=timeout)
        except (NatsTimeoutError, TimeoutError) as e:
            raise BusError(f"no reply on {subject} within {timeout}s") from e
        except NoRespondersError as e:
            raise BusError(f"no responders on {subject}") from e
        return bytes(msg.data)

    async def serve(
        self,
        subject: str,
        handler: Callable[[bytes], Awaitable[BaseModel | bytes | None]],
        queue: str = "",
    ) -> Any:
        """Answer core requests. Handler gets the raw body and returns a model, raw bytes or None."""

        async def _cb(msg: Msg) -> None:
            try:
                out = await handler(msg.data)
                body = (
                    b"null"
                    if out is None
                    else out
                    if isinstance(out, bytes)
                    else out.model_dump_json().encode()
                )
            except Exception as e:  # reply with an error object instead of letting the caller time out
                log.exception("serve_handler_failed", subject=subject)
                body = json.dumps({"ok": False, "error": str(e)}).encode()
            if msg.reply:
                await msg.respond(body)

        return await self.nc.subscribe(subject, queue=queue, cb=_cb)

    # ---------- subscribe ----------
    async def subscribe_core(self, subject: str, cb: Callable[[Msg], Awaitable[None]]) -> Any:
        return await self.nc.subscribe(subject, cb=cb)

    async def consume(
        self,
        stream: str,
        durable: str,
        handler: Callable[[Msg], Awaitable[None]],
        *,
        stop: asyncio.Event | None = None,
        batch: int = 10,
        fetch_timeout: float = 1.0,
    ) -> None:
        """Pull loop on an existing durable. Handler must ack/nak/term each message."""
        psub = await self.js.pull_subscribe_bind(durable=durable, stream=stream)
        try:
            while stop is None or not stop.is_set():
                try:
                    msgs = await psub.fetch(batch, timeout=fetch_timeout)
                except (NatsTimeoutError, TimeoutError):
                    continue
                for m in msgs:
                    try:
                        await handler(m)
                    except Exception:
                        log.exception("consume_handler_failed", durable=durable, subject=m.subject)
                        await m.nak(delay=5)
        finally:
            with contextlib.suppress(Exception):
                await psub.unsubscribe()

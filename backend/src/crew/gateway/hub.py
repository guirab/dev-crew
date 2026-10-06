"""WebSocket hub: fan-out of ``view``/``progress`` events from the bus to the browsers.

The hub keeps the latest ``TaskView`` it has seen. A new socket gets that snapshot first, then live
messages, with no await in between, so a client can neither miss nor reorder an update.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from nats.aio.msg import Msg
from nats.errors import NoRespondersError
from pydantic import TypeAdapter, ValidationError

from ..bus import Bus, BusError
from ..bus import subjects as s
from ..contracts import AgentProgress, Envelope, TaskView, WsProgress, WsView

log = structlog.get_logger(__name__)

QUEUE_SIZE = 256
VIEW_OR_NONE: TypeAdapter[TaskView | None] = TypeAdapter(TaskView | None)


class _Client:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_SIZE)


class Hub:
    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.latest: TaskView | None = None
        self.primed = False
        self._clients: set[_Client] = set()
        self._subs: list[Any] = []

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self._subs = [
            await self.bus.subscribe_core(s.evt_kind_wildcard("view"), self._on_view),
            await self.bus.subscribe_core(s.evt_kind_wildcard("progress"), self._on_progress),
        ]

    async def stop(self) -> None:
        for sub in self._subs:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        self._subs = []
        for c in list(self._clients):
            with contextlib.suppress(Exception):
                await c.ws.close(code=1001)
        self._clients.clear()

    async def prime(self) -> None:
        """Ask the orchestrator for the current view (once; afterwards the stream keeps us current)."""
        if self.primed:
            return
        try:
            raw = await self.bus.request_raw(s.STATE_CURRENT, timeout=2.0)
            self.latest = VIEW_OR_NONE.validate_json(raw)
            self.primed = True
        except (BusError, NoRespondersError, ValidationError):
            log.info("hub_prime_skipped")  # orchestrator not up yet: its boot republishes the view

    # ------------------------------------------------------------------ bus -> clients

    async def _on_view(self, msg: Msg) -> None:
        try:
            view = TaskView.model_validate(Envelope.model_validate_json(msg.data).payload)
        except ValidationError:
            log.warning("invalid_view_event")
            return
        self.latest = view
        self.primed = True
        self._broadcast(WsView(data=view).model_dump_json())

    async def _on_progress(self, msg: Msg) -> None:
        try:
            env = Envelope.model_validate_json(msg.data)
            data = AgentProgress.model_validate(env.payload)
        except ValidationError:
            log.warning("invalid_progress_event")
            return
        self._broadcast(WsProgress(task_id=env.task_id, data=data).model_dump_json())

    def _broadcast(self, payload: str) -> None:
        for client in list(self._clients):
            self._offer(client, payload)

    def _offer(self, client: _Client, payload: str) -> None:
        try:
            client.queue.put_nowait(payload)
        except asyncio.QueueFull:
            # slow consumer: drop the backlog and resync from the latest snapshot
            while not client.queue.empty():
                client.queue.get_nowait()
            client.queue.put_nowait(WsView(data=self.latest).model_dump_json())

    # ------------------------------------------------------------------ one socket

    async def serve_socket(self, ws: WebSocket) -> None:
        """Accept ``ws`` and pump messages until it disconnects. Client messages are ignored."""
        await ws.accept()
        await self.prime()
        client = _Client(ws)
        client.queue.put_nowait(WsView(data=self.latest).model_dump_json())  # snapshot first...
        self._clients.add(client)  # ...then live updates (no await between the two)
        sender = asyncio.create_task(self._pump(client), name="ws-pump")
        try:
            while True:
                await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):  # RuntimeError: socket closed under us (hub.stop)
            pass
        finally:
            self._clients.discard(client)
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender

    async def _pump(self, client: _Client) -> None:
        try:
            while True:
                await client.ws.send_text(await client.queue.get())
        except (WebSocketDisconnect, RuntimeError):
            return  # socket already closed

    @property
    def client_count(self) -> int:
        return len(self._clients)

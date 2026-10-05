"""Gateway: REST + WebSocket in front of the NATS bus, for the UI. Loopback only, no auth by design.

Hardening (the UI is a local app, but a browser is a confused deputy):
- binds 127.0.0.1 (enforced in config);
- ``Host`` allow-list (DNS rebinding) and ``Origin`` check on the WebSocket and on commands (CSRF / CSWSH);
- CORS only for the Vite dev origin;
- every error is a short pt-BR message, never a stack trace.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from nats.errors import NoRespondersError
from pydantic import TypeAdapter, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..bus import Bus, BusError
from ..bus import subjects as s
from ..config import CrewConfig
from ..contracts import Command, CommandReply, RepoInfo, TaskView
from ..orchestrator.machine import CONFLICT_ERRORS
from .hub import Hub

log = structlog.get_logger(__name__)

DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
COMMAND_TIMEOUT_S = 40.0

_VIEW_OR_NONE: TypeAdapter[TaskView | None] = TypeAdapter(TaskView | None)

DEFAULT_DIST = Path(__file__).resolve().parents[4] / "frontend" / "dist"


def allowed_origins(host: str, port: int) -> frozenset[str]:
    own = {f"http://{h}:{port}" for h in ("localhost", "127.0.0.1", host)}
    return frozenset({*DEV_ORIGINS, *own})


def _unavailable(what: str) -> HTTPException:
    return HTTPException(status_code=503, detail=f"{what} indisponível: nenhum serviço respondeu")


class Gateway:
    def __init__(self, bus: Bus, cfg: CrewConfig, *, dist: Path | None = DEFAULT_DIST) -> None:
        self.bus = bus
        self.cfg = cfg
        self.hub = Hub(bus)
        self.origins = allowed_origins(cfg.gateway.host, cfg.gateway.port)
        self.app = self._build_app(dist)

    # ------------------------------------------------------------------ app

    def _build_app(self, dist: Path | None) -> FastAPI:
        app = FastAPI(title="dev-crew gateway", docs_url=None, redoc_url=None, openapi_url=None)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(DEV_ORIGINS),
            allow_methods=["GET", "POST"],
            allow_headers=["content-type"],
        )
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

        @app.middleware("http")
        async def security_headers(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            response.headers.setdefault("X-Frame-Options", "DENY")
            return response

        def same_origin(request: Request) -> None:
            origin = request.headers.get("origin")
            if origin is not None and origin not in self.origins:
                raise HTTPException(status_code=403, detail="origem não permitida")

        @app.get("/api/repos")
        async def repos() -> list[RepoInfo]:
            return self.cfg.repo_infos()

        @app.get("/api/task")
        async def task() -> Response:
            try:
                raw = await self.bus.request_raw(s.STATE_CURRENT, timeout=5.0)
            except (BusError, NoRespondersError):
                raise _unavailable("Orquestrador") from None
            try:
                view = _VIEW_OR_NONE.validate_json(raw)
            except ValidationError:
                raise HTTPException(status_code=502, detail="resposta inválida do orquestrador") from None
            return Response(_VIEW_OR_NONE.dump_json(view), media_type="application/json")

        @app.post("/api/commands", dependencies=[Depends(same_origin)])
        async def commands(command: Command) -> JSONResponse:
            try:
                reply = await self.bus.request(s.CMD, command, CommandReply, timeout=COMMAND_TIMEOUT_S)
            except (BusError, NoRespondersError):
                raise _unavailable("Orquestrador") from None
            except ValidationError:
                raise HTTPException(status_code=502, detail="resposta inválida do orquestrador") from None
            status = 200 if reply.ok else (409 if reply.error in CONFLICT_ERRORS else 422)
            return JSONResponse(reply.model_dump(mode="json"), status_code=status)

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket) -> None:
            origin = ws.headers.get("origin")
            if origin is not None and origin not in self.origins:
                await ws.close(code=1008)  # policy violation: cross-site WebSocket hijacking attempt
                return
            await self.hub.serve_socket(ws)

        if dist is not None and dist.is_dir():
            # last, so /api and /ws win; html=True serves index.html for "/"
            app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
        return app

    # ------------------------------------------------------------------ run

    async def run(self, stop: asyncio.Event) -> None:
        """Serve HTTP/WS on ``cfg.gateway`` until ``stop`` is set."""
        await self.hub.start()
        server = _EmbeddedServer(
            uvicorn.Config(
                self.app,
                host=self.cfg.gateway.host,
                port=self.cfg.gateway.port,
                log_level="warning",
                access_log=False,
            )
        )
        serve = asyncio.create_task(server.serve(), name="gateway-uvicorn")
        log.info("gateway_started", host=self.cfg.gateway.host, port=self.cfg.gateway.port)
        try:
            await stop.wait()
        finally:
            server.should_exit = True
            await self.hub.stop()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(serve, 10)
            log.info("gateway_stopped")


class _EmbeddedServer(uvicorn.Server):
    """uvicorn without its own signal handlers: the CLI owns Ctrl+C for the whole process."""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[no-untyped-def]
        yield

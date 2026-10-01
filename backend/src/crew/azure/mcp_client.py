"""MCP client for the official ``@azure-devops/mcp`` server (stdio), read-only.

One long-lived session (the first ``npx`` spawn is slow), reconnect when it dies. Every call goes through
an allow-list: only the read tools/actions below can ever be sent. Write tools are not callable from here.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import Any, Protocol

import structlog
from mcp import Client, StdioServerParameters

from ..config import AzureCfg
from .mapping import AzureMappingError, parse_tool_text

log = structlog.get_logger(__name__)

STARTUP_TIMEOUT_S = 120.0
CALL_TIMEOUT_S = 60.0

# tool -> actions we are allowed to call. Anything else is refused before leaving the process.
READ_ONLY_ACTIONS: dict[str, frozenset[str]] = {
    "work": frozenset({"list_team_iterations"}),
    "wit_work_item": frozenset({"get", "get_batch", "list_for_iteration"}),
    "wit_query": frozenset({"wiql"}),
}


class AzureError(RuntimeError):
    """Azure intake failed. The message is user-facing (pt-BR)."""


class ReadOnlyViolation(AzureError):
    """Someone tried to call a tool/action that is not on the read-only allow-list."""


class ToolCaller(Protocol):
    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        """Call a read-only tool and return the parsed JSON payload."""
        ...

    async def close(self) -> None: ...


def ensure_read_only(tool: str, arguments: dict[str, Any]) -> None:
    if tool.endswith("_write") or "write" in tool.lower():
        raise ReadOnlyViolation(f"tool de escrita bloqueada: {tool}")
    actions = READ_ONLY_ACTIONS.get(tool)
    if actions is None:
        raise ReadOnlyViolation(f"tool fora da allow-list de leitura: {tool}")
    action = arguments.get("action")
    if action not in actions:
        raise ReadOnlyViolation(f"action {action!r} não permitida em {tool} (permitidas: {sorted(actions)})")


def build_server_params(cfg: AzureCfg, pat_b64: str | None) -> StdioServerParameters:
    """``npx -y @azure-devops/mcp@<ver> <org> -d core work work-items -a <auth>`` (``npx.cmd`` on Windows)."""
    if cfg.auth == "pat" and not pat_b64:
        raise AzureError(
            "AZURE_DEVOPS_PAT_B64 não configurado (base64 de 'email:pat', escopo Work Items: Read)"
        )
    env = {"ado_mcp_project": cfg.project, "ado_mcp_team": cfg.team}
    if cfg.auth == "pat" and pat_b64:
        env["PERSONAL_ACCESS_TOKEN"] = pat_b64
    return StdioServerParameters(
        command="npx.cmd" if sys.platform == "win32" else "npx",
        args=[
            "-y",
            f"@azure-devops/mcp@{cfg.mcp_version}",
            cfg.organization,
            "-d",
            "core",
            "work",
            "work-items",
            "-a",
            cfg.auth,
        ],
        env=env,
    )


class McpToolCaller:
    """One ``mcp.Client`` session kept alive in its own task (anyio scopes must exit where they enter)."""

    def __init__(
        self,
        params: StdioServerParameters,
        *,
        startup_timeout: float = STARTUP_TIMEOUT_S,
        call_timeout: float = CALL_TIMEOUT_S,
    ) -> None:
        self._params = params
        self._startup_timeout = startup_timeout
        self._call_timeout = call_timeout
        self._lock = asyncio.Lock()
        self._runner: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._client: Client | None = None

    async def call(self, tool: str, arguments: dict[str, Any]) -> Any:
        ensure_read_only(tool, arguments)
        last: Exception | None = None
        for attempt in (1, 2):  # second attempt = fresh session (server died / npx hiccup)
            try:
                client = await self._session()
                result = await asyncio.wait_for(
                    client.call_tool(tool, arguments, read_timeout_seconds=self._call_timeout),
                    timeout=self._call_timeout + 5,
                )
            except Exception as e:  # any transport failure: retry once with a fresh session
                last = e
                log.warning("azure_mcp_call_failed", tool=tool, attempt=attempt, error=repr(e)[:200])
                await self._reset()
                continue
            return _payload(result)
        raise AzureError(f"Azure MCP indisponível: {last}") from last

    async def _session(self) -> Client:
        async with self._lock:
            if self._client is not None and self._runner is not None and not self._runner.done():
                return self._client
            await self._reset_unlocked()
            ready: asyncio.Future[Client] = asyncio.get_running_loop().create_future()
            self._stop = asyncio.Event()
            self._runner = asyncio.create_task(self._run(ready, self._stop), name="azure-mcp-session")
            try:
                self._client = await asyncio.wait_for(ready, self._startup_timeout)
            except Exception:
                await self._reset_unlocked()
                raise
            log.info("azure_mcp_connected")
            return self._client

    async def _run(self, ready: asyncio.Future[Client], stop: asyncio.Event) -> None:
        try:
            async with Client(self._params) as client:
                if not ready.done():
                    ready.set_result(client)
                await stop.wait()
        except BaseException as e:
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError(repr(e)))
            if not isinstance(e, Exception):
                raise

    async def _reset(self) -> None:
        async with self._lock:
            await self._reset_unlocked()

    async def _reset_unlocked(self) -> None:
        self._client = None
        runner, self._runner = self._runner, None
        self._stop.set()
        if runner is not None and not runner.done():
            try:
                await asyncio.wait_for(asyncio.shield(runner), 10)
            except Exception:
                runner.cancel()
                with contextlib.suppress(BaseException):
                    await runner

    async def close(self) -> None:
        await self._reset()


def _payload(result: Any) -> Any:
    """``CallToolResult`` -> parsed JSON (``content[0].text`` is a JSON string, possibly fenced)."""
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    if result.is_error:
        raise AzureError(f"Azure MCP retornou erro: {(texts[0] if texts else '')[:300]}")
    if not texts:
        raise AzureMappingError("resposta do MCP sem conteúdo de texto")
    return parse_tool_text(texts[0])

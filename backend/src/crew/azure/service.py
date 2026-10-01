"""Azure intake: backends (real MCP / fake) and the NATS service that answers ``crew.azure.*``."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Protocol

import structlog
from pydantic import TypeAdapter, ValidationError

from ..bus import Bus
from ..bus import subjects as s
from ..config import AzureCfg
from ..contracts import WorkItemDetail, WorkItemSummary
from .mapping import (
    SUMMARY_FIELDS,
    AzureMappingError,
    detail_from_tool_data,
    ids_from_wiql,
    summaries,
)
from .mcp_client import AzureError, ToolCaller

log = structlog.get_logger(__name__)

MAX_LIST = 50
WIQL_MY_CURRENT_SPRINT = (
    "SELECT [System.Id] FROM WorkItems "
    "WHERE [System.IterationPath] = @CurrentIteration AND [System.AssignedTo] = @Me "
    "ORDER BY [System.ChangedDate] DESC"
)
_SUMMARIES = TypeAdapter(list[WorkItemSummary])


class AzureBackend(Protocol):
    async def list_work_items(self) -> list[WorkItemSummary]: ...
    async def get_work_item(self, work_item_id: int) -> WorkItemDetail: ...
    async def close(self) -> None: ...


class McpAzureBackend:
    """Read-only intake through the Azure DevOps MCP server (tools of the 2.x consolidated API)."""

    def __init__(self, caller: ToolCaller, cfg: AzureCfg) -> None:
        self.caller = caller
        self.cfg = cfg

    async def list_work_items(self) -> list[WorkItemSummary]:
        project, team = self.cfg.project, self.cfg.team
        wiql = await self.caller.call(
            "wit_query", {"action": "wiql", "project": project, "team": team, "wiql": WIQL_MY_CURRENT_SPRINT}
        )
        ids = ids_from_wiql(wiql)[:MAX_LIST]
        if not ids:
            return []
        batch = await self.caller.call(
            "wit_work_item",
            {"action": "get_batch", "ids": ids, "project": project, "fields": SUMMARY_FIELDS},
        )
        by_id = {w.id: w for w in summaries(batch)}
        return [by_id[i] for i in ids if i in by_id]  # keep the query's ordering

    async def get_work_item(self, work_item_id: int) -> WorkItemDetail:
        data = await self.caller.call(
            "wit_work_item",
            {"action": "get", "id": work_item_id, "project": self.cfg.project, "expand": "Relations"},
        )
        return detail_from_tool_data(data, organization=self.cfg.organization, project=self.cfg.project)

    async def close(self) -> None:
        await self.caller.close()


class AzureService:
    """``crew.azure.list`` -> ``list[WorkItemSummary]``; ``crew.azure.get`` ``{id}`` -> ``WorkItemDetail``.

    Failures are answered as ``{"ok": false, "error": "..."}`` (never a silent timeout).
    """

    def __init__(self, bus: Bus, backend: AzureBackend) -> None:
        self.bus = bus
        self.backend = backend

    async def run(self, stop: asyncio.Event) -> None:
        subs = [
            await self.bus.serve(s.AZURE_LIST, self._list),
            await self.bus.serve(s.AZURE_GET, self._get),
        ]
        log.info("azure_service_started")
        try:
            await stop.wait()
        finally:
            for sub in subs:
                with contextlib.suppress(Exception):
                    await sub.unsubscribe()
            with contextlib.suppress(Exception):
                await self.backend.close()

    async def _list(self, _data: bytes) -> bytes:
        try:
            return _SUMMARIES.dump_json(await self.backend.list_work_items())
        except (AzureError, AzureMappingError) as e:
            log.warning("azure_list_failed", error=str(e))
            return _error(str(e))

    async def _get(self, data: bytes) -> bytes:
        try:
            raw = json.loads(data)
            wid = int(raw["id"])
        except (ValueError, KeyError, TypeError):
            return _error('requisição inválida: esperado {"id": <int>}')
        try:
            return (await self.backend.get_work_item(wid)).model_dump_json().encode()
        except (AzureError, AzureMappingError, ValidationError) as e:
            log.warning("azure_get_failed", work_item_id=wid, error=str(e))
            return _error(str(e))


def _error(message: str) -> bytes:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False).encode()

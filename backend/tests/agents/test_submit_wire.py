"""Drives the in-process MCP server exactly as the Claude Code CLI would (JSON-RPC over the SDK bridge).

This proves, without an API key, that the submit tool is listed with the Pydantic schema and that
valid/invalid calls come back as the CLI would see them. It leans on an SDK-internal class
(``SdkMcpBridge``), so it skips instead of failing if a future SDK moves it.
"""

from __future__ import annotations

from typing import Any

import pytest

from crew.agents.submit import make_submit_tool
from crew.contracts import Plan

bridge_module = pytest.importorskip("claude_agent_sdk._internal.sdk_mcp_bridge")

PLAN_ARGS: dict[str, Any] = {
    "summary": "Adicionar filtro por datas.",
    "steps": ["a"],
    "files": [{"path": "shop/report.py", "change": "M"}],
    "acceptance_criteria": ["x"],
    "test_strategy": "unit",
}


async def rpc(bridge: Any, id_: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    response = await bridge.handle({"jsonrpc": "2.0", "id": id_, "method": method, "params": params})
    assert response is not None
    return dict(response)


async def test_tool_is_listed_and_called_over_jsonrpc() -> None:
    tool = make_submit_tool(Plan, "submit_plan")
    server = tool.server()
    bridge = bridge_module.SdkMcpBridge("crew", server["instance"])
    try:
        init = await rpc(
            bridge,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        )
        assert "result" in init
        await bridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

        listed = await rpc(bridge, 2, "tools/list", {})
        (listed_tool,) = listed["result"]["tools"]
        assert listed_tool["name"] == "submit_plan"
        assert listed_tool["inputSchema"]["required"] == Plan.model_json_schema()["required"]

        bad = await rpc(bridge, 3, "tools/call", {"name": "submit_plan", "arguments": {"summary": 1}})
        assert bad["result"]["isError"] is True
        assert tool.captured is None

        wrong_shape = await rpc(
            bridge, 4, "tools/call", {"name": "submit_plan", "arguments": {**PLAN_ARGS, "steps": "x"}}
        )
        assert wrong_shape["result"]["isError"] is True

        good = await rpc(bridge, 5, "tools/call", {"name": "submit_plan", "arguments": PLAN_ARGS})
        assert good["result"].get("isError", False) is False
        assert "Pode encerrar" in good["result"]["content"][0]["text"]
        assert isinstance(tool.captured, Plan)

        unknown = await rpc(bridge, 6, "tools/call", {"name": "nope", "arguments": {}})
        assert unknown["result"]["isError"] is True
    finally:
        await bridge.aclose()

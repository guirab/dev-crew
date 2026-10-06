"""Structured agent output through a ``submit_*`` tool validated by Pydantic.

The tool is exposed to the agent as an in-process MCP server named ``crew``; the final tool name is
``mcp__crew__<name>``. An invalid payload is answered with a readable error so the agent can fix it
and call the tool again; a valid one is stored in the captor and the agent is told it can stop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig
from pydantic import BaseModel, ValidationError

SERVER_NAME = "crew"

type Check[M: BaseModel] = Callable[[M], str | None]
"""Semantic check run after Pydantic validation. Returns an error message or ``None``."""

OK_TEXT = "ok, resultado registrado. Pode encerrar."


def full_tool_name(name: str) -> str:
    return f"mcp__{SERVER_NAME}__{name}"


def format_validation_error(err: ValidationError) -> str:
    """One line per problem: ``- plan.steps.0: Input should be a valid string``."""
    lines = []
    for e in err.errors(include_url=False, include_input=False, include_context=False):
        loc = ".".join(str(part) for part in e["loc"]) or "(raiz)"
        lines.append(f"- {loc}: {e['msg']}")
    return "\n".join(lines)


def _text(message: str, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": message}]}
    if is_error:
        result["is_error"] = True
    return result


class SubmitTool[M: BaseModel]:
    """A ``submit_*`` tool bound to one output model, plus the captor for its value."""

    def __init__(self, model: type[M], name: str, *, check: Check[M] | None = None) -> None:
        self.model = model
        self.name = name
        self.check = check
        self.captured: M | None = None
        self.rejections = 0
        self.sdk_tool: SdkMcpTool[Any] = tool(
            name,
            f"Entrega o resultado final desta tarefa ({model.__name__}). Chame exatamente quando terminar.",
            model.model_json_schema(),
        )(self.handle)

    @property
    def full_name(self) -> str:
        return full_tool_name(self.name)

    def server(self) -> McpSdkServerConfig:
        return create_sdk_mcp_server(SERVER_NAME, tools=[self.sdk_tool])

    async def handle(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            value = self.model.model_validate(args)
        except ValidationError as e:
            self.rejections += 1
            return _text(
                f"Resultado inválido. Corrija os campos e chame {self.name} de novo:\n"
                f"{format_validation_error(e)}",
                is_error=True,
            )
        if self.check is not None and (problem := self.check(value)):
            self.rejections += 1
            return _text(
                f"Resultado inconsistente: {problem}\nCorrija e chame {self.name} de novo.", is_error=True
            )
        self.captured = value
        return _text(OK_TEXT)


def make_submit_tool[M: BaseModel](
    model: type[M], name: str, *, check: Check[M] | None = None
) -> SubmitTool[M]:
    return SubmitTool(model, name, check=check)

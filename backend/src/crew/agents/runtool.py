"""Tool ``run``: the sandboxed replacement for Bash (D41).

When the repo has a sandbox, the agent loses the built-in Bash and gets ``mcp__crew__run`` instead: same
input (``command``), but the command runs with ``docker exec`` in the task container, which only sees
the worktree (at ``/work``) and has no network. The Bash guards still apply to it (defense in depth).
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import SdkMcpTool, tool

from .. import sandbox
from ..contracts import AgentJob
from .specs import AgentSpec
from .submit import full_tool_name

RUN_TOOL = "run"
RUN_FULL_NAME = full_tool_name(RUN_TOOL)
DEFAULT_TIMEOUT_S = 600
MAX_TIMEOUT_S = 1800
MAX_OUTPUT_CHARS = 30_000

RUN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Comando bash, rodado em /work (o worktree)."},
        "timeout_s": {"type": "integer", "minimum": 1, "maximum": MAX_TIMEOUT_S},
    },
    "required": ["command"],
    "additionalProperties": False,
}


def effective_tools(spec: AgentSpec[Any], job: AgentJob) -> tuple[str, ...]:
    """The agent's tools for this job: with a sandbox, ``Bash`` becomes ``mcp__crew__run``."""
    if not job.repo.sandbox:
        return spec.tools
    return tuple(RUN_FULL_NAME if t == "Bash" else t for t in spec.tools)


def _text(message: str, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": message}]}
    if is_error:
        result["is_error"] = True
    return result


def make_run_tool(job: AgentJob) -> SdkMcpTool[Any]:
    container = sandbox.container_name(job.task_id, job.repo.name)

    async def handle(args: dict[str, Any]) -> dict[str, Any]:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return _text("informe `command`.", is_error=True)
        timeout = min(int(args.get("timeout_s") or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S)
        try:
            res = await sandbox.exec_command(container, command, timeout)
        except sandbox.SandboxError as e:
            return _text(f"sandbox indisponível: {e}", is_error=True)
        return _text(f"exit code: {res.exit_code}\n{sandbox.tail(res.output, MAX_OUTPUT_CHARS)}")

    return tool(
        RUN_TOOL,
        "Executa um comando bash no container Linux isolado da tarefa: cwd /work (o worktree), sem "
        "internet, sem acesso ao resto da máquina. Use caminhos relativos. Devolve exit code e saída.",
        RUN_SCHEMA,
    )(handle)

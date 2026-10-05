"""Spike S0: what the installed claude-agent-sdk really supports.

Usage (from backend/):
    uv run python scripts/spike_sdk.py            # offline: introspection + local tool/hook checks, no API
    uv run python scripts/spike_sdk.py --live     # `claude auth login` session; spends plan quota (capped)

Offline mode never calls the API. Live mode runs against a fresh copy of fixtures/sample-repo with a
submit_echo tool, a hook that denies ``git commit`` and two turns chained with ``resume``.
Results are recorded in docs/spikes/agent-sdk.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import claude_agent_sdk as sdk
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

Row = tuple[str, bool, str]
rows: list[Row] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    rows.append((name, ok, detail))


def section(title: str) -> None:
    print(f"\n## {title}")


# ---------------------------------------------------------------------------------- offline
def introspect() -> None:
    section("Instalação")
    check("claude_agent_sdk importa", True, f"versão {sdk.__version__}")
    from claude_agent_sdk import _cli_version

    check("versão do CLI embutido esperada", True, _cli_version.__cli_version__)
    bundled = Path(sdk.__file__).parent / "_bundled"
    exe = "claude.exe" if platform.system() == "Windows" else "claude"
    check("wheel traz CLI embutida (_bundled)", (bundled / exe).is_file(), str(bundled / exe))

    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    try:
        transport = SubprocessCLITransport(prompt="x", options=ClaudeAgentOptions())
        found = transport._find_cli()
        check("SDK localiza um CLI utilizável", True, found)
        version = subprocess.run([found, "--version"], capture_output=True, text=True, check=False)
        check("CLI responde --version", version.returncode == 0, version.stdout.strip())
    except sdk.CLINotFoundError as e:
        check("SDK localiza um CLI utilizável", False, str(e).splitlines()[0])

    section("Windows: Git Bash para a tool Bash")
    bash = shutil.which("bash")
    check("bash no PATH", bash is not None, bash or "-")
    env_path = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    check(
        "CLAUDE_CODE_GIT_BASH_PATH definido",
        env_path is not None,
        env_path or "(não definido; auto-detecção)",
    )
    standard = Path("C:/Program Files/Git/bin/bash.exe")
    check("Git Bash no caminho padrão", standard.is_file(), str(standard))

    section("API do SDK (introspecção)")
    fields = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    for name in (
        "model",
        "system_prompt",
        "allowed_tools",
        "disallowed_tools",
        "tools",
        "permission_mode",
        "cwd",
        "max_turns",
        "max_budget_usd",
        "mcp_servers",
        "strict_mcp_config",
        "hooks",
        "resume",
        "fork_session",
        "setting_sources",
        "can_use_tool",
        "output_format",
        "env",
        "cli_path",
        "sandbox",
        "effort",
        "task_budget",
    ):
        check(f"ClaudeAgentOptions.{name}", name in fields, "")
    check(
        "ClaudeSDKClient.interrupt()",
        hasattr(ClaudeSDKClient, "interrupt"),
        str(inspect.signature(ClaudeSDKClient.interrupt)),
    )
    check(
        "ClaudeSDKClient.query(prompt, session_id)",
        "session_id" in inspect.signature(ClaudeSDKClient.query).parameters,
        "",
    )
    check("ClaudeSDKClient.receive_response()", hasattr(ClaudeSDKClient, "receive_response"), "")
    check(
        "HookMatcher(matcher, hooks, timeout)",
        {"matcher", "hooks", "timeout"} <= {f.name for f in dataclasses.fields(HookMatcher)},
        "",
    )
    check("@tool + create_sdk_mcp_server", callable(sdk.tool) and callable(sdk.create_sdk_mcp_server), "")
    result_fields = {f.name for f in dataclasses.fields(sdk.ResultMessage)}
    for name in (
        "total_cost_usd",
        "session_id",
        "num_turns",
        "is_error",
        "subtype",
        "usage",
        "api_error_status",
        "errors",
    ):
        check(f"ResultMessage.{name}", name in result_fields, "")
    permission_modes = str(inspect.signature(ClaudeAgentOptions).parameters["permission_mode"].annotation)
    check(
        "permission_mode aceita dontAsk/acceptEdits/default",
        all(m in permission_modes for m in ("dontAsk", "acceptEdits", "default")),
        permission_modes,
    )


async def offline_submit_and_hooks() -> None:
    section("Tool submit e hooks (sem API)")
    from crew.agents.guards import for_agent
    from crew.agents.specs import SPECS
    from crew.agents.submit import make_submit_tool
    from crew.contracts import AgentJob, Plan, RepoContext, TaskSpec

    POSIX_WS = "/work/crew/T-1"

    def make_job(agent: Any) -> AgentJob:
        return AgentJob(
            job_id=uuid4(),
            task_id="T-1",
            agent=agent,
            attempt=1,
            repo=RepoContext(name="r", base_branch="main", test_cmd="pytest", test_globs=["tests/**"]),
            spec=TaskSpec(title="t", description="d", source="manual", repo="r"),
            budget_usd=1.0,
        )

    tool = make_submit_tool(Plan, "submit_plan")
    bad = await tool.handle({"summary": 1})
    check(
        "submit rejeita payload inválido com mensagem legível",
        bad.get("is_error") is True and tool.captured is None,
        bad["content"][0]["text"].splitlines()[0],
    )
    good = await tool.handle(
        {
            "summary": "s",
            "steps": ["a"],
            "files": [{"path": "a.py", "change": "M"}],
            "acceptance_criteria": ["x"],
            "test_strategy": "t",
        }
    )
    check("submit aceita payload válido e captura", tool.captured is not None, good["content"][0]["text"])

    spec = SPECS["developer"]
    hooks = for_agent(spec, make_job("developer"), POSIX_WS)
    hook = hooks["PreToolUse"][0].hooks[0]

    async def call(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        event: Any = {
            "hook_event_name": "PreToolUse",
            "session_id": "s",
            "transcript_path": "t",
            "cwd": POSIX_WS,
            "tool_name": name,
            "tool_input": tool_input,
            "tool_use_id": "1",
        }
        return dict(await hook(event, "1", {"signal": None}))

    denied = await call("Bash", {"command": "git commit -m x"})
    decision = denied.get("hookSpecificOutput", {}).get("permissionDecision")
    check(
        "hook PreToolUse nega `git commit` (permissionDecision=deny)",
        decision == "deny",
        "formato do output do hook",
    )
    allowed = await call("Bash", {"command": "pytest -q"})
    check("hook libera `pytest -q` ({} )", allowed == {}, "")
    outside = await call("Write", {"file_path": "../x.py"})
    check(
        "hook nega Write fora do worktree", outside["hookSpecificOutput"]["permissionDecision"] == "deny", ""
    )


# ---------------------------------------------------------------------------------- live
async def live(budget: float) -> None:
    """Calls the real model through the CLI login (Claude subscription) or ANTHROPIC_API_KEY if set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("AVISO: ANTHROPIC_API_KEY definida, esta rodada cobra na API (não na assinatura).")
    from init_sample_repo import init_sample_repo

    from crew.agents.runner import session_env

    workdir = Path(tempfile.mkdtemp(prefix="crew-spike-")) / "repo"
    init_sample_repo(workdir)
    denied_calls: list[str] = []

    @sdk.tool("submit_echo", "Entrega o texto final.", {"text": str})
    async def submit_echo(args: dict[str, Any]) -> dict[str, Any]:
        print(f"  submit_echo chamado com {args}")
        return {"content": [{"type": "text", "text": "ok"}]}

    async def deny_commit(input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        command = str(input_data.get("tool_input", {}).get("command", ""))
        if "git commit" in command:
            denied_calls.append(command)
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "commit bloqueado pelo spike",
                }
            }
        return {}

    options = ClaudeAgentOptions(
        model=os.environ.get("CREW_SPIKE_MODEL", "claude-sonnet-5-5"),
        cwd=str(workdir),
        tools=["Read", "Bash"],
        allowed_tools=["Read", "Bash", "mcp__crew__submit_echo"],
        mcp_servers={"crew": sdk.create_sdk_mcp_server("crew", tools=[submit_echo])},
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[deny_commit])]},
        permission_mode="default",
        setting_sources=[],
        max_turns=8,
        max_budget_usd=budget,
        env=session_env(),  # same env as the real runner (scrub + Git Bash pinned)
    )

    section("LIVE: turno 1 (Bash + tentativa de commit + submit_echo)")
    session_id = ""
    async with ClaudeSDKClient(options) as client:
        await client.query(
            "Rode `python -m pytest -q`. Depois tente `git commit --allow-empty -m x` e conte o que "
            "aconteceu. "
            "Finalize chamando submit_echo com uma frase."
        )
        async for message in client.receive_response():
            print(" ", type(message).__name__, getattr(message, "subtype", ""))
            if isinstance(message, sdk.ResultMessage):
                session_id = message.session_id
                print(
                    f"  total_cost_usd={message.total_cost_usd} turns={message.num_turns} "
                    f"session={session_id}"
                )
                print(f"  usage={message.usage}")
    check(
        "hook bloqueou o commit na API real",
        bool(denied_calls),
        "; ".join(denied_calls) or "o modelo não tentou commitar",
    )

    section("LIVE: turno 2 com resume=<session_id> (novo cliente)")
    resumed = dataclasses.replace(options, resume=session_id)
    async with ClaudeSDKClient(resumed) as client:
        await client.query(
            "Qual comando você tentou bloquear no turno anterior? Responda em uma frase e chame submit_echo."
        )
        async for message in client.receive_response():
            if isinstance(message, sdk.ResultMessage):
                print(
                    f"  total_cost_usd={message.total_cost_usd} (cumulativo? compare com o turno 1) "
                    f"session={message.session_id}"
                )
                check(
                    "resume mantém o contexto (mesma session ou nova?)",
                    True,
                    f"{session_id} -> {message.session_id}",
                )
    shutil.rmtree(workdir.parent, ignore_errors=True)


async def cli_handshake() -> None:
    """Starts the real CLI and does the control-protocol handshake, without sending any prompt.

    Confirms the options reach the CLI (hooks registered, in-process MCP server connected, tool list)
    with no model call. The CLI may still reach Anthropic for auth/config; nonessential traffic is off.
    """
    from crew.agents.submit import make_submit_tool
    from crew.contracts import Plan

    section("CLI real: handshake sem prompt (sem chamada ao modelo)")
    tool = make_submit_tool(Plan, "submit_plan")

    async def hook(input_data: Any, tool_use_id: str | None, context: Any) -> dict[str, Any]:
        return {}

    options = ClaudeAgentOptions(
        cwd=str(BACKEND),
        tools=["Read", "Glob", "Grep", "Bash"],
        allowed_tools=["Read", "Glob", "Grep", "Bash", tool.full_name],
        mcp_servers={"crew": tool.server()},
        strict_mcp_config=True,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]},
        setting_sources=[],
        permission_mode="default",
        env={"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1"},
    )
    client = ClaudeSDKClient(options)
    try:
        await asyncio.wait_for(client.connect(), 90)
        check("ClaudeSDKClient.connect() com hooks + MCP in-process", True, "handshake ok")
        status: Any = {}
        for _ in range(20):  # the CLI connects MCP servers in the background after the handshake
            status = await asyncio.wait_for(client.get_mcp_status(), 30)
            if status.get("mcpServers"):
                break
            await asyncio.sleep(0.5)
        servers = {s["name"]: s for s in status.get("mcpServers", [])}
        crew = servers.get("crew", {})
        tools = [t["name"] for t in crew.get("tools", [])]
        check(
            "servidor MCP `crew` conectado no CLI", crew.get("status") == "connected", str(crew.get("status"))
        )
        check("tool submit_plan listada pelo CLI", "submit_plan" in tools, str(tools))
    except Exception as e:
        check("handshake com o CLI real", False, f"{type(e).__name__}: {e}"[:200])
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


def report() -> None:
    print("\n| Verificação | Resultado | Detalhe |\n|---|---|---|")
    for name, ok, detail in rows:
        print(f"| {name} | {'OK' if ok else 'FALHOU'} | {detail} |")
    failed = [r for r in rows if not r[1]]
    print(f"\n{len(rows) - len(failed)}/{len(rows)} ok")


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    introspect()
    asyncio.run(offline_submit_and_hooks())
    if "--cli" in argv:
        asyncio.run(cli_handshake())
    if "--live" in argv:
        asyncio.run(live(budget=0.25))
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Runners turn an ``AgentJob`` into an agent output.

``SdkRunner`` drives a real Claude Agent SDK session (``ClaudeSDKClient``); ``ScriptedRunner`` (fake.py)
plays a canned scenario. Both implement ``Runner`` so the service does not care which one it has.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    Message,
    ProcessError,
    ResultMessage,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import SystemPromptPreset

from ..bus import JOB_BUDGET_EXCEEDED, FatalJobError, RetryableJobError
from ..contracts import AgentJob, AgentOutput
from ..gitbash import find_git_bash
from . import guards
from .context import FOLLOW_UP, build_prompt, has_new_information, system_prompt_text
from .progress import ProgressLine, ProgressSink, ProgressThrottle, map_message
from .runtool import RUN_FULL_NAME, effective_tools, make_run_tool
from .settings import AgentRuntimeSettings
from .specs import DISALLOWED_TOOLS, SPECS, AgentSpec
from .submit import SERVER_NAME, SubmitTool, make_submit_tool

log = structlog.get_logger(__name__)

MAX_FOLLOW_UPS = 2
TRANSIENT_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
TRANSIENT_HINTS = ("overloaded", "rate limit", "rate_limit", "timeout", "timed out", "connection reset")
SUBPROCESS_ENV = {
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",  # no API keys/tokens in the env of Bash subprocesses
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",  # no telemetry/auto-update from the worker
}
CLI_PATH_ENV = "CREW_CLAUDE_CLI"


@dataclass(frozen=True)
class RunOutcome:
    output: AgentOutput
    cost_usd: float
    session_id: str | None


class Runner(Protocol):
    async def run(self, job: AgentJob, emit: ProgressSink) -> RunOutcome: ...


class SdkClient(Protocol):
    """The slice of ``ClaudeSDKClient`` the runner uses (tests inject a fake)."""

    async def connect(self) -> None: ...
    async def query(self, prompt: str) -> None: ...
    def receive_response(self) -> AsyncIterator[Message]: ...
    async def interrupt(self) -> None: ...
    async def disconnect(self) -> None: ...


ClientFactory = Callable[[ClaudeAgentOptions], SdkClient]


def default_client_factory(options: ClaudeAgentOptions) -> SdkClient:
    return ClaudeSDKClient(options)


class ResumeFailedError(Exception):
    """The previous session could not be resumed; the caller retries with a full prompt."""


def workspace_of(job: AgentJob) -> str:
    if not job.workspace_path:
        raise FatalJobError(
            f"job {job.agent} sem workspace_path: o agente precisa do diretório do repositório/worktree"
        )
    return job.workspace_path


def build_options(
    spec: AgentSpec[Any],
    job: AgentJob,
    settings: AgentRuntimeSettings,
    workspace: str,
    submit: SubmitTool[Any],
    *,
    resumed: bool,
    on_block: guards.BlockCallback | None = None,
    cli_path: str | None = None,
) -> ClaudeAgentOptions:
    """Options for one CLI session. Never ``bypassPermissions``; the target repo settings are ignored."""
    prompt: SystemPromptPreset = {
        "type": "preset",
        "preset": "claude_code",
        "append": system_prompt_text(spec.name),
    }
    tools = effective_tools(spec, job)
    mcp_tools = [submit.sdk_tool]
    disallowed = list(DISALLOWED_TOOLS)
    if RUN_FULL_NAME in tools:
        mcp_tools.append(make_run_tool(job))
        disallowed.append("Bash")  # the sandbox replaces it; host shell must stay unreachable
    return ClaudeAgentOptions(
        model=settings.model,
        system_prompt=prompt,
        tools=[t for t in tools if not t.startswith("mcp__")],
        allowed_tools=[*tools, submit.full_name],
        disallowed_tools=disallowed,
        permission_mode=spec.permission_mode,
        cwd=workspace,
        max_turns=settings.max_turns or spec.max_turns,
        max_budget_usd=min(spec.budget_cap_usd, job.budget_usd),
        mcp_servers={"crew": create_sdk_mcp_server(SERVER_NAME, tools=mcp_tools)},
        strict_mcp_config=True,
        hooks=guards.for_agent(spec, job, workspace, on_block),
        resume=job.resume_session_id if resumed else None,
        setting_sources=[],
        env=session_env(),
        cli_path=cli_path,
    )


def session_env() -> dict[str, str]:
    """Env for the CLI session. Pins Git Bash so the CLI never picks the WSL launcher in System32."""
    env = dict(SUBPROCESS_ENV)
    bash = find_git_bash()
    if sys.platform == "win32" and bash:
        env["CLAUDE_CODE_GIT_BASH_PATH"] = bash
    return env


def failure_for(
    result: ResultMessage, *, assistant_error: str | None = None
) -> RetryableJobError | FatalJobError | None:
    """Map a ``ResultMessage`` to the bus error the job loop understands (``None`` = success)."""
    if result.subtype == "success" and not result.is_error:
        return None
    detail = "; ".join(result.errors or []) or (result.result or "") or result.subtype
    status = result.api_error_status
    if result.subtype == "error_max_budget_usd":
        return FatalJobError(JOB_BUDGET_EXCEEDED)
    if result.subtype == "error_max_turns":
        return FatalJobError("limite de turnos do agente excedido")
    if assistant_error == "authentication_failed" or status in (401, 403):
        return FatalJobError(
            "autenticação falhou: rode `claude auth login` (assinatura) ou confira ANTHROPIC_API_KEY"
        )
    if assistant_error == "billing_error":
        return FatalJobError("erro de cobrança na API Anthropic (créditos/limite de gasto)")
    if assistant_error in ("rate_limit", "server_error") or status in TRANSIENT_STATUS:
        delay = 60.0 if (status == 429 or assistant_error == "rate_limit") else 30.0
        return RetryableJobError(
            f"API Anthropic indisponível ({status or assistant_error}): {detail}", delay=delay
        )
    if any(hint in detail.lower() for hint in TRANSIENT_HINTS):
        return RetryableJobError(f"falha transitória: {detail}", delay=30.0)
    return FatalJobError(f"sessão terminou com erro ({result.subtype}): {detail}")


class SdkRunner:
    def __init__(
        self,
        settings: AgentRuntimeSettings,
        *,
        client_factory: ClientFactory = default_client_factory,
        cli_path: str | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory
        self._cli_path = cli_path or os.environ.get(CLI_PATH_ENV) or None

    async def run(self, job: AgentJob, emit: ProgressSink) -> RunOutcome:
        spec = SPECS[job.agent]
        workspace = workspace_of(job)
        if job.budget_usd <= 0:
            raise FatalJobError("orçamento da tarefa esgotado")
        resumed = bool(spec.resume_across_rounds and job.resume_session_id and has_new_information(job))
        try:
            return await self._session(job, spec, workspace, emit, resumed=resumed)
        except ResumeFailedError:
            log.warning("resume_failed_retrying_fresh", agent=job.agent, session=job.resume_session_id)
            await emit(
                ProgressLine("status", "sessão anterior indisponível; recomeçando com contexto completo")
            )
            return await self._session(job, spec, workspace, emit, resumed=False)

    async def _session(
        self, job: AgentJob, spec: AgentSpec[Any], workspace: str, emit: ProgressSink, *, resumed: bool
    ) -> RunOutcome:
        submit = make_submit_tool(spec.output, spec.submit_name, check=spec.check)
        throttle = ProgressThrottle(emit)

        async def on_block(reason: str) -> None:
            await throttle.push(ProgressLine("status", f"bloqueado: {reason}"))

        options = build_options(
            spec,
            job,
            self.settings,
            workspace,
            submit,
            resumed=resumed,
            on_block=on_block,
            cli_path=self._cli_path,
        )
        client = self._client_factory(options)
        state = _State()
        try:
            await client.connect()
            await self._turn(
                client,
                build_prompt(job, spec, resumed=resumed),
                workspace,
                throttle,
                state,
                submit,
                resumed=resumed,
            )
            while submit.captured is None:
                if state.follow_ups >= MAX_FOLLOW_UPS:
                    raise FatalJobError(
                        f"o agente terminou sem chamar {spec.submit_name} após {MAX_FOLLOW_UPS} lembretes"
                    )
                state.follow_ups += 1
                await throttle.push(ProgressLine("status", "lembrando o agente de entregar o resultado"))
                await self._turn(
                    client,
                    FOLLOW_UP.format(tool=spec.submit_name),
                    workspace,
                    throttle,
                    state,
                    submit,
                    resumed=False,
                )
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(client.interrupt(), timeout=3)
            raise
        except CLINotFoundError as e:
            raise FatalJobError(f"CLI do Claude Code não encontrada: {e}") from e
        except ProcessError as e:
            if resumed and "no conversation found" in str(e).lower():
                raise ResumeFailedError from e
            raise RetryableJobError(f"processo do Claude Code falhou: {e}", delay=30.0) from e
        except (CLIConnectionError, CLIJSONDecodeError) as e:
            raise RetryableJobError(f"conexão com o Claude Code falhou: {e}", delay=30.0) from e
        except ClaudeSDKError as e:
            raise FatalJobError(f"erro do SDK: {e}") from e
        finally:
            with contextlib.suppress(Exception):
                await throttle.flush()
            with contextlib.suppress(Exception):
                await client.disconnect()

        output = submit.captured
        if output is None:  # unreachable: the loop above only exits with a captured value
            raise FatalJobError(f"o agente não entregou {spec.submit_name}")
        if spec.finalize is not None:
            output = spec.finalize(output, job)
        return RunOutcome(output=output, cost_usd=state.cost_usd, session_id=state.session_id)

    async def _turn(
        self,
        client: SdkClient,
        prompt: str,
        workspace: str,
        throttle: ProgressThrottle,
        state: _State,
        submit: SubmitTool[Any],
        *,
        resumed: bool,
    ) -> None:
        """One ``query`` + response stream. Raises the mapped bus error on a failed result."""
        await client.query(prompt)
        result: ResultMessage | None = None
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                state.saw_assistant = True
                if message.error:
                    state.assistant_error = message.error
            for line in map_message(message, workspace):
                await throttle.push(line)
            if isinstance(message, ResultMessage):
                result = message
        if result is None:
            raise RetryableJobError("sessão encerrou sem resultado (processo caiu?)", delay=30.0)
        state.session_id = result.session_id or state.session_id
        if result.total_cost_usd is not None:
            state.cost_usd = result.total_cost_usd  # assumed cumulative per client session; see spike doc
        if resumed and result.is_error and not state.saw_assistant:
            raise ResumeFailedError
        error = failure_for(result, assistant_error=state.assistant_error)
        if error is not None and submit.captured is None:
            raise error


@dataclass
class _State:
    cost_usd: float = 0.0
    session_id: str | None = None
    follow_ups: int = 0
    saw_assistant: bool = False
    assistant_error: str | None = None

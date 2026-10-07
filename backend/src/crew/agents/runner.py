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
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    RateLimitEvent,
    ResultMessage,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
)
from claude_agent_sdk.types import RateLimitInfo, SystemPromptPreset

from ..bus import FatalJobError, RetryableJobError, UsageLimitJobError
from ..contracts import AgentJob, AgentOutput, TokenUsage, UsageLimit, UsageLimitKind
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
USAGE_LIMIT_HINTS = ("usage limit", "hit your limit")  # CLI texts when the subscription quota is gone
STALL_TIMEOUT_S = 30 * 60.0
"""D52: no SDK message for this long while no tool is running = the session is stuck. Not a time limit:
a session that keeps working (messages, tool calls) can run for hours."""
_LIMIT_KINDS: dict[str, UsageLimitKind] = {
    "five_hour": "session",
    "seven_day": "weekly",
    "seven_day_opus": "weekly_opus",
    "seven_day_sonnet": "weekly_sonnet",
}
_LIMIT_LABELS: dict[UsageLimitKind, str] = {
    "session": "sessão de 5 h",
    "weekly": "semana",
    "weekly_opus": "semana, Opus",
    "weekly_sonnet": "semana, Sonnet",
    "unknown": "assinatura",
}
SUBPROCESS_ENV = {
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",  # no API keys/tokens in the env of Bash subprocesses
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",  # no telemetry/auto-update from the worker
}
CLI_PATH_ENV = "CREW_CLAUDE_CLI"
SESSION_START_GAP_S = 4.0
"""Parallel lanes start CLI sessions at the same time; when the OAuth token needs a refresh they race for
it and all but one fail. Sessions of this process start at least this far apart."""


class _StartGate:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self, gap: float) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            delay = self._last + gap - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = loop.time()


_START_GATE = _StartGate()


@dataclass(frozen=True)
class RunOutcome:
    output: AgentOutput
    cost_usd: float
    session_id: str | None
    usage: tuple[TokenUsage, ...] = ()


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
        max_turns=settings.max_turns or spec.max_turns,  # None = no cap (D51)
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


def usage_limit(kind: UsageLimitKind, resets_at: datetime | None) -> UsageLimit:
    return UsageLimit(
        kind=kind,
        resets_at=resets_at,
        message=f"Limite de uso da assinatura atingido ({_LIMIT_LABELS[kind]})",
    )


def limit_from_event(info: RateLimitInfo) -> UsageLimit | None:
    """A ``rejected`` rate-limit event means the subscription quota is gone until ``resets_at``."""
    if info.status != "rejected":
        return None
    kind = _LIMIT_KINDS.get(info.rate_limit_type or "", "unknown")
    resets = datetime.fromtimestamp(info.resets_at, UTC) if info.resets_at else None
    return usage_limit(kind, resets)


def token_usage(result: ResultMessage) -> tuple[TokenUsage, ...]:
    """Per-model tokens of the session so far (the CLI reports cumulative figures)."""
    return tuple(
        TokenUsage(
            model=model,
            input_tokens=int(mu.get("inputTokens", 0)),
            output_tokens=int(mu.get("outputTokens", 0)),
            cache_read_tokens=int(mu.get("cacheReadInputTokens", 0)),
            cache_write_tokens=int(mu.get("cacheCreationInputTokens", 0)),
            cost_usd=float(mu.get("costUSD", 0.0)),
        )
        for model, mu in (result.model_usage or {}).items()
    )


def failure_for(
    result: ResultMessage, *, assistant_error: str | None = None, limit: UsageLimit | None = None
) -> RetryableJobError | FatalJobError | None:
    """Map a ``ResultMessage`` to the bus error the job loop understands (``None`` = success)."""
    if result.subtype == "success" and not result.is_error:
        return None
    detail = "; ".join(result.errors or []) or (result.result or "") or result.subtype
    status = result.api_error_status
    if limit is not None:
        return UsageLimitJobError(limit)
    if (assistant_error == "rate_limit" or status == 429) and any(
        hint in detail.lower() for hint in USAGE_LIMIT_HINTS
    ):
        return UsageLimitJobError(usage_limit("unknown", None))
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
        stall_timeout_s: float = STALL_TIMEOUT_S,
        start_gap_s: float = SESSION_START_GAP_S,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory
        self._cli_path = cli_path or os.environ.get(CLI_PATH_ENV) or None
        self._stall_timeout_s = stall_timeout_s
        self._start_gap_s = start_gap_s

    async def run(self, job: AgentJob, emit: ProgressSink) -> RunOutcome:
        spec = SPECS[job.agent]
        workspace = workspace_of(job)
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
        submit = make_submit_tool(spec.output, spec.submit_name, check=spec.check_for(job))
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
            await _START_GATE.wait(self._start_gap_s)
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
        return RunOutcome(
            output=output, cost_usd=state.cost_usd, session_id=state.session_id, usage=state.usage
        )

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
        running_tools: set[str] = set()
        stream = client.receive_response().__aiter__()
        while True:
            # a running tool (a long test suite) may be silent for long: only idle *between* tools counts
            timeout = None if running_tools else self._stall_timeout_s
            try:
                message = await asyncio.wait_for(anext(stream), timeout)
            except StopAsyncIteration:
                break
            except TimeoutError:
                minutes = round(self._stall_timeout_s / 60)
                raise FatalJobError(f"agente sem nenhuma atividade há {minutes} min (travado?)") from None
            if isinstance(message, AssistantMessage):
                state.saw_assistant = True
                if message.error:
                    state.assistant_error = message.error
                running_tools.update(b.id for b in message.content if isinstance(b, ToolUseBlock))
            elif isinstance(message, UserMessage) and isinstance(message.content, list):
                running_tools.difference_update(
                    b.tool_use_id for b in message.content if isinstance(b, ToolResultBlock)
                )
            elif isinstance(message, RateLimitEvent):
                await self._on_rate_limit(message.rate_limit_info, state, throttle)
            for line in map_message(message, workspace):
                await throttle.push(line)
            if isinstance(message, ResultMessage):
                result = message
        if result is None:
            if state.limit is not None:
                raise UsageLimitJobError(state.limit)
            raise RetryableJobError("sessão encerrou sem resultado (processo caiu?)", delay=30.0)
        state.session_id = result.session_id or state.session_id
        if result.total_cost_usd is not None:
            state.cost_usd = result.total_cost_usd  # assumed cumulative per client session; see spike doc
        state.usage = token_usage(result) or state.usage
        if resumed and result.is_error and not state.saw_assistant:
            raise ResumeFailedError
        error = failure_for(result, assistant_error=state.assistant_error, limit=state.limit)
        if error is not None and submit.captured is None:
            raise error

    @staticmethod
    async def _on_rate_limit(info: RateLimitInfo, state: _State, throttle: ProgressThrottle) -> None:
        limit = limit_from_event(info)
        if limit is not None:
            state.limit = limit
            await throttle.push(ProgressLine("status", limit.message))
        elif info.status == "allowed_warning":
            pct = f" ({round(info.utilization * 100)}%)" if info.utilization is not None else ""
            await throttle.push(ProgressLine("status", f"Perto do limite de uso da assinatura{pct}"))


@dataclass
class _State:
    cost_usd: float = 0.0
    session_id: str | None = None
    follow_ups: int = 0
    saw_assistant: bool = False
    assistant_error: str | None = None
    usage: tuple[TokenUsage, ...] = field(default_factory=tuple)
    limit: UsageLimit | None = None

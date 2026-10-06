"""SdkRunner against a scripted fake client: no CLI, no API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    CLIConnectionError,
    CLINotFoundError,
    Message,
    ProcessError,
    ResultMessage,
    ToolUseBlock,
)

from crew.agents import runner as runner_module
from crew.agents.progress import ProgressLine
from crew.agents.runner import SdkRunner, build_options, failure_for
from crew.agents.settings import AgentRuntimeSettings
from crew.agents.specs import SPECS
from crew.agents.submit import SubmitTool, make_submit_tool
from crew.bus import FatalJobError, RetryableJobError
from crew.contracts import (
    DevResult,
    Feedback,
    Plan,
    TestFailure,
    TestResult,
)

from .factories import POSIX_WS, make_job, make_turn

PLAN_ARGS: dict[str, Any] = {
    "summary": "Adicionar filtro por datas.",
    "steps": ["a", "b"],
    "files": [{"path": "shop/report.py", "change": "M"}],
    "acceptance_criteria": ["intervalo inclusivo"],
    "test_strategy": "unit",
}


def result_msg(
    *,
    cost: float | None = 0.1,
    session: str = "sess-1",
    error: bool = False,
    subtype: str = "success",
    **kw: Any,
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=error,
        num_turns=kw.pop("num_turns", 1),
        session_id=session,
        total_cost_usd=cost,
        **kw,
    )


def assistant(*blocks: Any, error: str | None = None) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model="m", error=error)  # type: ignore[arg-type]


def tool_use(name: str, **tool_input: Any) -> ToolUseBlock:
    return ToolUseBlock(id=f"tu-{name}", name=name, input=tool_input)


Turn = Callable[["ScriptedClient"], AsyncIterator[Message]]


class ScriptedClient:
    """Plays one scripted turn per ``query``; records everything the runner does."""

    def __init__(
        self, options: ClaudeAgentOptions, turns: list[Turn], submit_box: list[SubmitTool[Any]]
    ) -> None:
        self.options = options
        self.turns = turns
        self.submit_box = submit_box
        self.prompts: list[str] = []
        self.connected = False
        self.disconnected = False
        self.interrupted = False
        self.connect_error: Exception | None = None
        self._current: Turn | None = None

    @property
    def submit(self) -> SubmitTool[Any]:
        return self.submit_box[-1]

    async def connect(self) -> None:
        if self.connect_error:
            raise self.connect_error
        self.connected = True

    async def query(self, prompt: str) -> None:
        self.prompts.append(prompt)
        self._current = self.turns[len(self.prompts) - 1]

    def receive_response(self) -> AsyncIterator[Message]:
        assert self._current is not None
        return self._current(self)

    async def interrupt(self) -> None:
        self.interrupted = True

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patches ``make_submit_tool`` to expose the tool and builds a runner with scripted clients."""
    submit_box: list[SubmitTool[Any]] = []
    real = runner_module.make_submit_tool

    def spy(*args: Any, **kwargs: Any) -> SubmitTool[Any]:
        tool = real(*args, **kwargs)
        submit_box.append(tool)
        return tool

    monkeypatch.setattr(runner_module, "make_submit_tool", spy)

    class Harness:
        def __init__(self) -> None:
            self.clients: list[ScriptedClient] = []
            self.progress: list[ProgressLine] = []

        def runner(
            self, *session_scripts: list[Turn], model: str = "claude-opus-5-5", **kw: Any
        ) -> SdkRunner:
            scripts = list(session_scripts)

            def factory(options: ClaudeAgentOptions) -> ScriptedClient:
                client = ScriptedClient(options, scripts[len(self.clients)], submit_box)
                self.clients.append(client)
                return client

            return SdkRunner(AgentRuntimeSettings(model=model, **kw), client_factory=factory)

        async def emit(self, line: ProgressLine) -> None:
            self.progress.append(line)

        @property
        def texts(self) -> list[str]:
            return [p.text for p in self.progress]

    return Harness()


def submit_ok(args: dict[str, Any], *, name: str = "mcp__crew__submit_plan", cost: float = 0.12) -> Turn:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        yield assistant(tool_use("Read", file_path=f"{POSIX_WS}/shop/report.py"))
        yield assistant(tool_use(name, **args))
        await client.submit.handle(args)
        yield result_msg(cost=cost)

    return turn


def ends_without_submit(cost: float = 0.05) -> Turn:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        yield assistant(tool_use("Grep", pattern="def "))
        yield result_msg(cost=cost)

    return turn


# ---------------------------------------------------------------------------------- happy path
async def test_planner_happy_path_returns_output_cost_and_session(harness: Any) -> None:
    job = make_job("planner", workspace=POSIX_WS)
    outcome = await harness.runner([submit_ok(PLAN_ARGS)]).run(job, harness.emit)
    assert isinstance(outcome.output, Plan)
    assert outcome.output.summary == "Adicionar filtro por datas."
    assert outcome.cost_usd == 0.12
    assert outcome.session_id == "sess-1"
    client = harness.clients[0]
    assert client.connected and client.disconnected and len(client.prompts) == 1


async def test_progress_lines_come_from_the_message_stream(harness: Any) -> None:
    job = make_job("planner", workspace=POSIX_WS)
    await harness.runner([submit_ok(PLAN_ARGS)]).run(job, harness.emit)
    assert "Lendo shop/report.py" in harness.texts or "Enviando resultado" in harness.texts
    assert all(p.kind in ("tool", "text", "status") for p in harness.progress)


async def test_first_prompt_has_the_fixed_sections(harness: Any) -> None:
    job = make_job("developer", workspace=POSIX_WS)
    args = {"round": 1, "summary": "feito", "files_changed": [{"path": "shop/report.py", "change": "M"}]}
    await harness.runner([submit_ok(args, name="mcp__crew__submit_dev_result")]).run(job, harness.emit)
    prompt = harness.clients[0].prompts[0]
    for heading in ("## Tarefa", "## Plano", "## Regras do job"):
        assert heading in prompt


async def test_finalizer_forces_dev_round_from_the_job(harness: Any) -> None:
    job = make_job("developer", workspace=POSIX_WS, attempt=3)
    args = {"round": 1, "summary": "feito", "files_changed": []}
    outcome = await harness.runner([submit_ok(args, name="mcp__crew__submit_dev_result")]).run(
        job, harness.emit
    )
    assert isinstance(outcome.output, DevResult)
    assert outcome.output.round == 3


# ---------------------------------------------------------------------------------- submit discipline
async def test_follow_up_when_the_agent_forgets_to_submit(harness: Any) -> None:
    job = make_job("planner", workspace=POSIX_WS)
    outcome = await harness.runner([ends_without_submit(), submit_ok(PLAN_ARGS, cost=0.2)]).run(
        job, harness.emit
    )
    assert isinstance(outcome.output, Plan)
    prompts = harness.clients[0].prompts
    assert len(prompts) == 2
    assert "submit_plan" in prompts[1]
    assert "lembrando o agente de entregar o resultado" in harness.texts
    assert outcome.cost_usd == 0.2


async def test_gives_up_after_two_follow_ups(harness: Any) -> None:
    job = make_job("planner", workspace=POSIX_WS)
    runner = harness.runner([ends_without_submit(), ends_without_submit(), ends_without_submit()])
    with pytest.raises(FatalJobError, match="submit_plan"):
        await runner.run(job, harness.emit)
    assert len(harness.clients[0].prompts) == 3  # original + 2 follow-ups
    assert harness.clients[0].disconnected


async def test_invalid_then_valid_submit_in_one_turn(harness: Any) -> None:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        first = await client.submit.handle({"summary": 1})
        assert first["is_error"] is True
        await client.submit.handle(PLAN_ARGS)
        yield result_msg()

    outcome = await harness.runner([turn]).run(make_job("planner", workspace=POSIX_WS), harness.emit)
    assert isinstance(outcome.output, Plan)


async def test_error_result_after_a_valid_submit_does_not_discard_it(harness: Any) -> None:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        await client.submit.handle(PLAN_ARGS)
        yield result_msg(error=True, subtype="error_max_turns")

    outcome = await harness.runner([turn]).run(make_job("planner", workspace=POSIX_WS), harness.emit)
    assert isinstance(outcome.output, Plan)


# ---------------------------------------------------------------------------------- errors
def make_result(**kw: Any) -> ResultMessage:
    return result_msg(**kw)


@pytest.mark.parametrize(
    ("kwargs", "assistant_error", "expected", "match", "delay"),
    [
        ({}, None, None, "", None),
        ({"error": True, "subtype": "error_max_turns"}, None, FatalJobError, "turnos", None),
        ({"error": True, "subtype": "error_max_budget_usd"}, None, FatalJobError, "orçamento", None),
        ({"error": True, "api_error_status": 401}, None, FatalJobError, "ANTHROPIC_API_KEY", None),
        ({"error": True}, "authentication_failed", FatalJobError, "ANTHROPIC_API_KEY", None),
        ({"error": True}, "billing_error", FatalJobError, "cobrança", None),
        ({"error": True, "api_error_status": 429}, None, RetryableJobError, "429", 60.0),
        ({"error": True}, "rate_limit", RetryableJobError, "rate_limit", 60.0),
        ({"error": True, "api_error_status": 529}, None, RetryableJobError, "529", 30.0),
        ({"error": True, "api_error_status": 503}, None, RetryableJobError, "503", 30.0),
        ({"error": True}, "server_error", RetryableJobError, "server_error", 30.0),
        ({"error": True, "result": "Overloaded, try later"}, None, RetryableJobError, "Overloaded", 30.0),
        ({"error": True, "errors": ["request timed out"]}, None, RetryableJobError, "timed out", 30.0),
        (
            {"error": True, "subtype": "error_during_execution", "errors": ["boom"]},
            None,
            FatalJobError,
            "boom",
            None,
        ),
        (
            {"error": True, "api_error_status": 400, "result": "bad request"},
            None,
            FatalJobError,
            "bad request",
            None,
        ),
    ],
)
def test_failure_mapping(
    kwargs: dict[str, Any],
    assistant_error: str | None,
    expected: type | None,
    match: str,
    delay: float | None,
) -> None:
    err = failure_for(make_result(**kwargs), assistant_error=assistant_error)
    if expected is None:
        assert err is None
        return
    assert isinstance(err, expected)
    assert match in str(err)
    if isinstance(err, RetryableJobError):
        assert err.delay == delay


async def test_error_result_without_submit_raises_the_mapped_error(harness: Any) -> None:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        yield result_msg(error=True, api_error_status=429)

    with pytest.raises(RetryableJobError):
        await harness.runner([turn]).run(make_job("planner", workspace=POSIX_WS), harness.emit)
    assert harness.clients[0].disconnected


async def test_assistant_level_error_is_used_to_classify(harness: Any) -> None:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        yield assistant(error="authentication_failed")
        yield result_msg(error=True)

    with pytest.raises(FatalJobError, match="ANTHROPIC_API_KEY"):
        await harness.runner([turn]).run(make_job("planner", workspace=POSIX_WS), harness.emit)


async def test_stream_ending_without_result_is_retryable(harness: Any) -> None:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        yield assistant(tool_use("Read", file_path="a.py"))

    with pytest.raises(RetryableJobError, match="sem resultado"):
        await harness.runner([turn]).run(make_job("planner", workspace=POSIX_WS), harness.emit)


@pytest.mark.parametrize(
    ("error", "kind", "match"),
    [
        (CLINotFoundError("claude missing"), FatalJobError, "CLI do Claude Code"),
        (ProcessError("crashed", exit_code=1), RetryableJobError, "processo"),
        (CLIConnectionError("pipe closed"), RetryableJobError, "conexão"),
    ],
)
async def test_sdk_exceptions_map_to_bus_errors(
    harness: Any, error: Exception, kind: type, match: str
) -> None:
    runner = harness.runner([submit_ok(PLAN_ARGS)])
    original = runner._client_factory

    def failing(options: ClaudeAgentOptions) -> ScriptedClient:
        client = original(options)
        client.connect_error = error
        return client

    runner._client_factory = failing
    with pytest.raises(kind, match=match):
        await runner.run(make_job("planner", workspace=POSIX_WS), harness.emit)
    assert harness.clients[0].disconnected


async def test_job_without_workspace_or_budget_fails_fast(harness: Any) -> None:
    runner = harness.runner([submit_ok(PLAN_ARGS)])
    with pytest.raises(FatalJobError, match="workspace_path"):
        await runner.run(make_job("planner"), harness.emit)
    with pytest.raises(FatalJobError, match="orçamento"):
        await runner.run(make_job("planner", workspace=POSIX_WS, budget_usd=0), harness.emit)
    assert harness.clients == []


# ---------------------------------------------------------------------------------- cancellation
async def test_cancellation_interrupts_and_disconnects(harness: Any) -> None:
    started = asyncio.Event()

    async def hang(client: ScriptedClient) -> AsyncIterator[Message]:
        yield assistant(tool_use("Read", file_path="a.py"))
        started.set()
        await asyncio.sleep(60)
        yield result_msg()

    task = asyncio.create_task(
        harness.runner([hang]).run(make_job("planner", workspace=POSIX_WS), harness.emit)
    )
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client = harness.clients[0]
    assert client.interrupted
    assert client.disconnected


# ---------------------------------------------------------------------------------- resume
async def test_resume_sends_only_feedback_and_rules(harness: Any) -> None:
    failing = TestResult(
        ok=False,
        passed=1,
        total=2,
        failures=[TestFailure(test="t::x", message="esperado 12, obtido 9")],
        command="pytest",
    )
    job = make_job(
        "developer",
        workspace=POSIX_WS,
        attempt=2,
        resume_session_id="old-session",
        feedback=Feedback(kind="test_failures", test=failing),
    )
    args = {"round": 2, "summary": "corrigido", "files_changed": []}
    await harness.runner([submit_ok(args, name="mcp__crew__submit_dev_result")]).run(job, harness.emit)
    client = harness.clients[0]
    assert client.options.resume == "old-session"
    prompt = client.prompts[0]
    assert "## Feedback" in prompt
    assert "esperado 12, obtido 9" in prompt
    assert "## Tarefa" not in prompt
    assert "## Plano" not in prompt


async def test_resume_without_new_information_sends_the_full_prompt(harness: Any) -> None:
    job = make_job("developer", workspace=POSIX_WS, resume_session_id="old-session")
    args = {"round": 1, "summary": "feito", "files_changed": []}
    await harness.runner([submit_ok(args, name="mcp__crew__submit_dev_result")]).run(job, harness.emit)
    client = harness.clients[0]
    assert client.options.resume is None
    assert "## Tarefa" in client.prompts[0]


async def test_interviewer_resume_sends_the_last_answer(harness: Any) -> None:
    job = make_job(
        "interviewer", workspace=POSIX_WS, resume_session_id="s0", history=[make_turn("Fora de escopo")]
    )

    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        await client.submit.handle(
            {"kind": "question", "questions": [{"topic": "t", "question": "q?", "recommendation": "r"}]}
        )
        yield result_msg()

    await harness.runner([turn]).run(job, harness.emit)
    client = harness.clients[0]
    assert client.options.resume == "s0"
    assert "Respostas do usuário à rodada 1:" in client.prompts[0]
    assert "[Fora de escopo]" in client.prompts[0]
    assert "## Tarefa" not in client.prompts[0]


async def test_failed_resume_falls_back_to_a_fresh_full_prompt(harness: Any) -> None:
    async def resume_fails(client: ScriptedClient) -> AsyncIterator[Message]:
        yield result_msg(
            error=True, num_turns=0, subtype="error_during_execution", errors=["No conversation found"]
        )

    feedback = Feedback(kind="human_instruction", text="use fake timers")
    job = make_job("developer", workspace=POSIX_WS, attempt=2, resume_session_id="gone", feedback=feedback)
    args = {"round": 2, "summary": "ok", "files_changed": []}
    runner = harness.runner([resume_fails], [submit_ok(args, name="mcp__crew__submit_dev_result")])
    outcome = await runner.run(job, harness.emit)
    assert isinstance(outcome.output, DevResult)
    first, second = harness.clients
    assert first.options.resume == "gone"
    assert second.options.resume is None
    assert "## Tarefa" in second.prompts[0]
    assert "use fake timers" in second.prompts[0]
    assert first.disconnected
    assert any("recomeçando" in t for t in harness.texts)


# ---------------------------------------------------------------------------------- guards wiring
async def test_blocked_tool_call_becomes_a_status_line(harness: Any) -> None:
    async def turn(client: ScriptedClient) -> AsyncIterator[Message]:
        (matcher,) = client.options.hooks["PreToolUse"]  # type: ignore[index]
        hook = matcher.hooks[0]
        event: Any = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
        out = await hook(event, "tu1", {"signal": None})
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        await client.submit.handle({"round": 1, "summary": "feito", "files_changed": []})
        yield result_msg()

    job = make_job("developer", workspace=POSIX_WS)
    await harness.runner([turn]).run(job, harness.emit)
    blocked = [p for p in harness.progress if p.kind == "status" and p.text.startswith("bloqueado:")]
    assert len(blocked) == 1
    assert "git" in blocked[0].text


# ---------------------------------------------------------------------------------- options
@pytest.mark.parametrize("agent", ["interviewer", "planner", "developer", "tester", "reviewer"])
def test_build_options_per_agent(agent: str) -> None:
    spec = SPECS[agent]  # type: ignore[index]
    job = make_job(agent, workspace=POSIX_WS, budget_usd=5.0)  # type: ignore[arg-type]
    submit = make_submit_tool(spec.output, spec.submit_name, check=spec.check)
    opts = build_options(spec, job, AgentRuntimeSettings(model="m-x"), POSIX_WS, submit, resumed=False)

    assert opts.model == "m-x"
    assert opts.cwd == POSIX_WS
    assert opts.tools == list(spec.tools)
    assert opts.allowed_tools == [*spec.tools, f"mcp__crew__{spec.submit_name}"]
    assert opts.permission_mode == spec.permission_mode
    assert opts.permission_mode != "bypassPermissions"
    assert opts.setting_sources == []
    assert opts.strict_mcp_config is True
    assert opts.resume is None
    assert opts.max_turns == spec.max_turns
    assert opts.max_budget_usd == spec.budget_cap_usd
    assert set(opts.disallowed_tools) >= {"WebFetch", "WebSearch", "PowerShell"}
    assert opts.env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1"
    git_bash = opts.env.get("CLAUDE_CODE_GIT_BASH_PATH", "")
    assert "system32" not in git_bash.lower()  # never the WSL launcher
    assert list(opts.mcp_servers) == ["crew"]  # type: ignore[arg-type]
    assert opts.hooks is not None
    assert list(opts.hooks) == ["PreToolUse"]
    assert isinstance(opts.system_prompt, dict)
    assert opts.system_prompt["preset"] == "claude_code"
    assert "Equipe dev-crew" in opts.system_prompt["append"]  # type: ignore[typeddict-item]
    assert f"Papel: {_role(agent)}" in opts.system_prompt["append"]  # type: ignore[typeddict-item]


def _role(agent: str) -> str:
    return {
        "interviewer": "Entrevistador",
        "planner": "Planner",
        "developer": "Developer",
        "tester": "Tester",
        "reviewer": "Reviewer",
    }[agent]


def test_budget_is_the_smaller_of_cap_and_remaining() -> None:
    spec = SPECS["developer"]
    submit = make_submit_tool(spec.output, spec.submit_name)
    low = build_options(
        spec,
        make_job("developer", budget_usd=0.4),
        AgentRuntimeSettings(model="m"),
        POSIX_WS,
        submit,
        resumed=False,
    )
    high = build_options(
        spec,
        make_job("developer", budget_usd=99),
        AgentRuntimeSettings(model="m"),
        POSIX_WS,
        submit,
        resumed=False,
    )
    assert low.max_budget_usd == 0.4
    assert high.max_budget_usd == spec.budget_cap_usd


def test_settings_override_max_turns_and_resume_is_set_only_when_resumed() -> None:
    spec = SPECS["tester"]
    submit = make_submit_tool(spec.output, spec.submit_name)
    job = make_job("tester", resume_session_id="abc")
    plain = build_options(
        spec, job, AgentRuntimeSettings(model="m", max_turns=7), POSIX_WS, submit, resumed=False
    )
    resumed = build_options(
        spec, job, AgentRuntimeSettings(model="m"), POSIX_WS, submit, resumed=True, cli_path="C:/x/claude.exe"
    )
    assert plain.max_turns == 7
    assert plain.resume is None
    assert resumed.resume == "abc"
    assert str(resumed.cli_path) == "C:/x/claude.exe"

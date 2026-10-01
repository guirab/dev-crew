"""Progress mapping and throttling (no LLM, no clock sleeps)."""

from __future__ import annotations

from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from crew.agents.progress import (
    BASH_MAX,
    TEXT_MAX,
    ProgressLine,
    ProgressThrottle,
    display_path,
    map_message,
    text_line,
    tool_line,
)

from .factories import POSIX_WS, WINDOWS_WS


def tool(name: str, **tool_input: object) -> ProgressLine | None:
    return tool_line(name, tool_input, POSIX_WS)


@pytest.mark.parametrize(
    ("name", "tool_input", "text"),
    [
        ("Read", {"file_path": f"{POSIX_WS}/src/x.py"}, "Lendo src/x.py"),
        ("Read", {"file_path": "src/x.py"}, "Lendo src/x.py"),
        ("Read", {}, "Lendo ?"),
        ("Grep", {"pattern": "def foo"}, 'Buscando "def foo"'),
        ("Glob", {"pattern": "**/*.py"}, 'Buscando "**/*.py"'),
        ("Edit", {"file_path": f"{POSIX_WS}/src/x.py"}, "Editando src/x.py"),
        ("MultiEdit", {"file_path": "src/x.py"}, "Editando src/x.py"),
        ("NotebookEdit", {"notebook_path": f"{POSIX_WS}/a.ipynb"}, "Editando a.ipynb"),
        ("Write", {"file_path": f"{POSIX_WS}/src/new.tsx"}, "Criando src/new.tsx"),
        ("Bash", {"command": "pytest -q"}, "$ pytest -q"),
        ("Bash", {"command": "ruff check .\nmypy src"}, "$ ruff check ."),
        ("Bash", {"command": "  pytest    -q   tests/ "}, "$ pytest -q tests/"),
        ("mcp__crew__submit_plan", {"summary": "x"}, "Enviando resultado"),
        ("mcp__crew__submit_review", {}, "Enviando resultado"),
        ("WebFetch", {}, "Usando WebFetch"),
    ],
)
def test_tool_lines(name: str, tool_input: dict[str, object], text: str) -> None:
    assert tool_line(name, tool_input, POSIX_WS) == ProgressLine("tool", text)


def test_todo_write_is_not_shown() -> None:
    assert tool("TodoWrite", todos=[]) is None


def test_bash_is_truncated_to_the_limit() -> None:
    line = tool("Bash", command="python -m pytest " + "x" * 200)
    assert line is not None
    assert len(line.text) == BASH_MAX
    assert line.text.endswith("…")
    assert line.text.startswith("$ python -m pytest xxx")


def test_write_says_editing_when_the_file_exists(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    ws = str(tmp_path)
    assert tool_line("Write", {"file_path": str(tmp_path / "a.py")}, ws) == ProgressLine(
        "tool", "Editando a.py"
    )
    assert tool_line("Write", {"file_path": "a.py"}, ws) == ProgressLine("tool", "Editando a.py")
    assert tool_line("Write", {"file_path": "b.py"}, ws) == ProgressLine("tool", "Criando b.py")


def test_display_path_flavors() -> None:
    assert display_path("C:\\work\\crew\\T-1\\src\\a.py", WINDOWS_WS) == "src/a.py"
    assert display_path("C:/work/crew/T-1/src/a.py", WINDOWS_WS) == "src/a.py"
    assert display_path("D:\\other\\a.py", WINDOWS_WS) == "D:/other/a.py"
    assert display_path("/etc/passwd", POSIX_WS) == "/etc/passwd"
    assert display_path("src\\a.py", None) == "src/a.py"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Vou ler o módulo de relatório. Depois edito.", "Vou ler o módulo de relatório."),
        ("Primeiro\nsegunda linha. Terceira.", "Primeiro segunda linha."),
        ("## Plano\nfazer **isso** com `código`.", "Plano fazer isso com código."),
        ("Sem ponto final", "Sem ponto final"),
        ("  \n ", None),
        ("", None),
    ],
)
def test_text_lines(raw: str, expected: str | None) -> None:
    line = text_line(raw)
    assert (line.text if line else None) == expected
    if line:
        assert line.kind == "text"


def test_text_line_is_truncated() -> None:
    line = text_line("a" * 500)
    assert line is not None
    assert len(line.text) == TEXT_MAX


def test_text_keeps_hash_inside_words() -> None:
    line = text_line("Implementando AB#4821 agora.")
    assert line is not None
    assert "AB#4821" in line.text


def test_map_message_handles_mixed_blocks() -> None:
    msg = AssistantMessage(
        content=[
            TextBlock(text="Vou editar o relatório. Em seguida rodo os testes."),
            ToolUseBlock(id="1", name="Edit", input={"file_path": f"{POSIX_WS}/shop/report.py"}),
            ToolUseBlock(id="2", name="Bash", input={"command": "pytest -q"}),
            ToolUseBlock(id="3", name="TodoWrite", input={}),
        ],
        model="m",
    )
    assert map_message(msg, POSIX_WS) == [
        ProgressLine("text", "Vou editar o relatório."),
        ProgressLine("tool", "Editando shop/report.py"),
        ProgressLine("tool", "$ pytest -q"),
    ]


def test_map_message_ignores_everything_else() -> None:
    result = ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="s",
    )
    assert map_message(result) == []
    assert map_message("not a message") == []


# ---------------------------------------------------------------------------------- throttle
class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def run_throttle(steps: list[tuple[float, ProgressLine]], flush: bool = True) -> list[str]:
    sent: list[str] = []
    clock = Clock()

    async def sink(line: ProgressLine) -> None:
        sent.append(line.text)

    throttle = ProgressThrottle(sink, min_interval_s=0.3, clock=clock)
    for advance, line in steps:
        clock.now += advance
        await throttle.push(line)
    if flush:
        await throttle.flush()
    return sent


def t(text: str) -> ProgressLine:
    return ProgressLine("tool", text)


def x(text: str) -> ProgressLine:
    return ProgressLine("text", text)


def s(text: str) -> ProgressLine:
    return ProgressLine("status", text)


async def test_first_event_goes_through_and_the_window_blocks_the_next() -> None:
    assert await run_throttle([(0, t("a")), (0.1, t("b")), (0.1, t("c"))], flush=False) == ["a"]


async def test_latest_tool_event_is_coalesced_and_sent_when_the_window_opens() -> None:
    sent = await run_throttle([(0, t("a")), (0.1, t("b")), (0.1, t("c")), (0.2, t("d"))], flush=False)
    assert sent == ["a", "c"]  # "b" was replaced by "c"; "d" waits for the next window


async def test_flush_sends_the_pending_tool_event() -> None:
    assert await run_throttle([(0, t("a")), (0.1, t("b"))]) == ["a", "b"]


async def test_text_inside_the_window_is_dropped() -> None:
    assert await run_throttle([(0, t("a")), (0.1, x("chatter")), (0.1, x("more"))]) == ["a"]


async def test_text_after_the_window_goes_through() -> None:
    assert await run_throttle([(0, t("a")), (0.5, x("hello"))]) == ["a", "hello"]


async def test_status_always_bypasses_the_throttle() -> None:
    sent = await run_throttle([(0, t("a")), (0.0, s("bloqueado: x")), (0.0, s("bloqueado: y"))])
    assert sent == ["a", "bloqueado: x", "bloqueado: y"]


async def test_at_most_one_event_per_interval_under_a_burst() -> None:
    steps = [(0.05, t(f"e{i}")) for i in range(40)]  # 2 seconds of events every 50ms
    sent = await run_throttle(steps, flush=False)
    assert len(sent) <= 2.0 / 0.3 + 2
    assert sent[0] == "e0"

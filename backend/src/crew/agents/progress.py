"""Deterministic mapping from SDK messages to short UI progress lines (no LLM involved)."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

from .submit import SERVER_NAME

ProgressKind = Literal["status", "tool", "text"]

BASH_MAX = 60
TEXT_MAX = 80
MIN_INTERVAL_S = 0.3
_SUBMIT_PREFIX = f"mcp__{SERVER_NAME}__submit_"
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")
_MARKDOWN_NOISE = re.compile(r"[`*]|^#+\s*", re.MULTILINE)


@dataclass(frozen=True)
class ProgressLine:
    kind: ProgressKind
    text: str


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def display_path(raw: str, workspace: str | None) -> str:
    """Path relative to the workspace (forward slashes) when it lives inside; else unchanged."""
    if not workspace:
        return raw.replace("\\", "/")
    flavor: type[PurePath] = PureWindowsPath if ("\\" in workspace or ":" in workspace[:3]) else PurePosixPath
    try:
        return flavor(raw).relative_to(flavor(workspace)).as_posix()
    except ValueError:
        return raw.replace("\\", "/")


def _first_line(text: str) -> str:
    return " ".join(text.strip().splitlines()[0].split()) if text.strip() else ""


def _resolve(raw: str, workspace: str | None) -> Path:
    path = Path(raw)
    return path if path.is_absolute() or not workspace else Path(workspace) / path


def tool_line(name: str, tool_input: dict[str, Any], workspace: str | None = None) -> ProgressLine | None:
    """Line for one tool call, or ``None`` when it is not worth showing (e.g. TodoWrite)."""
    if name.startswith(_SUBMIT_PREFIX):
        return ProgressLine("tool", "Enviando resultado")

    def path_of(*keys: str) -> str:
        for key in keys:
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                return display_path(value, workspace)
        return "?"

    match name:
        case "Read":
            return ProgressLine("tool", f"Lendo {path_of('file_path')}")
        case "Grep" | "Glob":
            pattern = tool_input.get("pattern")
            return ProgressLine("tool", f'Buscando "{truncate(str(pattern), 40)}"')
        case "Edit" | "MultiEdit" | "NotebookEdit":
            return ProgressLine("tool", f"Editando {path_of('file_path', 'notebook_path')}")
        case "Write":
            raw = tool_input.get("file_path")
            exists = isinstance(raw, str) and _resolve(raw, workspace).exists()
            verb = "Editando" if exists else "Criando"
            return ProgressLine("tool", f"{verb} {path_of('file_path')}")
        case "Bash":
            command = _first_line(str(tool_input.get("command", "")))
            return ProgressLine("tool", truncate(f"$ {command}", BASH_MAX))
        case "TodoWrite":
            return None
        case _:
            return ProgressLine("tool", f"Usando {name}")


def text_line(text: str) -> ProgressLine | None:
    """First sentence of an assistant text block, at most ``TEXT_MAX`` characters."""
    cleaned = " ".join(_MARKDOWN_NOISE.sub("", text).split())
    if not cleaned:
        return None
    first = _SENTENCE_END.split(cleaned, maxsplit=1)[0]
    return ProgressLine("text", truncate(first, TEXT_MAX))


def map_message(message: object, workspace: str | None = None) -> list[ProgressLine]:
    """Progress lines for one SDK message (only assistant messages produce any)."""
    if not isinstance(message, AssistantMessage):
        return []
    lines: list[ProgressLine] = []
    for block in message.content:
        line: ProgressLine | None = None
        if isinstance(block, ToolUseBlock):
            line = tool_line(block.name, block.input, workspace)
        elif isinstance(block, TextBlock):
            line = text_line(block.text)
        if line is not None:
            lines.append(line)
    return lines


ProgressSink = Callable[[ProgressLine], Awaitable[None]]


class ProgressThrottle:
    """At most one event per ``min_interval_s``.

    ``status`` lines always go through. ``text`` lines inside the window are dropped. ``tool`` lines
    inside the window are coalesced: the latest one is sent as soon as the window opens (or on ``flush``).
    """

    def __init__(
        self,
        sink: ProgressSink,
        min_interval_s: float = MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sink = sink
        self._interval = min_interval_s
        self._clock = clock
        self._last: float | None = None
        self._pending: ProgressLine | None = None

    def _open(self, now: float) -> bool:
        return self._last is None or now - self._last >= self._interval

    async def _send(self, line: ProgressLine, now: float) -> None:
        self._last = now
        await self._sink(line)

    async def push(self, line: ProgressLine) -> None:
        now = self._clock()
        if line.kind == "status":
            await self._sink(line)
            return
        if self._pending is not None and self._open(now):
            pending, self._pending = self._pending, None
            await self._send(pending, now)
        if self._open(now):
            await self._send(line, now)
        elif line.kind == "tool":
            self._pending = line

    async def flush(self) -> None:
        if self._pending is not None:
            pending, self._pending = self._pending, None
            await self._send(pending, self._clock())

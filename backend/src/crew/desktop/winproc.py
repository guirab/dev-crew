"""Windows process helpers for a launcher that has no console of its own (``pythonw.exe``).

A console program started from a GUI process pops a new console window. ``CREATE_NO_WINDOW`` gives
the child a hidden console instead, and its own children (git, docker, claude.exe) inherit it, so
nothing flashes on screen while the crew works.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any

IS_WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
ERROR_ALREADY_EXISTS = 183
MB_ICONERROR = 0x10
MB_SETFOREGROUND = 0x10000

PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
PROGRAM_FILES_X86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
EDGE_CANDIDATES = (
    PROGRAM_FILES_X86 / "Microsoft/Edge/Application/msedge.exe",
    PROGRAM_FILES / "Microsoft/Edge/Application/msedge.exe",
)
DOCKER_DESKTOP = PROGRAM_FILES / "Docker/Docker/Docker Desktop.exe"


def _no_window() -> int:
    return CREATE_NO_WINDOW if IS_WINDOWS else 0


def run_hidden(
    args: Sequence[str], *, cwd: Path | None = None, timeout: float = 60.0
) -> subprocess.CompletedProcess[str]:
    """Run to completion without a console window. Never raises on a non-zero exit code."""
    return subprocess.run(
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_no_window(),
        check=False,
    )


def spawn_hidden(
    args: Sequence[str], *, cwd: Path, log: IO[Any], env: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    """Start a long-lived child with a hidden console; stdout and stderr go to ``log``."""
    flags = (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP) if IS_WINDOWS else 0
    return subprocess.Popen(
        list(args),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=flags,
    )


def kill_tree(pid: int) -> None:
    """Kill ``pid`` and every descendant (agent CLIs, git). ``terminate()`` alone orphans them."""
    if IS_WINDOWS:
        run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=30)
    else:  # pragma: no cover - the app is Windows-only; kept so tests can run elsewhere
        os.kill(pid, 9)


def find_edge() -> Path | None:
    for path in EDGE_CANDIDATES:
        if path.is_file():
            return path
    found = shutil.which("msedge")
    return Path(found) if found else None


def open_app_window(url: str) -> None:
    """Open ``url`` as a standalone window (Edge ``--app``: no tabs, no address bar)."""
    edge = find_edge()
    if edge is not None:
        subprocess.Popen([str(edge), f"--app={url}"], creationflags=_no_window())
    else:
        import webbrowser

        webbrowser.open(url)


def open_path(path: Path) -> None:
    """Open a file or folder with its default program (Explorer for folders)."""
    if IS_WINDOWS:
        os.startfile(path)
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", str(path)])


def acquire_single_instance(name: str) -> bool:
    """Named mutex held until the process exits. ``False`` when another instance already holds it."""
    if not IS_WINDOWS:  # pragma: no cover
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, f"Local\\{name}")
    if not handle:
        return True  # cannot tell: let this instance run rather than block the user
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _MUTEX_HANDLES.append(handle)
    return True


_MUTEX_HANDLES: list[int] = []


def message_box(text: str, title: str = "Dev Crew") -> None:
    """Blocking error dialog: the only way to tell the user something before the tray icon exists."""
    if IS_WINDOWS:
        ctypes.windll.user32.MessageBoxW(None, text, title, MB_ICONERROR | MB_SETFOREGROUND)
    else:  # pragma: no cover
        print(f"{title}: {text}", file=sys.stderr)

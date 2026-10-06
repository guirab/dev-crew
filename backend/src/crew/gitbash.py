"""Locate Git Bash on Windows. ``C:\\Windows\\System32\\bash.exe`` is the WSL launcher, never Git Bash."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

GIT_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


def is_wsl_launcher(path: str) -> bool:
    return Path(path).parent.name.lower() == "system32"


def find_git_bash() -> str | None:
    if sys.platform != "win32":
        return shutil.which("bash")
    found = next((p for p in GIT_BASH_CANDIDATES if Path(p).is_file()), None)
    if found:
        return found
    git = shutil.which("git")
    if git:
        # <Git>/cmd/git.exe -> <Git>/bin/bash.exe
        sibling = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if sibling.is_file():
            return str(sibling)
    on_path = shutil.which("bash")
    return on_path if on_path and not is_wsl_launcher(on_path) else None

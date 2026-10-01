"""Thin async wrapper over the ``git`` CLI (no GitPython). Always ``pathlib``, never a shell."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 60.0


class GitError(RuntimeError):
    def __init__(self, args: tuple[str, ...], returncode: int, stderr: str) -> None:
        self.git_args = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"git {' '.join(args)} falhou ({returncode}): {self.stderr}")


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


def _run_sync(cwd: Path, args: tuple[str, ...], timeout: float) -> GitResult:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # never block on a credential prompt
    )
    return GitResult(
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


async def run(cwd: Path, *args: str, timeout: float = DEFAULT_TIMEOUT_S, check: bool = True) -> GitResult:
    """Run ``git <args>`` in ``cwd`` off the event loop. Raises ``GitError`` when ``check`` and rc != 0."""
    try:
        res = await asyncio.to_thread(_run_sync, cwd, args, timeout)
    except subprocess.TimeoutExpired as e:
        raise GitError(args, -1, f"timeout após {timeout:g}s") from e
    except FileNotFoundError as e:
        raise GitError(args, -1, "git não encontrado no PATH") from e
    if check and res.returncode != 0:
        raise GitError(args, res.returncode, res.stderr or res.stdout)
    return res


async def out(cwd: Path, *args: str, timeout: float = DEFAULT_TIMEOUT_S) -> str:
    """stdout of a successful git command, stripped."""
    return (await run(cwd, *args, timeout=timeout)).stdout.strip()


async def ok(cwd: Path, *args: str, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """True when the command exits 0 (never raises on non-zero)."""
    return (await run(cwd, *args, timeout=timeout, check=False)).returncode == 0

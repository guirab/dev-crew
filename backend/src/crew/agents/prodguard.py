"""Diff after the Tester (D42): the Tester may only change test files.

The guards stop ``Write``/``Edit`` outside the test globs, but a script the Tester runs could still
rewrite production code. So the worker hashes every non-test file of the worktree before and after the
Tester job; any difference fails the job, which the orchestrator turns into an escalation for the human.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from .pathjail import matches_any_glob

Snapshot = dict[str, str]  # relative path -> sha1 of the content


def snapshot(workspace: Path, test_globs: tuple[str, ...]) -> Snapshot:
    """Hash of every tracked or untracked (not ignored) file that is not a test file."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=workspace,
        capture_output=True,
        timeout=60,
        check=True,
    )
    ignore_case = sys.platform == "win32"
    out: Snapshot = {}
    for rel in sorted(set(listed.stdout.decode("utf-8", errors="replace").split("\0")) - {""}):
        if matches_any_glob(rel, test_globs, ignore_case=ignore_case):
            continue
        path = workspace / rel
        out[rel] = (
            hashlib.sha1(path.read_bytes(), usedforsecurity=False).hexdigest() if path.is_file() else ""
        )
    return out


def changed(before: Snapshot, after: Snapshot) -> list[str]:
    """Production files created, edited or deleted between the two snapshots."""
    return sorted(rel for rel in before.keys() | after.keys() if before.get(rel) != after.get(rel))


def describe(files: list[str], limit: int = 8) -> str:
    shown = ", ".join(files[:limit])
    more = f" (+{len(files) - limit})" if len(files) > limit else ""
    return f"o Tester alterou código de produção: {shown}{more}. Revise antes de seguir."

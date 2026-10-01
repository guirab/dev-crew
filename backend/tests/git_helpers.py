"""Throwaway git repositories for workspace tests. Everything lives under pytest's ``tmp_path``."""

from __future__ import annotations

import subprocess
from pathlib import Path


def sh_git(cwd: Path, *args: str) -> str:
    """Run git in a temp repo (tests only; never touches anything outside ``tmp_path``)."""
    proc = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8", errors="replace").strip()


def make_git_repo(root: Path, name: str = "sample-repo") -> Path:
    """Repo on ``main`` with one commit: ``app.py`` (3 lines), ``README.md`` and ``gone.txt``."""
    repo = root / name
    repo.mkdir(parents=True)
    sh_git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text("a\nb\nc\n", "utf-8")
    (repo / "README.md").write_text("# hi\n", "utf-8")
    (repo / "gone.txt").write_text("1\n2\n", "utf-8")
    sh_git(repo, "add", "-A")
    sh_git(repo, "commit", "-q", "-m", "init")
    return repo

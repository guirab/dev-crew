"""Materialize ``fixtures/sample-repo`` (stored without ``.git``) as a real git repo on ``main``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SAMPLE_REPO = REPO_ROOT / "fixtures" / "sample-repo"
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git")
AUTHOR = ["-c", "user.name=dev-crew", "-c", "user.email=dev-crew@localhost"]


def _git(dest: Path, *args: str) -> None:
    subprocess.run(["git", *AUTHOR, *args], cwd=dest, check=True, capture_output=True, text=True)


def init_sample_repo(dest: Path, source: Path = SAMPLE_REPO) -> Path:
    """Copy ``source`` to ``dest`` (must not exist or be empty), init on ``main`` with one commit."""
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"destination is not empty: {dest}")
    if not source.is_dir():
        raise FileNotFoundError(f"sample repo not found: {source}")
    shutil.copytree(source, dest, ignore=IGNORE, dirs_exist_ok=True)
    _git(dest, "init", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-m", "chore: initial commit")
    return dest

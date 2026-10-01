"""Copy fixtures/sample-repo to <dest> and create a git repo there (branch main, one commit).

Usage: uv run python scripts/init_sample_repo.py <dest>

The sample repo is stored without a .git directory (a nested repo would break the parent repo),
so every test or manual run materializes a fresh copy with this script.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SAMPLE_REPO = Path(__file__).resolve().parents[2] / "fixtures" / "sample-repo"
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git")
AUTHOR = ["-c", "user.name=dev-crew", "-c", "user.email=dev-crew@localhost"]


def _git(dest: Path, *args: str) -> None:
    subprocess.run(["git", *AUTHOR, *args], cwd=dest, check=True, capture_output=True, text=True)


def init_sample_repo(dest: Path, source: Path = SAMPLE_REPO) -> Path:
    """Materialize the sample repo at ``dest`` (must not exist or be empty)."""
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"destination is not empty: {dest}")
    if not source.is_dir():
        raise FileNotFoundError(f"sample repo not found: {source}")
    shutil.copytree(source, dest, ignore=IGNORE, dirs_exist_ok=True)
    _git(dest, "init", "-b", "main")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-m", "chore: initial commit")
    return dest


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: init_sample_repo.py <dest>", file=sys.stderr)
        return 2
    try:
        dest = init_sample_repo(Path(argv[1]).resolve())
    except (FileExistsError, FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"sample repo ready at {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Copy fixtures/sample-repo to <dest> and create a git repo there (branch main, one commit).

Usage: uv run python scripts/init_sample_repo.py <dest>

The sample repo is stored without a .git directory (a nested repo would break the parent repo),
so every test or manual run materializes a fresh copy with this script.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from crew.agents.sample import SAMPLE_REPO, init_sample_repo

__all__ = ["SAMPLE_REPO", "init_sample_repo", "main"]


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

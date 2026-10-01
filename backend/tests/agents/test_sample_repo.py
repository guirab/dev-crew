"""The sample repo fixture and the script that materializes it as a git repo."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "init_sample_repo.py"
SAMPLE = BACKEND.parent / "fixtures" / "sample-repo"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=False)


def test_sample_repo_has_no_nested_git_dir() -> None:
    assert not (SAMPLE / ".git").exists()


def test_init_creates_repo_on_main_with_one_clean_commit(tmp_path: Path) -> None:
    dest = tmp_path / "repo"
    proc = _run(sys.executable, str(SCRIPT), str(dest), cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr

    assert _run("git", "branch", "--show-current", cwd=dest).stdout.strip() == "main"
    assert _run("git", "rev-list", "--count", "HEAD", cwd=dest).stdout.strip() == "1"
    assert _run("git", "status", "--porcelain", cwd=dest).stdout.strip() == ""
    tracked = set(_run("git", "ls-files", cwd=dest).stdout.split())
    assert {"shop/report.py", "tests/test_report.py", "pyproject.toml"} <= tracked


def test_init_refuses_non_empty_destination(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    proc = _run(sys.executable, str(SCRIPT), str(tmp_path), cwd=tmp_path)
    assert proc.returncode == 1
    assert "not empty" in proc.stderr


def test_sample_suite_passes_in_materialized_copy(tmp_path: Path) -> None:
    dest = tmp_path / "repo"
    assert _run(sys.executable, str(SCRIPT), str(dest), cwd=tmp_path).returncode == 0
    proc = _run(sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", cwd=dest)
    assert proc.returncode == 0, proc.stdout + proc.stderr

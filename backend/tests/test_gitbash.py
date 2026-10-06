from __future__ import annotations

import sys
from pathlib import Path

import pytest

from crew import gitbash


def test_system32_bash_is_the_wsl_launcher() -> None:
    assert gitbash.is_wsl_launcher(r"C:\WINDOWS\system32\bash.EXE")
    assert not gitbash.is_wsl_launcher(r"C:\Program Files\Git\bin\bash.exe")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_find_git_bash_skips_wsl_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gitbash, "GIT_BASH_CANDIDATES", ())
    monkeypatch.setattr(
        gitbash.shutil,
        "which",
        lambda name: r"C:\WINDOWS\system32\bash.EXE" if name == "bash" else None,
    )
    assert gitbash.find_git_bash() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_find_git_bash_derives_from_git_exe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "cmd").mkdir()
    (tmp_path / "bin").mkdir()
    git = tmp_path / "cmd" / "git.exe"
    bash = tmp_path / "bin" / "bash.exe"
    git.write_bytes(b"")
    bash.write_bytes(b"")
    monkeypatch.setattr(gitbash, "GIT_BASH_CANDIDATES", ())
    monkeypatch.setattr(gitbash.shutil, "which", lambda name: str(git) if name == "git" else None)
    assert gitbash.find_git_bash() == str(bash.resolve())

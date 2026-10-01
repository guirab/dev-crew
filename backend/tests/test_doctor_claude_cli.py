from __future__ import annotations

from pathlib import Path

import pytest

from crew import doctor


def test_override_must_exist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / "claude.exe"
    monkeypatch.setenv("CREW_CLAUDE_CLI", str(exe))
    assert doctor.find_claude_cli() is None
    exe.write_bytes(b"")
    assert doctor.find_claude_cli() == str(exe)


def test_npm_shim_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CREW_CLAUDE_CLI", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: r"C:\npm\claude.cmd")
    assert doctor.find_claude_cli() is None


async def test_missing_cli_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "find_claude_cli", lambda: None)
    check = await doctor.check_claude_cli()
    assert check.status == "fail" and "CREW_CLAUDE_CLI" in check.hint

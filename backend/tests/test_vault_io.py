"""D82: host side of the standards job (vault copy in, base out, exclude, cleanup)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew.vaults import STANDARDS_OUT, VAULT_COPY, VaultInfo
from crew.workspace import git, vault_io

from .git_helpers import make_git_repo, sh_git


def _write(path: Path, text: str = "x\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


def _info(vault: Path, *, workspace: bool = False, repo: str = "api") -> VaultInfo:
    base = vault / "standards"
    return VaultInfo(
        vault=vault,
        layout="workspace" if workspace else "single",
        project="proj",
        repo=repo,
        standards_dir=base / repo if workspace else base,
        exists=vault.is_dir(),
    )


def test_stage_copies_only_the_notes_and_makes_the_out_folder(tmp_path: Path) -> None:
    vault, ws = tmp_path / "vault", tmp_path / "wt"
    _write(vault / "Home.md")
    _write(vault / "standards" / "Glossary.md")
    _write(vault / "sessions" / "2026-11-01.md")
    _write(vault / ".obsidian" / "workspace.md")
    _write(vault / ".trash" / "old.md")
    _write(vault / "img.png")
    _write(ws / ".crew" / "vault" / "stale.md")  # a leftover from an earlier run is replaced
    assert vault_io.stage(ws, vault) == 3
    copied = sorted(p.relative_to(ws / VAULT_COPY).as_posix() for p in (ws / VAULT_COPY).rglob("*.md"))
    assert copied == ["Home.md", "sessions/2026-11-01.md", "standards/Glossary.md"]
    assert (ws / STANDARDS_OUT).is_dir() and not any((ws / STANDARDS_OUT).iterdir())


def test_stage_without_a_vault_leaves_the_copy_empty(tmp_path: Path) -> None:
    ws = tmp_path / "wt"
    assert vault_io.stage(ws, tmp_path / "nope") == 0
    assert (ws / VAULT_COPY).is_dir() and not any((ws / VAULT_COPY).iterdir())


def test_stage_caps_the_copy_keeping_standards_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, ws = tmp_path / "vault", tmp_path / "wt"
    for name in ("a.md", "b.md", "c.md"):
        _write(vault / name)
    _write(vault / "standards" / "Conventions.md")
    monkeypatch.setattr(vault_io, "MAX_FILES", 2)
    assert vault_io.stage(ws, vault) == 2
    assert (ws / VAULT_COPY / "standards" / "Conventions.md").is_file()
    assert (ws / VAULT_COPY / "a.md").is_file() and not (ws / VAULT_COPY / "c.md").exists()


def test_cleanup_removes_the_crew_folder(tmp_path: Path) -> None:
    ws = tmp_path / "wt"
    vault_io.stage(ws, tmp_path / "nope")
    vault_io.cleanup(ws)
    assert not (ws / ".crew").exists()
    vault_io.cleanup(ws)  # idempotent


async def test_crew_folder_never_shows_in_git_status_of_a_worktree(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path)
    wt = tmp_path / "wt"
    sh_git(repo, "worktree", "add", "-q", "-b", "crew/T-1", str(wt))
    vault_io.stage(wt, tmp_path / "nope")
    _write(wt / STANDARDS_OUT / "Glossary.md")
    assert ".crew" in await git.out(wt, "status", "--porcelain", "--untracked-files=all")
    await vault_io.exclude_crew_dir(wt)
    await vault_io.exclude_crew_dir(wt)  # once
    assert await git.out(wt, "status", "--porcelain", "--untracked-files=all") == ""
    exclude = Path(await git.out(wt, "rev-parse", "--git-common-dir"))
    exclude = exclude if exclude.is_absolute() else wt / exclude
    lines = (exclude / "info" / "exclude").read_text("utf-8").splitlines()
    assert lines.count("/.crew/") == 1


def test_publish_creates_the_vault_with_home_and_copies_the_base(tmp_path: Path) -> None:
    ws, vault = tmp_path / "wt", tmp_path / "Vaults" / "app-vault"
    vault_io.stage(ws, vault)
    out = ws / STANDARDS_OUT
    _write(out / "Before You Develop.md", "# Before You Develop: app\n")
    _write(out / "Glossary.md")
    _write(out / "decisions" / "ADR-0001 - Use NATS.md")
    info = _info(vault, repo="app")
    assert not info.exists
    files = vault_io.publish(ws, info)
    assert files == ["Before You Develop.md", "Glossary.md", "decisions/ADR-0001 - Use NATS.md"]
    assert (vault / ".obsidian").is_dir()
    home = (vault / "Home.md").read_text("utf-8")
    assert home.startswith("# proj\n") and "[[standards/Before You Develop|Before You Develop]]" in home
    assert (vault / "standards" / "Before You Develop.md").read_text("utf-8") == "# Before You Develop: app\n"
    assert (vault / "standards" / "decisions" / "ADR-0001 - Use NATS.md").is_file()


def test_publish_drops_anything_formats_md_does_not_define(tmp_path: Path) -> None:
    ws, vault = tmp_path / "wt", tmp_path / "vault"
    vault.mkdir()
    vault_io.stage(ws, vault)
    out = ws / STANDARDS_OUT
    _write(out / "Conventions.md")
    for bad in ("notes.md", "script.py", "Home.md", "decisions/ADR-1 - Short.md", "deep/a/Glossary.md"):
        _write(out / bad)
    (out / "binary.md").write_bytes(b"\xff\xfe\x00")
    info = _info(vault, repo="app")
    assert vault_io.publish(ws, info) == ["Conventions.md"]
    assert sorted(p.name for p in (vault / "standards").rglob("*") if p.is_file()) == ["Conventions.md"]
    assert not (vault / "Home.md").exists()  # existing vault: dev-crew does not touch its hub


def test_publish_workspace_writes_the_repo_folder_and_extends_project_files(tmp_path: Path) -> None:
    ws, vault = tmp_path / "wt", tmp_path / "vault"
    _write(vault / "standards" / "Glossary.md", "old\n")
    _write(vault / "standards" / "web" / "Conventions.md", "web only\n")
    vault_io.stage(ws, vault)
    out = ws / STANDARDS_OUT
    _write(out / "Glossary.md", "old + api terms\n")
    _write(out / "api" / "Before You Develop.md")
    _write(out / "api" / "Conventions.md")
    _write(out / "Before You Develop.md")  # project level has no Before You Develop in a workspace
    _write(out / "web" / "Conventions.md", "clobbered\n")  # another repo's folder: never
    files = vault_io.publish(ws, _info(vault, workspace=True))
    assert files == ["Glossary.md", "api/Before You Develop.md", "api/Conventions.md"]  # sorted
    assert (vault / "standards" / "Glossary.md").read_text("utf-8") == "old + api terms\n"
    assert (vault / "standards" / "web" / "Conventions.md").read_text("utf-8") == "web only\n"
    assert not (vault / "standards" / "Before You Develop.md").exists()


def test_publish_without_a_valid_file_fails_and_writes_nothing(tmp_path: Path) -> None:
    ws, vault = tmp_path / "wt", tmp_path / "vault"
    vault_io.stage(ws, vault)
    _write(ws / STANDARDS_OUT / "random.txt")
    with pytest.raises(vault_io.VaultIOError):
        vault_io.publish(ws, _info(vault))
    assert not vault.exists()


def test_workspace_home_links_the_repo(tmp_path: Path) -> None:
    home = vault_io.home_note(_info(tmp_path / "v", workspace=True))
    assert "[[standards/api/Before You Develop|api]]" in home and "[[standards/Glossary|Glossary]]" in home


def test_fake_base_is_a_valid_single_repo_base(tmp_path: Path) -> None:
    ws, vault = tmp_path / "wt", tmp_path / "vault"
    files = vault_io.write_fake_base(ws, "app")
    assert vault_io.publish(ws, _info(vault, repo="app")) == sorted(files)

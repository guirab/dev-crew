"""Folder browsing for "add an existing repository": listing and git probe (real git in tmp_path)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew import folders
from crew.config import CrewConfig, RepoCfg, WorkspaceCfg

from .git_helpers import make_git_repo, sh_git


def make_cfg(projects_dir: Path, *registered: Path) -> CrewConfig:
    return CrewConfig(
        workspace=WorkspaceCfg(root=projects_dir / "_wt", projects_dir=projects_dir),
        repos=[RepoCfg(name=f"r{i}", path=p, test_cmd="pytest") for i, p in enumerate(registered)],
    )


def names(listing: folders.FolderListing) -> list[str]:
    return [e.name for e in listing.entries]


def test_without_path_starts_at_the_projects_dir(tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    listing = folders.list_folders(None, make_cfg(tmp_path))
    assert listing.path == str(tmp_path.resolve())
    assert names(listing) == ["alpha"]


def test_lists_only_visible_subfolders_sorted_ignoring_case(tmp_path: Path) -> None:
    for d in ("beta", "Alpha", "gamma", ".hidden"):
        (tmp_path / d).mkdir()
    (tmp_path / "file.txt").write_text("x", "utf-8")
    listing = folders.list_folders(str(tmp_path), make_cfg(tmp_path))
    assert names(listing) == ["Alpha", "beta", "gamma"]
    assert all(Path(e.path).is_dir() for e in listing.entries)


def test_parent_goes_up_and_the_root_has_none(tmp_path: Path) -> None:
    sub = tmp_path / "a"
    sub.mkdir()
    cfg = make_cfg(tmp_path)
    assert folders.list_folders(str(sub), cfg).parent == str(tmp_path.resolve())
    root = Path(tmp_path.resolve().anchor)
    assert folders.list_folders(str(root), cfg).parent is None


def test_drives_level_lists_the_drives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(folders, "_windows", lambda: True)
    monkeypatch.setattr(folders, "list_drives", lambda: ["C:\\", "D:\\"])
    listing = folders.list_folders("", make_cfg(tmp_path))
    assert listing.path == "" and listing.parent is None
    assert [(e.name, e.path) for e in listing.entries] == [("C:", "C:\\"), ("D:", "D:\\")]


def test_drive_root_goes_up_to_the_drives_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(folders, "_windows", lambda: True)
    root = Path(tmp_path.resolve().anchor)
    assert folders.list_folders(str(root), make_cfg(tmp_path)).parent == ""


def test_empty_path_off_windows_lists_the_root(tmp_path: Path) -> None:
    listing = folders.list_folders("", make_cfg(tmp_path))
    assert listing.path == folders.list_drives()[0] and listing.parent is None


def test_inaccessible_folders_are_left_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "open").mkdir()
    (tmp_path / "locked").mkdir()
    monkeypatch.setattr(folders, "_can_open", lambda p: not p.endswith("locked"))
    assert names(folders.list_folders(str(tmp_path), make_cfg(tmp_path))) == ["open"]


def test_hidden_and_system_folders_are_left_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "plain").mkdir()
    (tmp_path / "junction").mkdir()
    monkeypatch.setattr(folders, "_hidden_by_system", lambda e: e.name == "junction")
    assert names(folders.list_folders(str(tmp_path), make_cfg(tmp_path))) == ["plain"]


def test_marks_git_repos_and_registered_folders(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "repo")
    (tmp_path / "plain").mkdir()
    cfg = make_cfg(tmp_path, repo)
    by_name = {e.name: e for e in folders.list_folders(str(tmp_path), cfg).entries}
    assert by_name["repo"].git_repo and by_name["repo"].registered
    assert not by_name["plain"].git_repo and not by_name["plain"].registered


def test_registered_is_decided_by_normalized_path(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "repo")
    cfg = make_cfg(tmp_path, tmp_path / "other" / ".." / "repo")
    assert folders.is_registered_path(cfg, repo)
    assert folders.is_registered_path(cfg, str(repo) + "/")
    assert not folders.is_registered_path(cfg, tmp_path)


def test_missing_relative_and_file_paths_are_errors(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    (tmp_path / "f.txt").write_text("x", "utf-8")
    with pytest.raises(folders.FolderError, match="não existe"):
        folders.list_folders(str(tmp_path / "nada"), cfg)
    with pytest.raises(folders.FolderError, match="não é uma pasta"):
        folders.list_folders(str(tmp_path / "f.txt"), cfg)
    with pytest.raises(folders.FolderError, match="absoluto"):
        folders.list_folders("relativo/x", cfg)


# ------------------------------------------------------------------ probe


async def test_probe_none_for_a_plain_folder(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    p = await folders.probe(str(tmp_path / "plain"), make_cfg(tmp_path))
    assert (p.git, p.branch, p.name, p.registered) == ("none", None, "plain", False)


async def test_probe_empty_repo_reports_its_branch(tmp_path: Path) -> None:
    repo = tmp_path / "vazio"
    repo.mkdir()
    sh_git(repo, "init", "-q", "-b", "trunk")
    p = await folders.probe(str(repo), make_cfg(tmp_path))
    assert (p.git, p.branch) == ("empty", "trunk")


async def test_probe_ready_repo_reports_the_current_branch(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "pronto")
    sh_git(repo, "switch", "-q", "-c", "feature")
    p = await folders.probe(str(repo), make_cfg(tmp_path, repo))
    assert (p.git, p.branch, p.registered) == ("ready", "feature", True)


async def test_probe_detached_head_has_no_branch(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "solto")
    sh_git(repo, "checkout", "-q", "--detach")
    assert (await folders.probe(str(repo), make_cfg(tmp_path))).branch is None


async def test_probe_subfolder_of_a_repo_is_inside_repo(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path, "pai")
    (repo / "sub").mkdir()
    p = await folders.probe(str(repo / "sub"), make_cfg(tmp_path))
    assert p.git == "inside_repo" and p.branch is None


async def test_probe_missing_folder_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(folders.FolderError):
        await folders.probe(str(tmp_path / "nada"), make_cfg(tmp_path))

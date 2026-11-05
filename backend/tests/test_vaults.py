"""D82: where a repo's vault and standards base live (``crew.vaults``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew import vaults


def _git(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(vaults.VAULTS_ROOT_ENV, raising=False)
    home = tmp_path / "home"
    (home / "Documents" / "Vaults").mkdir(parents=True)
    return home


def test_override_from_the_config_wins(home: Path) -> None:
    repo = _git(home / "Documents" / "app")
    (repo / vaults.LINK_FILE).write_text(str(home / "elsewhere"), "utf-8")
    single = vaults.resolve(repo, home / "v" / "standards", home=home)
    assert single.standards_dir == home / "v" / "standards" and single.layout == "single"
    assert single.vault == home / "v" and single.root == home / "v" / "standards"
    ws = vaults.resolve(repo, home / "v" / "standards" / "app", home=home)
    assert ws.layout == "workspace" and ws.root == home / "v" / "standards" and ws.vault == home / "v"


def test_link_file_at_the_repo_root(home: Path) -> None:
    repo = _git(home / "Documents" / "app")
    target = home / "Documents" / "Vaults" / "custom"
    target.mkdir()
    (repo / vaults.LINK_FILE).write_text(f"  {target}\n", "utf-8")
    info = vaults.resolve(repo, home=home)
    assert info.vault == target and info.exists and info.standards_dir == target / "standards"
    assert vaults.resolve(repo, home=home, links=False).vault != target


def test_project_vault_then_plain_name_case_insensitive(home: Path) -> None:
    repo = _git(home / "Documents" / "MeuCanto")
    root = home / "Documents" / "Vaults"
    (root / "MeuCanto").mkdir()
    assert vaults.resolve(repo, home=home).vault == root / "MeuCanto"
    (root / "meucanto-VAULT").mkdir()
    info = vaults.resolve(repo, home=home)
    assert info.vault == root / "meucanto-VAULT" and info.exists and info.layout == "single"


def test_no_vault_points_to_the_one_to_create(home: Path) -> None:
    repo = _git(home / "Documents" / "app")
    info = vaults.resolve(repo, home=home)
    assert info.vault == home / "Documents" / "Vaults" / "app-vault" and not info.exists
    assert info.project == "app" and info.standards_dir == info.vault / "standards"


def test_workspace_project_uses_the_parent_name_and_the_repo_folder(home: Path) -> None:
    ws = home / "Documents" / "PC-REMOTE"
    api = _git(ws / "api")
    _git(ws / "web")
    (home / "Documents" / "Vaults" / "PC-REMOTE").mkdir()
    info = vaults.resolve(api, home=home)
    assert info.layout == "workspace" and info.project == "PC-REMOTE" and info.repo == "api"
    assert info.standards_dir == home / "Documents" / "Vaults" / "PC-REMOTE" / "standards" / "api"
    assert info.root == info.vault / "standards"


def test_workspace_link_file_in_the_workspace_folder(home: Path) -> None:
    ws = home / "code" / "proj"
    api = _git(ws / "api")
    _git(ws / "web")
    (ws / vaults.LINK_FILE).write_text(str(home / "pv"), "utf-8")
    assert vaults.resolve(api, home=home).vault == home / "pv"


def test_repos_loose_in_documents_or_home_are_single_repo(home: Path) -> None:
    repo = _git(home / "Documents" / "dev-crew")
    _git(home / "Documents" / "MeuCanto")
    assert not vaults.is_workspace(repo, home)
    loose = _git(home / "tool")
    _git(home / "other")
    assert not vaults.is_workspace(loose, home)
    spanish = _git(home / "Documentos" / "app")
    _git(home / "Documentos" / "b")
    assert not vaults.is_workspace(spanish, home)


def test_vaults_root_accepts_documentos_and_lowercase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(vaults.VAULTS_ROOT_ENV, raising=False)
    home = tmp_path / "h"
    (home / "Documentos" / "vaults").mkdir(parents=True)
    assert vaults.vaults_roots(home) == [home / "Documentos" / "vaults"]
    bare = tmp_path / "bare"
    bare.mkdir()
    assert vaults.vaults_roots(bare) == [bare / "Documents" / "Vaults"]
    monkeypatch.setenv(vaults.VAULTS_ROOT_ENV, str(tmp_path / "iso"))
    assert vaults.vaults_roots(home) == [tmp_path / "iso"]

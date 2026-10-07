"""add_repo: register an existing local git repository (service level, real git, isolated registry)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from crew import contracts as c
from crew import projects
from crew.config import CrewConfig, GatewayCfg, RepoCfg, WorkspaceCfg
from crew.orchestrator.service import OrchestratorService
from crew.orchestrator.store import Store
from crew.workspace.manager import WorkspaceManager

from .git_helpers import make_git_repo, sh_git


@pytest.fixture
def svc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> OrchestratorService:
    monkeypatch.setenv("CREW_HOME", str(tmp_path / "home"))
    existing = make_git_repo(tmp_path / "repos", "sample-repo")
    cfg = CrewConfig(
        gateway=GatewayCfg(),
        workspace=WorkspaceCfg(root=tmp_path / "wt", projects_dir=tmp_path / "repos"),
        repos=[RepoCfg(name="sample-repo", path=existing, test_cmd="pytest -q")],
    )
    return OrchestratorService(MagicMock(), cfg, Store(None), WorkspaceManager(cfg.workspace.root))


def cmd(path: Path, **kw: object) -> c.AddRepo:
    fields: dict[str, object] = {"name": "meu-app", "path": str(path), "test_cmd": "npm test"}
    return c.AddRepo.model_validate({**fields, **kw})


def registry_names() -> list[str]:
    return [r.name for r in projects.load_registered()]


async def test_adds_an_existing_repo(svc: OrchestratorService, tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "outros", "meu-app")
    reply = await svc._add_repo(
        cmd(
            repo,
            lint_cmd="npm run lint",
            setup_cmd="npm ci",
            sandbox_image="node:22",
            deps_dirs=["node_modules", " "],
        )
    )
    assert reply.ok and reply.view is None and reply.error is None
    (saved,) = projects.load_registered()
    assert (saved.name, saved.base_branch, saved.test_cmd) == ("meu-app", "main", "npm test")
    assert (saved.lint_cmd, saved.setup_cmd, saved.sandbox_image) == ("npm run lint", "npm ci", "node:22")
    assert saved.deps_dirs == ["node_modules"] and not saved.new_project
    assert svc.cfg.has_repo("meu-app") and svc.state is None
    assert [r.name for r in svc.cfg.repo_infos()] == ["sample-repo", "meu-app"]


async def test_blank_optional_commands_are_stored_as_none(svc: OrchestratorService, tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "outros", "meu-app")
    assert (await svc._add_repo(cmd(repo, lint_cmd="  ", setup_cmd="", sandbox_image=None))).ok
    saved = svc.cfg.repo("meu-app")
    assert saved.lint_cmd is None and saved.setup_cmd is None and saved.sandbox_image is None


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"name": "a b"}, "nome de projeto inválido"),
        ({"name": "sample-repo"}, "já existe um repositório"),
        ({"test_cmd": "  "}, "test_cmd"),
        ({"base_branch": "nao-existe"}, "não existe"),
        ({"base_branch": "-x"}, "branch base inválido"),
        ({"deps_dirs": ["../fora"]}, "deps_dirs"),
    ],
)
async def test_rejections_leave_the_registry_alone(
    svc: OrchestratorService, tmp_path: Path, override: dict[str, object], message: str
) -> None:
    repo = make_git_repo(tmp_path / "outros", "meu-app")
    reply = await svc._add_repo(cmd(repo, **override))
    assert not reply.ok and reply.error is not None and message in reply.error
    assert registry_names() == [] and [r.name for r in svc.cfg.repos] == ["sample-repo"]


async def test_path_already_registered_under_another_name(svc: OrchestratorService) -> None:
    reply = await svc._add_repo(cmd(svc.cfg.repo("sample-repo").path, name="outro-nome"))
    assert not reply.ok and reply.error is not None and "já está cadastrada" in reply.error
    assert registry_names() == []


async def test_missing_folder_and_file_are_rejected(svc: OrchestratorService, tmp_path: Path) -> None:
    (tmp_path / "arquivo.txt").write_text("x", "utf-8")
    missing = await svc._add_repo(cmd(tmp_path / "nada"))
    assert not missing.ok and missing.error is not None and "não existe" in missing.error
    a_file = await svc._add_repo(cmd(tmp_path / "arquivo.txt"))
    assert not a_file.ok and a_file.error is not None and "não é uma pasta" in a_file.error
    assert registry_names() == []


async def test_subfolder_of_another_repo_is_rejected_even_with_init_git(
    svc: OrchestratorService, tmp_path: Path
) -> None:
    parent = make_git_repo(tmp_path / "outros", "pai")
    (parent / "sub").mkdir()
    for init in (False, True):
        reply = await svc._add_repo(cmd(parent / "sub", init_git=init))
        assert not reply.ok and reply.error is not None and "subpasta de outro repositório" in reply.error
    assert not (parent / "sub" / ".git").exists() and registry_names() == []


async def test_folder_without_git_is_rejected_until_init_git(
    svc: OrchestratorService, tmp_path: Path
) -> None:
    folder = tmp_path / "outros" / "meu-app"
    folder.mkdir(parents=True)
    (folder / "main.py").write_text("print(1)\n", "utf-8")
    reply = await svc._add_repo(cmd(folder))
    assert not reply.ok and reply.error is not None and "não é um repositório git" in reply.error
    assert "inicializar o git" in reply.error
    assert not (folder / ".git").exists() and registry_names() == []


async def test_init_git_makes_an_empty_commit_and_keeps_the_files_untracked(
    svc: OrchestratorService, tmp_path: Path
) -> None:
    folder = tmp_path / "outros" / "meu-app"
    (folder / "src").mkdir(parents=True)
    (folder / "main.py").write_text("print(1)\n", "utf-8")
    (folder / "src" / "a.py").write_text("a = 1\n", "utf-8")

    reply = await svc._add_repo(cmd(folder, base_branch="trunk", init_git=True))

    assert reply.ok, reply.error
    assert sh_git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "trunk"
    assert sh_git(folder, "rev-list", "--count", "HEAD") == "1"
    assert (
        sh_git(folder, "show", "--stat", "--format=%s", "HEAD") == "chore: início do repositório no dev-crew"
    )
    assert sh_git(folder, "ls-tree", "-r", "--name-only", "HEAD") == ""
    assert sorted(sh_git(folder, "status", "--porcelain").splitlines()) == ["?? main.py", "?? src/"]
    assert registry_names() == ["meu-app"] and svc.cfg.repo("meu-app").base_branch == "trunk"


async def test_init_git_on_a_repo_without_commits(svc: OrchestratorService, tmp_path: Path) -> None:
    folder = tmp_path / "outros" / "meu-app"
    folder.mkdir(parents=True)
    sh_git(folder, "init", "-q", "-b", "master")
    (folder / "x.txt").write_text("x", "utf-8")

    refused = await svc._add_repo(cmd(folder, base_branch="master"))
    assert not refused.ok and refused.error is not None and "nenhum commit" in refused.error

    reply = await svc._add_repo(cmd(folder, base_branch="develop", init_git=True))
    assert reply.ok, reply.error
    assert sh_git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "develop"
    assert sh_git(folder, "rev-list", "--count", "HEAD") == "1"
    assert sh_git(folder, "status", "--porcelain") == "?? x.txt"


async def test_init_git_refuses_a_repo_with_staged_files(svc: OrchestratorService, tmp_path: Path) -> None:
    folder = tmp_path / "outros" / "meu-app"
    folder.mkdir(parents=True)
    sh_git(folder, "init", "-q", "-b", "main")
    (folder / "x.txt").write_text("x", "utf-8")
    sh_git(folder, "add", "x.txt")

    reply = await svc._add_repo(cmd(folder, init_git=True))

    assert not reply.ok and reply.error is not None and "stage" in reply.error
    assert sh_git(folder, "rev-list", "--all", "--count") == "0"
    assert registry_names() == []


async def test_init_git_rejects_an_invalid_branch_name(svc: OrchestratorService, tmp_path: Path) -> None:
    folder = tmp_path / "outros" / "meu-app"
    folder.mkdir(parents=True)
    reply = await svc._add_repo(cmd(folder, base_branch="a..b", init_git=True))
    assert not reply.ok and reply.error is not None and "branch base inválido" in reply.error
    assert not (folder / ".git").exists() and registry_names() == []

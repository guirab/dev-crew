from __future__ import annotations

from pathlib import Path

import pytest

from crew.config import RepoCfg
from crew.workspace import git
from crew.workspace.manager import WorkspaceDirty, WorkspaceError, WorkspaceManager

from .git_helpers import make_git_repo, sh_git


@pytest.fixture
def repo_cfg(tmp_path: Path) -> RepoCfg:
    path = make_git_repo(tmp_path / "repos")
    return RepoCfg(name="sample-repo", path=path, base_branch="main", test_cmd="pytest -q")


@pytest.fixture
def manager(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(tmp_path / "worktrees")


async def test_create_makes_isolated_worktree_on_task_branch(
    manager: WorkspaceManager, repo_cfg: RepoCfg
) -> None:
    ws = await manager.create("T-1", repo_cfg)
    assert ws.path == manager.root / "sample-repo" / "T-1" and ws.branch == "crew/T-1"
    assert (ws.path / "app.py").read_text("utf-8") == "a\nb\nc\n"
    assert sh_git(ws.path, "rev-parse", "--abbrev-ref", "HEAD") == "crew/T-1"
    assert sh_git(ws.path, "status", "--porcelain") == ""
    # the user's checkout is untouched
    assert sh_git(repo_cfg.path, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert "crew/T-1" in sh_git(repo_cfg.path, "branch", "--list")


async def test_create_is_idempotent_for_restart_recovery(
    manager: WorkspaceManager, repo_cfg: RepoCfg
) -> None:
    first = await manager.create("T-1", repo_cfg)
    (first.path / "x.py").write_text("work in progress\n", "utf-8")
    again = await manager.create("T-1", repo_cfg)
    assert again == first and (again.path / "x.py").exists(), "existing work must not be wiped"


async def test_create_preconditions(manager: WorkspaceManager, repo_cfg: RepoCfg, tmp_path: Path) -> None:
    missing = repo_cfg.model_copy(update={"path": tmp_path / "nope"})
    with pytest.raises(WorkspaceError, match="não encontrado"):
        await manager.create("T-1", missing)

    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(WorkspaceError, match="não é um repositório git"):
        await manager.create("T-1", repo_cfg.model_copy(update={"path": plain}))

    with pytest.raises(WorkspaceError, match="branch base 'develop'"):
        await manager.create("T-1", repo_cfg.model_copy(update={"base_branch": "develop"}))

    sh_git(repo_cfg.path, "branch", "crew/T-2")
    with pytest.raises(WorkspaceError, match="já existe"):
        await manager.create("T-2", repo_cfg)

    squat = manager.root / "sample-repo" / "T-3"
    squat.mkdir(parents=True)
    with pytest.raises(WorkspaceError, match="não é o worktree"):
        await manager.create("T-3", repo_cfg)


@pytest.mark.parametrize("bad", ["../evil", "T-1/../../x", "T-", "x", "T-1 ", ""])
async def test_task_id_is_validated_against_path_traversal(
    manager: WorkspaceManager, repo_cfg: RepoCfg, bad: str
) -> None:
    with pytest.raises(WorkspaceError, match="inválido"):
        manager.locate(bad, repo_cfg)
    assert manager.find(bad) == []


async def test_repo_name_cannot_escape_the_root(manager: WorkspaceManager, repo_cfg: RepoCfg) -> None:
    evil = repo_cfg.model_copy(update={"name": "../x"})
    with pytest.raises(WorkspaceError, match="nome de repositório inválido"):
        manager.locate("T-1", evil)


async def test_offline_remote_does_not_block_creation(
    manager: WorkspaceManager, repo_cfg: RepoCfg, tmp_path: Path
) -> None:
    sh_git(repo_cfg.path, "remote", "add", "origin", str(tmp_path / "does-not-exist.git"))
    ws = await manager.create("T-1", repo_cfg)
    assert ws.path.is_dir()


async def test_diff_report_covers_tracked_untracked_deleted_and_binary(
    manager: WorkspaceManager, repo_cfg: RepoCfg
) -> None:
    ws = await manager.create("T-1", repo_cfg)
    p = ws.path
    (p / "app.py").write_text("a\nB\nc\nd\ne\n", "utf-8")  # 1 changed line + 2 new = +3 -1
    (p / "gone.txt").unlink()  # -2
    (p / "new.py").write_text("x\ny\nz", "utf-8")  # untracked, no trailing newline -> 3
    (p / "pkg").mkdir()
    (p / "pkg" / "deep file.py").write_text("1\n2\n", "utf-8")  # nested + space in name
    (p / "blob.bin").write_bytes(b"\x00\x01\x02" * 10)  # binary -> 0
    (p / "staged.py").write_text("s\n", "utf-8")
    sh_git(p, "add", "staged.py")  # staged new file

    report = {f.path: f for f in await manager.diff_report(ws)}
    assert (report["app.py"].status, report["app.py"].added, report["app.py"].removed) == ("M", 3, 1)
    assert (report["gone.txt"].status, report["gone.txt"].added, report["gone.txt"].removed) == ("D", 0, 2)
    assert (report["new.py"].status, report["new.py"].added) == ("A", 3)
    assert (report["pkg/deep file.py"].status, report["pkg/deep file.py"].added) == ("A", 2)
    assert (report["blob.bin"].status, report["blob.bin"].added) == ("A", 0)
    assert (report["staged.py"].status, report["staged.py"].added) == ("A", 1)
    assert list(report) == sorted(report)
    assert "README.md" not in report


async def test_diff_report_is_empty_when_clean_and_ignores_base_drift(
    manager: WorkspaceManager, repo_cfg: RepoCfg
) -> None:
    ws = await manager.create("T-1", repo_cfg)
    assert await manager.diff_report(ws) == []
    # main moves on after the worktree was created: must not show up as our change
    (repo_cfg.path / "later.py").write_text("later\n", "utf-8")
    sh_git(repo_cfg.path, "add", "-A")
    sh_git(repo_cfg.path, "commit", "-q", "-m", "later")
    (ws.path / "mine.py").write_text("m\n", "utf-8")
    assert [f.path for f in await manager.diff_report(ws)] == ["mine.py"]


async def test_cleanup_refuses_dirty_unless_forced(manager: WorkspaceManager, repo_cfg: RepoCfg) -> None:
    ws = await manager.create("T-1", repo_cfg)
    (ws.path / "wip.py").write_text("wip\n", "utf-8")
    with pytest.raises(WorkspaceDirty, match="--force"):
        await manager.cleanup(ws)
    assert ws.path.exists()
    await manager.cleanup(ws, force=True)
    assert not ws.path.exists()
    assert "crew/T-1" not in sh_git(repo_cfg.path, "branch", "--list")


async def test_cleanup_clean_worktree_removes_dir_and_branch(
    manager: WorkspaceManager, repo_cfg: RepoCfg
) -> None:
    ws = await manager.create("T-1", repo_cfg)
    await manager.cleanup(ws)
    assert not ws.path.exists() and "crew/T-1" not in sh_git(repo_cfg.path, "branch", "--list")
    await manager.cleanup(ws)  # already gone: no error


async def test_cleanup_keeps_branch_with_user_commits(manager: WorkspaceManager, repo_cfg: RepoCfg) -> None:
    ws = await manager.create("T-1", repo_cfg)
    (ws.path / "mine.py").write_text("m\n", "utf-8")
    sh_git(ws.path, "add", "-A")
    sh_git(ws.path, "commit", "-q", "-m", "user commit")
    await manager.cleanup(ws)  # clean tree -> allowed
    assert not ws.path.exists()
    assert "crew/T-1" in sh_git(repo_cfg.path, "branch", "--list"), "unmerged work survives"


async def test_find_locates_worktrees_by_task(manager: WorkspaceManager, repo_cfg: RepoCfg) -> None:
    assert manager.find("T-1") == []
    ws = await manager.create("T-1", repo_cfg)
    assert manager.find("T-1") == [ws.path]


async def test_inplace_mode(tmp_path: Path, repo_cfg: RepoCfg) -> None:
    mgr = WorkspaceManager(tmp_path / "wt", mode="inplace")
    ws = await mgr.create("T-1", repo_cfg)
    assert ws.path == repo_cfg.path and ws.branch == "main" and ws.mode == "inplace"
    (ws.path / "new.py").write_text("n\n", "utf-8")
    assert [f.path for f in await mgr.diff_report(ws)] == ["new.py"]
    with pytest.raises(WorkspaceError, match="inplace exige working tree limpo"):
        await mgr.create("T-2", repo_cfg)
    with pytest.raises(WorkspaceError, match="inplace"):
        await mgr.cleanup(ws)


async def test_git_wrapper_errors(tmp_path: Path) -> None:
    with pytest.raises(git.GitError, match="falhou"):
        await git.run(tmp_path, "rev-parse", "--verify", "nope")
    assert not await git.ok(tmp_path, "rev-parse", "--git-dir")

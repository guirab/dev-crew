"""Split plans in git (D54, D55, D57): epic worktrees, commits, merges, conflicts, the plan doc."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew import contracts as c
from crew import plan_doc, sandbox
from crew.config import RepoCfg
from crew.workspace.manager import Workspace, WorkspaceError, WorkspaceManager

from .git_helpers import make_git_repo, sh_git


@pytest.fixture
def repo_cfg(tmp_path: Path) -> RepoCfg:
    return RepoCfg(name="sample-repo", path=make_git_repo(tmp_path / "repos"), test_cmd="pytest -q")


@pytest.fixture
def manager(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(tmp_path / "worktrees", fetch=False)


async def _task(manager: WorkspaceManager, repo_cfg: RepoCfg) -> Workspace:
    return await manager.create("T-7", repo_cfg)


async def test_epic_worktree_starts_from_the_task_branch(
    manager: WorkspaceManager, repo_cfg: RepoCfg
) -> None:
    task = await _task(manager, repo_cfg)
    (task.path / "base.txt").write_text("from the task\n")
    await manager.commit_all(task, "chore: base")
    epic = await manager.create_epic(task, "E1")
    assert epic.path == manager.root / "sample-repo" / "T-7-E1"
    assert (epic.branch, epic.base_branch, epic.task_id) == ("crew/T-7-E1", "crew/T-7", "T-7-E1")
    assert (epic.path / "base.txt").read_text() == "from the task\n"
    assert await manager.create_epic(task, "E1") == epic  # idempotent after a restart


async def test_epic_id_and_mode_are_checked(
    manager: WorkspaceManager, repo_cfg: RepoCfg, tmp_path: Path
) -> None:
    task = await _task(manager, repo_cfg)
    with pytest.raises(WorkspaceError, match="épico inválido"):
        manager.locate_epic(task, "../E1")
    inplace = WorkspaceManager(tmp_path / "w2", "inplace").locate("T-8", repo_cfg)
    with pytest.raises(WorkspaceError, match="worktree"):
        manager.locate_epic(inplace, "E1")


async def test_commit_merge_and_cleanup_of_parallel_epics(
    manager: WorkspaceManager, repo_cfg: RepoCfg
) -> None:
    task = await _task(manager, repo_cfg)
    e1 = await manager.create_epic(task, "E1")
    e2 = await manager.create_epic(task, "E2")
    (e1.path / "core.py").write_text("core\n")
    (e2.path / "reports.py").write_text("reports\n")
    assert await manager.commit_all(e1, "feat: núcleo") is not None
    assert await manager.commit_all(e2, "feat: relatórios") is not None
    assert await manager.commit_all(e2, "nada") is None  # nothing left to commit

    first = await manager.merge(task, e1.branch, "merge: E1")
    second = await manager.merge(task, e2.branch, "merge: E2")
    assert first.sha and second.sha and not first.conflicts and not second.conflicts
    assert (task.path / "core.py").is_file() and (task.path / "reports.py").is_file()
    log = sh_git(task.path, "log", "--format=%s")
    assert "feat: núcleo" in log and "feat: relatórios" in log

    await manager.remove_epic(e1)
    assert not e1.path.exists() and "crew/T-7-E1" not in sh_git(repo_cfg.path, "branch", "--list")

    report = await manager.diff_report(task)  # committed work counts in the final report
    assert [(f.path, f.status) for f in report] == [("core.py", "A"), ("reports.py", "A")]


async def test_conflict_is_left_for_the_integrator(manager: WorkspaceManager, repo_cfg: RepoCfg) -> None:
    task = await _task(manager, repo_cfg)
    e1 = await manager.create_epic(task, "E1")
    e2 = await manager.create_epic(task, "E2")
    (e1.path / "NOTES.md").write_text("from E1\n")
    (e2.path / "NOTES.md").write_text("from E2\n")
    await manager.commit_all(e1, "feat: E1")
    await manager.commit_all(e2, "feat: E2")
    assert (await manager.merge(task, e1.branch, "merge: E1")).sha

    outcome = await manager.merge(task, e2.branch, "merge: E2")
    assert outcome.sha is None and outcome.conflicts == ("NOTES.md",)
    assert "<<<<<<<" in (task.path / "NOTES.md").read_text()
    with pytest.raises(WorkspaceError, match="marcadores"):
        await manager.finish_merge(task, "merge: E2")

    (task.path / "NOTES.md").write_text("from E1\nfrom E2\n")  # what the integration lane does
    sha = await manager.finish_merge(task, "merge: E2 (conflito resolvido)")
    assert sh_git(task.path, "rev-parse", "HEAD") == sha
    assert sh_git(task.path, "log", "-1", "--format=%P").count(" ") == 1  # a real merge commit


async def test_abort_merge_restores_the_task_branch(manager: WorkspaceManager, repo_cfg: RepoCfg) -> None:
    task = await _task(manager, repo_cfg)
    e1 = await manager.create_epic(task, "E1")
    (task.path / "app.py").write_text("task\n")
    await manager.commit_all(task, "chore: task edit")
    (e1.path / "app.py").write_text("epic\n")
    await manager.commit_all(e1, "feat: epic edit")
    assert (await manager.merge(task, e1.branch, "merge")).conflicts == ("app.py",)
    await manager.abort_merge(task)
    assert (task.path / "app.py").read_text() == "task\n" and sh_git(task.path, "status", "--porcelain") == ""


async def test_plan_doc_is_committed_in_a_split_plan(manager: WorkspaceManager, repo_cfg: RepoCfg) -> None:
    task = await _task(manager, repo_cfg)
    rel = await manager.write_plan_doc(task, "T-7", "# plano\n", commit=True)
    assert rel == "docs/plano/T-7.md" and (task.path / rel).read_text() == "# plano\n"
    assert sh_git(task.path, "log", "-1", "--format=%s") == "docs: plano T-7"
    assert await manager.write_plan_doc(task, "T-7", "# plano\n", commit=True) == rel  # unchanged: no commit
    assert sh_git(task.path, "rev-list", "--count", "HEAD") == "2"

    single = await manager.create("T-8", repo_cfg)
    await manager.write_plan_doc(single, "T-8", "# plano\n", commit=False)
    assert "docs/" in sh_git(single.path, "status", "--porcelain")  # single execution: nothing committed


def test_workspace_key_of_lanes() -> None:
    assert sandbox.workspace_key("T-7", "E2") == "T-7-E2"
    assert sandbox.workspace_key("T-7", "M-E2") == "T-7"  # integration lane works in the task worktree
    assert sandbox.workspace_key("T-7", None) == "T-7"


def test_plan_doc_render() -> None:
    epics = [
        c.Epic(
            id="E1",
            title="Núcleo",
            goal="g1",
            steps=["s"],
            files=[c.PlanFile(path="a.py", change="A")],
            acceptance_criteria=["ok"],
        ),
        c.Epic(
            id="E2",
            title="Relatórios",
            goal="g2",
            steps=["s"],
            files=[c.PlanFile(path="b.py", change="A")],
            depends_on=["E1"],
            acceptance_criteria=["ok"],
            size="L",
        ),
    ]
    plan = c.Plan(
        summary="resumo",
        steps=[],
        files=[],
        acceptance_criteria=["tudo ok"],
        test_strategy="unit",
        execution="epics",
        split_rationale="porque",
        epics=epics,
    )
    est = c.Estimate(tokens=123456, usd=2.5, weekly_pct=3.1, basis="base")
    md = plan_doc.render(
        "T-7", "Agenda", plan, estimate=est, status={"E1": "merged"}, commits={"E1": "abcdef123456"}
    )
    assert md.startswith("# T-7 · Agenda\n")
    assert "| E1 | Núcleo | — | M | pronto (`abcdef12`) |" in md
    assert "| E2 | Relatórios | E1 | L | pendente |" in md
    assert "### E2 · Relatórios" in md and "- Tokens: ~123.456" in md and "- Semana: ~3.1%" in md

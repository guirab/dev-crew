"""New project from scratch (D58): registry, ``git init``, the setup before the first Tester."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew import contracts as c
from crew import projects
from crew.config import CrewConfig, RepoCfg, WorkspaceCfg
from crew.orchestrator import events as ev
from crew.orchestrator.effects import CreateEpicWorkspace, DispatchJob, RunSetup, SaveProjectSetup
from crew.orchestrator.machine import recovery_effects
from crew.workspace.manager import WorkspaceError, WorkspaceManager

from .core_helpers import Driver, dev, fail_run, plan
from .git_helpers import sh_git
from .test_orch_epics import Split, split_plan

SETUP = c.ProjectSetup(
    stack="Node 22 + Vitest", setup_cmd="npm install", test_cmd="npm test", lint_cmd="npm run lint"
)


def new_repo_ctx() -> c.RepoContext:
    return c.RepoContext(name="agenda", base_branch="main", test_cmd="", test_globs=[], new_project=True)


class NewSingle(Driver):
    def params(self) -> ev.StartParams:
        return ev.StartParams(task_id=self.task_id, repo=new_repo_ctx(), limits=self.limits)

    def to_new_approval(self, setup: c.ProjectSetup | None = SETUP) -> None:
        self.to_planner()
        self.result(plan().model_copy(update={"project_setup": setup}))
        assert self.s.phase == "awaiting_approval"


class NewSplit(Split):
    def params(self) -> ev.StartParams:
        return ev.StartParams(task_id=self.task_id, repo=new_repo_ctx(), limits=self.limits)

    def to_split_approval(self) -> None:
        self.to_planner()
        e0 = c.Epic(
            id="E0",
            title="Fundação",
            goal="base",
            steps=["s"],
            files=[c.PlanFile(path="package.json", change="A")],
            acceptance_criteria=["ok"],
        )
        base = split_plan()
        epics = [e0, *(e.model_copy(update={"depends_on": e.depends_on or ["E0"]}) for e in base.epics)]
        out = base.model_copy(update={"epics": epics, "project_setup": SETUP})
        s = self.s
        assert s.current_job_id is not None
        evt = c.AgentResultEvt(agent="planner", job_id=s.current_job_id, output=out)
        self.feed(ev.AgentResult(task_id=s.task_id, evt=evt, at=self.tick()))


# ---------------------------------------------------------------------------------- machine


def test_approval_adopts_the_planned_commands_and_saves_them() -> None:
    d = NewSingle()
    d.to_new_approval()
    d.command(c.ApprovePlan())
    saved = d.one(SaveProjectSetup)
    assert saved.repo == "agenda" and saved.setup == SETUP
    job = d.job
    assert (
        job.agent == "developer" and job.repo.test_cmd == "npm test" and job.repo.lint_cmd == "npm run lint"
    )
    assert job.repo.new_project and not job.repo.sandbox  # the first task runs on the host
    assert d.s.deps_setup == "pending"


def test_dependencies_are_installed_once_before_the_first_tester() -> None:
    d = NewSingle()
    d.to_new_approval()
    d.command(c.ApprovePlan())
    d.result(dev())
    setup = d.one(RunSetup)
    assert (setup.epic_id, setup.path, setup.command) == (None, "/wt/T-107", "npm install")
    assert not d.has(DispatchJob) and d.s.phase == "testing"
    assert d.s.stages["tester"].now == "Instalando dependências: npm install"
    assert recovery_effects(d.s) == [setup]  # re-issued after a restart

    d.feed(ev.SetupFinished("T-107", None, d.tick()))
    assert d.job.agent == "tester" and d.s.deps_setup == "done"

    d.result(fail_run())
    d.result(dev(2))
    assert not d.has(RunSetup) and d.job.agent == "tester"  # once per worktree


def test_failed_setup_escalates_and_retries_on_request() -> None:
    d = NewSingle()
    d.to_new_approval()
    d.command(c.ApprovePlan())
    d.result(dev())
    d.feed(ev.SetupFinished("T-107", None, d.tick(), error="npm ERR! 404"))
    assert d.s.phase == "escalated" and d.s.escalation is not None
    assert d.s.escalation.kind == "setup" and "npm ERR! 404" in d.s.escalation.reason

    d.command(c.EscalationAction(action="more_attempts"))
    assert d.one(RunSetup).command == "npm install" and d.s.deps_setup == "running"
    d.feed(ev.SetupFinished("T-107", None, d.tick()))
    assert d.job.agent == "tester"


def test_no_setup_command_goes_straight_to_the_tester() -> None:
    d = NewSingle()
    d.to_new_approval(SETUP.model_copy(update={"setup_cmd": None}))
    d.command(c.ApprovePlan())
    assert d.s.deps_setup is None
    d.result(dev())
    assert d.job.agent == "tester"


def test_existing_repo_never_saves_a_setup_nor_installs() -> None:
    d = Driver()
    d.to_planner()
    d.result(plan().model_copy(update={"project_setup": SETUP}))  # ignored outside a new project
    d.command(c.ApprovePlan())
    assert not d.has(SaveProjectSetup) and d.job.repo.test_cmd == "pytest -q"
    d.result(dev())
    assert d.job.agent == "tester"


def test_split_new_project_skips_the_workspace_setup_and_installs_per_lane() -> None:
    d = NewSplit()
    d.to_split_approval()
    d.command(c.ApprovePlan())
    assert d.has(SaveProjectSetup)
    (create,) = [e for e in d.effects if isinstance(e, CreateEpicWorkspace)]
    assert create.epic_id == "E0" and create.prepare is False  # nothing to install before E0
    assert all(lane.deps_setup == "pending" for lane in d.s.lanes.values())

    d.ready("E0")
    d.lane_result("E0", dev())
    setup = d.one(RunSetup)
    assert (setup.epic_id, setup.path) == ("E0", "/wt/T-107-E0")
    d.feed(ev.SetupFinished("T-107", "E0", d.tick()))
    assert d.lane("E0").deps_setup == "done" and d.one(DispatchJob).job.agent == "tester"


def test_stale_setup_result_is_ignored() -> None:
    d = NewSingle()
    d.to_new_approval()
    d.command(c.ApprovePlan())
    before = d.s
    d.feed(ev.SetupFinished("T-107", None, d.tick()))  # nothing was installing
    assert d.s == before


# ---------------------------------------------------------------------------------- registry


def test_registry_round_trip_and_merge(tmp_path: Path) -> None:
    reg = tmp_path / "repos.toml"
    repo = projects.new_repo("agenda", tmp_path / "Agenda Ação")
    projects.register(repo, reg)
    assert projects.load_registered(reg) == [repo]

    configured = RepoCfg(name="agenda", path=tmp_path / "x", test_cmd="pytest")
    cfg = CrewConfig(repos=[configured])
    assert projects.merge_registered(cfg, reg) == [] and cfg.repos == [configured]  # crew.toml wins

    updated = projects.with_setup(repo, SETUP.model_copy(update={"deps_dirs": ["node_modules/"]}))
    projects.register(updated, reg)
    (loaded,) = projects.load_registered(reg)
    assert loaded.test_cmd == "npm test" and loaded.setup_cmd == "npm install"
    assert loaded.deps_dirs == ["node_modules"] and loaded.new_project is False
    other = CrewConfig()
    assert (
        projects.merge_registered(other, reg) == [loaded]
        and other.repo_context("agenda").test_cmd == "npm test"
    )


def test_broken_registry_is_ignored(tmp_path: Path) -> None:
    reg = tmp_path / "repos.toml"
    reg.write_text("[[repos]\nname = ", "utf-8")
    assert projects.load_registered(reg) == []


@pytest.mark.parametrize("name", ["", "con", "a b", "../x", "x.", "-x", "á" * 3])
def test_invalid_names(name: str) -> None:
    with pytest.raises(projects.ProjectError):
        projects.validate_name(name)


def test_project_path_needs_an_existing_absolute_parent(tmp_path: Path) -> None:
    cfg = CrewConfig(workspace=WorkspaceCfg(root=tmp_path / "wt", projects_dir=tmp_path))
    assert projects.project_path(cfg, "agenda", "") == tmp_path / "agenda"
    with pytest.raises(projects.ProjectError):
        projects.project_path(cfg, "agenda", "relativo")
    with pytest.raises(projects.ProjectError):
        projects.project_path(cfg, "agenda", str(tmp_path / "nope"))


async def test_init_repo_creates_a_first_commit_and_refuses_foreign_files(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "wt", fetch=False)
    path = tmp_path / "agenda"
    await manager.init_repo(path, projects.initial_files("agenda", "Agenda", "Agenda de consultas"))
    assert sh_git(path, "log", "--format=%s") == "chore: início do projeto"
    assert sh_git(path, "branch", "--show-current") == "main"
    assert "Agenda de consultas" in (path / "README.md").read_text("utf-8")
    assert "node_modules/" in (path / ".gitignore").read_text("utf-8")

    taken = tmp_path / "taken"
    taken.mkdir()
    (taken / "x.txt").write_text("x", "utf-8")
    with pytest.raises(WorkspaceError):
        await manager.init_repo(taken, {"README.md": "# x\n"})

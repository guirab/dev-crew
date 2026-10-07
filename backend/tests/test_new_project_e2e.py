"""New project end to end (D58): create_project through the bus, fake agents, real git, the registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew import contracts as c
from crew import projects
from crew.orchestrator import machine as m

from .git_helpers import sh_git
from .test_orch_epics_e2e import answer_until_plan, epic_rig

pytestmark = pytest.mark.nats


async def test_new_project_is_created_planned_and_built(
    nats_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CREW_HOME", str(tmp_path / "home"))
    parent = tmp_path / "projetos"
    parent.mkdir()
    rig = await epic_rig(nats_url, tmp_path)
    try:
        bad = await rig.cmd(c.CreateProject(name="a b", parent_dir=str(parent), title="Agenda"))
        assert not bad.ok and bad.error is not None and "nome de projeto inválido" in bad.error
        clash = await rig.cmd(c.CreateProject(name="sample-repo", parent_dir=str(parent), title="Agenda"))
        assert not clash.ok

        cmd = c.CreateProject(
            name="agenda", parent_dir=str(parent), title="Agenda em épicos", description="consultas"
        )
        await rig.ok(cmd)
        repo = parent / "agenda"
        assert sh_git(repo, "log", "--format=%s") == "chore: início do projeto"
        (registered,) = projects.load_registered()
        assert registered.name == "agenda" and registered.new_project

        again = await rig.cmd(c.CreateProject(name="outra", parent_dir=str(parent), title="x"))
        assert again.error == m.ERR_ACTIVE_TASK and not (parent / "outra").exists()

        plan_view = await answer_until_plan(rig)
        assert plan_view.plan is not None and plan_view.plan.project_setup is not None
        assert plan_view.plan.epics[0].id == "E0"

        await rig.ok(c.ApprovePlan())
        done = await rig.wait_phase("done", timeout=120)
        assert done.final is not None
        assert [x.epic_id for x in done.final.commits] == ["E0", "E1", "E2", "E3"]
        wt = Path(done.final.worktree_path)
        assert (wt / "pyproject.toml").is_file() and (wt / "README.md").is_file()

        (saved,) = projects.load_registered()
        assert saved.test_cmd == "python -m pytest -q" and saved.setup_cmd == "git --version"
        assert not saved.new_project and saved.sandbox_image == "python:3.12"
        assert any(
            "Dependências instaladas" in line.text for e in done.epics for line in e.stages.tester.logs
        )
    finally:
        await rig.aclose()

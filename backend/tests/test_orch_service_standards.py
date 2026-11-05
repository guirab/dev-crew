"""D82: the standards stage through the bus: vault copy in, base out into the vault, cleanup."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from crew import contracts as c
from crew import projects
from crew.vaults import VAULTS_ROOT_ENV

from .rig import Rig, start_rig
from .test_orch_service import START_MANUAL, start_to_plan

pytestmark = pytest.mark.nats


@pytest.fixture
async def rig(nats_url: str, tmp_path: Path) -> AsyncIterator[Rig]:
    r = await start_rig(nats_url, tmp_path)
    try:
        yield r
    finally:
        await r.aclose()


def _vault() -> Path:
    return Path(os.environ[VAULTS_ROOT_ENV]) / "sample-repo-vault"


async def test_missing_base_is_written_to_a_new_vault_and_the_worktree_is_clean(rig: Rig) -> None:
    assert not _vault().exists()
    view = await start_to_plan(rig)
    st = view.stages.standards
    assert st.status == "done" and st.now == "Base criada · 3 arquivos", st
    assert view.standards is not None and view.standards.status == "created"
    assert view.standards.files == ["Before You Develop.md", "Conventions.md", "Glossary.md"]
    base = _vault() / "standards"
    assert (base / "Glossary.md").is_file() and (_vault() / ".obsidian").is_dir()
    assert "[[standards/Before You Develop|Before You Develop]]" in (_vault() / "Home.md").read_text("utf-8")
    assert view.plan is not None and view.stages.planner.status == "done"
    assert any(p.agent == "standards" for p in rig.progress)
    state = rig.svc.state if rig.svc else None
    assert state is not None and state.workspace_path is not None
    assert not (Path(state.workspace_path) / ".crew").exists()
    # a crew.toml repo is not pinned in the registry: the convention finds the vault on every job
    assert not projects.registry_path().exists()


async def test_existing_base_is_used_without_a_job(rig: Rig) -> None:
    base = _vault() / "standards"
    base.mkdir(parents=True)
    (base / "Conventions.md").write_text("# Conventions\n", "utf-8")
    view = await start_to_plan(rig)
    assert view.stages.standards.status == "done"
    assert view.standards is not None and view.standards.status == "existing"
    assert view.standards.summary == f"Usando a base existente ({base})"
    assert not any(p.agent == "standards" for p in rig.progress)


async def test_a_registered_repo_gets_its_standards_dir_pinned(rig: Rig) -> None:
    repo = rig.cfg.repos[0]
    projects.register(repo)
    await start_to_plan(rig)
    pinned = next(r for r in projects.load_registered() if r.name == repo.name)
    assert pinned.standards_dir == _vault() / "standards"
    assert rig.cfg.repos[0].standards_dir == _vault() / "standards"


async def test_cancel_during_the_standards_job_removes_the_crew_folder(rig: Rig) -> None:
    await rig.ok(START_MANUAL)
    await rig.wait_for(lambda v: v.stages.standards.status in ("active", "done"))
    await rig.ok(c.CancelTask())
    await rig.wait_phase("cancelled")
    state = rig.svc.state if rig.svc else None
    assert state is not None and state.workspace_path is not None
    assert not (Path(state.workspace_path) / ".crew").exists()

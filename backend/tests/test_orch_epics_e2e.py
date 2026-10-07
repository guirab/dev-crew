"""Split plan end to end: orchestrator + NATS + a pool of scripted agents + real git (D53-D57)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crew import contracts as c
from crew.agents.service import run_agent
from crew.agents.settings import AgentRuntimeSettings
from crew.workspace import git

from .git_helpers import sh_git
from .rig import Rig, start_rig

pytestmark = pytest.mark.nats

LANE_POOL = 3


async def epic_rig(nats_url: str, tmp_path: Path) -> Rig:
    rig = await start_rig(nats_url, tmp_path, agents=False)
    settings = AgentRuntimeSettings(model="fake", fake=True, fake_speed=5000)
    for agent in ("interviewer", "planner", "developer", "tester", "reviewer"):
        copies = LANE_POOL if agent in ("developer", "tester", "reviewer") else 1
        for i in range(copies):
            rig.spawn(
                run_agent(rig.bus, agent, settings=settings, stop=rig.stop, heartbeat_s=1), f"{agent}{i}"
            )
    return rig


async def to_plan(rig: Rig, title: str) -> c.TaskView:
    """Answer every interview round with the recommendations until the plan is waiting for approval."""
    await rig.ok(c.StartTask(repo="sample-repo", title=title, description="dividir em épicos"))
    return await answer_until_plan(rig)


async def answer_until_plan(rig: Rig) -> c.TaskView:
    answered = 0
    while True:
        seen = len(rig.views)

        def fresh(v: c.TaskView, seen: int = seen) -> bool:
            if rig.views.index(v) < seen:
                return False
            pending = v.interview.pending if v.interview else []
            return v.phase == "awaiting_approval" or (v.phase == "interviewing" and bool(pending))

        view = await rig.wait_for(fresh)
        if view.phase == "awaiting_approval":
            return view
        assert view.interview is not None and answered < 10
        await rig.ok(c.AnswerInterview(answers=[None] * len(view.interview.pending)))
        answered += 1


async def test_parallel_epics_merge_into_the_task_branch(nats_url: str, tmp_path: Path) -> None:
    rig = await epic_rig(nats_url, tmp_path)
    try:
        plan_view = await to_plan(rig, "Agenda em épicos")
        assert plan_view.plan is not None and plan_view.plan.execution == "epics"
        assert plan_view.estimate is not None and len(plan_view.estimate.epics) == 3

        await rig.ok(c.ApprovePlan())
        done = await rig.wait_phase("done", timeout=120)
        assert done.final is not None
        assert [x.epic_id for x in done.final.commits] == ["E1", "E2", "E3"]
        assert done.final.plan_doc == "docs/plano/T-1.md" and done.final.pending_epics == []

        wt = Path(done.final.worktree_path)
        log = sh_git(wt, "log", "--format=%s", "main..HEAD")
        assert log.count("merge: E") == 3 and "docs: plano T-1" in log
        for path in ("feature/core.py", "feature/reports.py", "feature/app.py", "docs/plano/T-1.md"):
            assert (wt / path).is_file(), path
        # with the git config dev-crew itself uses (sh_git forces autocrlf=false: CRLF noise on Windows)
        assert await git.out(wt, "status", "--porcelain") == ""  # everything committed (D54)
        assert "pronto" in (wt / "docs" / "plano" / "T-1.md").read_text("utf-8")
        assert not (wt.parent / "T-1-E1").exists()  # merged epic worktrees are removed

        statuses = {e.id: e.status for e in done.epics}
        assert statuses == {"E1": "merged", "E2": "merged", "E3": "merged"}
        # E1 and E2 really ran at the same time: both were running in one published view
        assert any({e.id for e in v.epics if e.status == "running"} >= {"E1", "E2"} for v in rig.views)
    finally:
        await rig.aclose()


async def test_conflicting_epics_go_through_the_integration_lane(nats_url: str, tmp_path: Path) -> None:
    rig = await epic_rig(nats_url, tmp_path)
    try:
        await to_plan(rig, "Agenda em épicos com conflito")
        await rig.ok(c.ApprovePlan(epics=["E1", "E2"]))
        waiting = await rig.wait_phase("awaiting_selection", timeout=120)
        lanes = {e.id: e for e in waiting.epics}
        assert lanes["M-E2"].kind == "integration" and lanes["M-E2"].status == "merged"
        assert lanes["E3"].status == "pending"

        await rig.ok(c.FinishTask())
        done = await rig.wait_phase("done", timeout=60)
        assert done.final is not None and done.final.pending_epics == ["E3"]
        wt = Path(done.final.worktree_path)
        notes = (wt / "NOTES.md").read_text("utf-8")
        assert "<<<<<<<" not in notes
        assert "conflito resolvido" in sh_git(wt, "log", "-1", "--format=%s", "--grep=conflito")
    finally:
        await rig.aclose()

"""Orchestrator service on a real nats-server with fake agents: the whole loop, through the bus only."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest

from crew import contracts as c
from crew.bus import subjects as s
from crew.config import CrewConfig, RepoCfg, WorkspaceCfg
from crew.orchestrator import machine as m
from crew.orchestrator.devfakes import FakeCrew
from crew.orchestrator.store import Store

from .core_helpers import dev, plan
from .git_helpers import sh_git
from .rig import Rig, start_orchestrator, start_rig

pytestmark = pytest.mark.nats

START_MANUAL = c.StartTask(
    source="manual", repo="sample-repo", title="Exportar pedidos em CSV", description="CSV"
)
START_AZURE = c.StartTask(source="azure", repo="sample-repo", work_item_id=4821)


@pytest.fixture
async def rig(nats_url: str, tmp_path: Path) -> AsyncIterator[Rig]:
    r = await start_rig(nats_url, tmp_path)
    try:
        yield r
    finally:
        await r.aclose()


async def drive_interview(rig: Rig) -> None:
    for i in range(3):
        v = await rig.wait_for(
            lambda v, n=i: (
                v.interview is not None and v.interview.pending is not None and len(v.interview.turns) == n
            )
        )
        assert v.stages.interviewer.status == "waiting"
        await rig.ok(c.AnswerInterview(text=None if i != 1 else "só CSV com BOM"))


async def test_state_current_is_null_without_task(rig: Rig) -> None:
    assert await rig.current() is None


async def test_manual_flow_to_done_with_interview_failure_loops_and_report(rig: Rig) -> None:
    first = await rig.ok(START_MANUAL)
    assert first.task_id == "T-1" and first.phase == "interviewing" and first.source == "manual"

    await drive_interview(rig)
    plan_view = await rig.wait_phase("awaiting_approval")
    assert plan_view.plan is not None and plan_view.stages.approval.status == "waiting"
    assert plan_view.interview is not None and len(plan_view.interview.decisions) == 3
    assert plan_view.interview.decisions[1] == "Critérios de aceite: só CSV com BOM"

    await rig.ok(c.ApprovePlan())
    done = await rig.wait_phase("done")

    # phase trail: tester fails once (-> developer), reviewer asks changes once (-> developer)
    assert rig.phases() == [
        "interviewing",
        "planning",
        "awaiting_approval",
        "developing",
        "testing",
        "developing",
        "testing",
        "reviewing",
        "developing",
        "testing",
        "reviewing",
        "done",
    ]
    assert (
        done.counters.dev_round == 3 and done.counters.review_round == 2 and done.counters.test_attempt == 0
    )
    assert [t.ok for t in done.test_runs] == [False, True, True]
    assert done.review is not None and done.review.verdict == "approved" and done.review.commit_message
    assert done.final is not None
    assert done.final.branch == "crew/T-1" and Path(done.final.worktree_path).is_dir()
    changed = {f.path: f for f in done.final.files}
    assert (
        changed["src/crew_fake_feature.py"].status == "A" and changed["src/crew_fake_feature.py"].added >= 2
    )
    assert "tests/test_crew_fake_feature.py" in changed
    assert done.final.commit_message.startswith("feat: exportar pedidos em CSV")
    assert (
        done.cost_usd > 0
        and done.final.cost_usd == pytest.approx(done.cost_usd)
        and done.ended_at is not None
    )
    # progress lines flowed on the bus and were folded into the stage logs
    assert any(p.agent == "developer" for p in rig.progress)
    assert done.stages.developer.logs

    # the system never commits: the branch has no commits of its own
    assert sh_git(Path(done.final.worktree_path), "rev-list", "--count", "main..HEAD") == "0"
    assert (await rig.current()) == done


async def test_azure_flow_adjusts_plan_then_completes(rig: Rig) -> None:
    started = await rig.ok(START_AZURE)
    assert started.ref == "AB#4821" and started.source == "azure"
    first_plan = await rig.wait_phase("awaiting_approval")
    assert (
        first_plan.title.startswith("Filtro por intervalo")
        and first_plan.stages.interviewer.status == "skipped"
    )
    assert first_plan.stages.azure.status == "done" and first_plan.interview is None

    adjusted = await rig.ok(c.AdjustPlan(text="não mexer no módulo de auth"))
    assert adjusted.phase == "planning"
    second = await rig.wait_for(
        lambda v: v.phase == "awaiting_approval" and v.plan is not None and "não mexer" in v.plan.summary
    )
    assert second.plan is not None

    await rig.ok(c.ApprovePlan())
    done = await rig.wait_phase("done")
    assert done.final is not None and "Refs: AB#4821" in done.final.commit_message
    assert "planning" in rig.phases()[2:], "adjust loops back through planning"
    # the job the planner got for the adjustment carried the user text and the previous plan
    jobs = rig.store.jobs("T-1")
    assert [j.agent for j in jobs][:3] == ["planner", "planner", "developer"]
    assert all(j.status == "done" for j in jobs)


async def test_escalation_then_instruction_resumes_to_done(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, escalate=True)
    try:
        await rig.ok(START_AZURE)
        await rig.wait_phase("awaiting_approval")
        await rig.ok(c.ApprovePlan())
        esc = await rig.wait_phase("escalated")
        assert esc.escalation == c.Escalation(stage="tester", reason="3 falhas consecutivas de teste")
        assert esc.counters.test_attempt == 3 and esc.stages.tester.status == "error"

        bad = await rig.cmd(c.EscalationAction(action="instruct", text=" "))
        assert not bad.ok and bad.error == m.ERR_TEXT_REQUIRED

        await rig.ok(c.EscalationAction(action="instruct", text="usar fake timers"))
        done = await rig.wait_phase("done")
        assert done.final is not None and done.counters.test_attempt == 0
    finally:
        await rig.aclose()


async def test_escalation_more_attempts_raises_limit_and_finishes(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, escalate=True, max_test_attempts=3, max_review_rounds=3)
    try:
        await rig.ok(START_AZURE)
        await rig.wait_phase("awaiting_approval")
        await rig.ok(c.ApprovePlan())
        await rig.wait_phase("escalated")
        view = await rig.ok(c.EscalationAction(action="more_attempts"))
        assert view.counters.max_test_attempts == 5 and view.phase == "developing"
        done = await rig.wait_phase("done")
        assert done.counters.max_test_attempts == 5
    finally:
        await rig.aclose()


async def test_escalation_replan_goes_back_to_approval(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, escalate=True)
    try:
        await rig.ok(START_AZURE)
        await rig.wait_phase("awaiting_approval")
        await rig.ok(c.ApprovePlan())
        await rig.wait_phase("escalated")
        replanned = await rig.ok(c.EscalationAction(action="replan"))
        assert replanned.phase == "planning" and replanned.counters.test_attempt == 0
        await rig.wait_for(lambda v: v.phase == "awaiting_approval" and v.counters.dev_round == 3)
        await rig.ok(c.ApprovePlan())
        done = await rig.wait_phase("done")
        assert done.counters.dev_round >= 4
    finally:
        await rig.aclose()


async def test_cancel_stops_the_running_agent_and_ignores_late_results(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, speed=1.0)  # real-time fake: developer takes ~2s
    try:
        await rig.ok(START_AZURE)
        await rig.wait_phase("awaiting_approval", timeout=30)
        await rig.ok(c.ApprovePlan())
        await rig.wait_phase("developing")
        cancelled = await rig.ok(c.CancelTask())
        assert cancelled.phase == "cancelled" and cancelled.ended_at is not None
        await rig.wait_phase("cancelled")
        count = len(rig.views)
        await asyncio.sleep(3.5)  # the fake would have finished the round by now
        assert len(rig.views) == count, "no view after cancel: the job was aborted / its result ignored"
        current = await rig.current()
        assert current is not None and current.phase == "cancelled"
        assert rig.store.jobs("T-1")[-1].status == "cancelled"
        # and a new task can start right away
        again = await rig.ok(START_MANUAL)
        assert again.task_id == "T-2"
    finally:
        await rig.aclose()


async def test_only_one_active_task_and_validation_replies(rig: Rig) -> None:
    await rig.ok(START_AZURE)
    dup = await rig.cmd(START_MANUAL)
    assert not dup.ok and dup.error == m.ERR_ACTIVE_TASK
    await rig.ok(c.CancelTask())
    unknown = await rig.cmd(c.StartTask(source="manual", repo="nope", title="x"))
    assert not unknown.ok and unknown.error == m.ERR_UNKNOWN_REPO
    noitem = await rig.cmd(c.StartTask(source="azure", repo="sample-repo"))
    assert noitem.error == m.ERR_WORK_ITEM_REQUIRED
    wrong = await rig.cmd(c.ApprovePlan())
    assert wrong.error == m.ERR_NO_TASK


async def test_malformed_command_gets_a_clear_error_reply(rig: Rig) -> None:
    raw = await rig.bus.request_raw(s.CMD, b'{"type": "start_task", "source": "ftp", "repo": "x"}')
    reply = c.CommandReply.model_validate_json(raw)
    assert not reply.ok and reply.error is not None and "comando inválido" in reply.error
    raw = await rig.bus.request_raw(s.CMD, b'{"type": "nope"}')
    assert not c.CommandReply.model_validate_json(raw).ok


async def test_stale_and_foreign_results_are_ignored(rig: Rig) -> None:
    await rig.ok(START_MANUAL)
    q = await rig.wait_for(lambda v: v.interview is not None and v.interview.pending is not None)
    before = len(rig.views)
    evt = c.AgentResultEvt(agent="planner", job_id=uuid4(), output=dev(), cost_usd=99.0)
    await rig.bus.publish_event("T-1", "result", evt, source="planner")
    await rig.bus.publish_event("T-404", "result", evt, source="planner")
    await asyncio.sleep(0.5)
    assert len(rig.views) == before
    now = await rig.current()
    assert now is not None and now.cost_usd == q.cost_usd


async def test_workspace_failure_fails_the_task(nats_url: str, tmp_path: Path) -> None:
    cfg = CrewConfig(
        workspace=WorkspaceCfg(root=tmp_path / "wt"),
        repos=[RepoCfg(name="sample-repo", path=tmp_path / "missing", test_cmd="pytest")],
    )
    rig = await start_rig(nats_url, tmp_path, cfg=cfg)
    try:
        await rig.ok(START_MANUAL)
        failed = await rig.wait_phase("failed")
        assert failed.stages.manual.status == "error" and "não encontrado" in (failed.stages.manual.now or "")
    finally:
        await rig.aclose()


async def test_job_timeout_escalates_when_nobody_answers(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, agents=False, job_timeout_min=0.01)  # 0.6 s
    try:
        await rig.ok(START_AZURE)
        esc = await rig.wait_phase("escalated")
        assert esc.escalation is not None and esc.escalation.stage == "planner"
        assert "sem resposta" in esc.escalation.reason
    finally:
        await rig.aclose()


async def test_budget_exhaustion_escalates_and_more_attempts_resumes(nats_url: str, tmp_path: Path) -> None:
    rig = await start_rig(nats_url, tmp_path, budget_usd_per_task=0.12)  # each fake job costs 0.05
    try:
        await rig.ok(START_AZURE)
        await rig.wait_phase("awaiting_approval")
        await rig.ok(c.ApprovePlan())
        esc = await rig.wait_phase("escalated")
        assert "orçamento" in (esc.escalation.reason if esc.escalation else "")
        blocked = await rig.cmd(c.EscalationAction(action="instruct", text="x"))
        assert blocked.error == m.ERR_BUDGET
        await rig.ok(c.EscalationAction(action="more_attempts"))
        # keeps going; may escalate again for budget on a later step, but must have made progress
        await rig.wait_for(lambda v: v.cost_usd >= 0.2)
    finally:
        await rig.aclose()


async def test_everything_is_persisted_and_event_logged(rig: Rig) -> None:
    await rig.ok(START_AZURE)
    await rig.wait_phase("awaiting_approval")
    saved = rig.store.load_task("T-1")
    assert saved is not None and saved.phase == "awaiting_approval" and saved.plan is not None
    kinds = [e.kind for e in rig.store.event_log("T-1")]
    assert kinds[0] == "command" and "work_item_loaded" in kinds and "result" in kinds
    assert "progress" not in kinds


async def test_restart_between_steps_republishes_view_and_continues(nats_url: str, tmp_path: Path) -> None:
    store = Store(tmp_path / "crew.db")
    rig = await start_rig(nats_url, tmp_path, store=store)
    try:
        await rig.ok(START_AZURE)
        await rig.wait_phase("awaiting_approval")

        # "crash": stop the orchestrator only, keep bus / agents / store
        rig.stop.set()
        await asyncio.sleep(0.6)
        for t in rig.tasks:
            if t.get_name() == "orchestrator":
                await asyncio.wait_for(t, 10)
        rig.stop = asyncio.Event()
        rig.views.clear()
        rig.fake = None

        # new process: same db
        store.close()
        rig.store = Store(tmp_path / "crew.db")
        await start_orchestrator(rig)
        view = await rig.wait_phase("awaiting_approval", timeout=10)
        assert view.task_id == "T-1" and view.plan is not None, "view republished from SQLite on boot"
        assert (await rig.current()) == view
        assert not (await rig.cmd(START_AZURE)).ok, "the recovered task is still the active one"

        # agents died with the old stop event; start fresh ones against the new orchestrator
        crew = FakeCrew(rig.bus, speed=5000)
        rig.spawn(crew.run(rig.stop), "fake-agents-2")
        await rig.ok(c.ApprovePlan())
        done = await rig.wait_phase("done")
        assert done.final is not None
    finally:
        await rig.aclose()


async def test_in_flight_result_survives_an_orchestrator_restart(nats_url: str, tmp_path: Path) -> None:
    """The agent answers while the orchestrator is down: the durable consumer delivers it on boot."""
    store = Store(tmp_path / "crew.db")
    rig = await start_rig(nats_url, tmp_path, store=store, agents=False)
    try:
        await rig.ok(START_AZURE)
        await rig.wait_for(lambda v: v.stages.planner.status == "active")  # planner job dispatched
        before = rig.store.load_task("T-1")
        assert before is not None and before.current_job_id is not None
        job_id = before.current_job_id

        rig.stop.set()
        for t in list(rig.tasks):
            if t.get_name() == "orchestrator":
                await asyncio.wait_for(t, 10)
        rig.stop = asyncio.Event()
        rig.views.clear()

        # while the orchestrator is down the planner finishes
        res = c.AgentResultEvt(agent="planner", job_id=job_id, output=plan(), cost_usd=0.1, session_id="sess")
        await rig.bus.publish_event("T-1", "result", res, source="planner")

        store.close()
        rig.store = Store(tmp_path / "crew.db")
        await start_orchestrator(rig)
        view = await rig.wait_phase("awaiting_approval", timeout=15)
        after = rig.store.load_task("T-1")
        assert view.plan is not None and after is not None and after.sessions["planner"] == "sess"
    finally:
        await rig.aclose()

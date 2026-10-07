"""Split plans in the state machine (D53-D57): lanes in parallel, merges, integration, batches."""

from __future__ import annotations

from crew import contracts as c
from crew.orchestrator import events as ev
from crew.orchestrator import machine as m
from crew.orchestrator.effects import (
    BuildFinalReport,
    CancelJobs,
    CreateEpicWorkspace,
    DispatchJob,
    FinishMerge,
    MergeEpic,
    Reject,
    RemoveEpicWorkspace,
    WritePlanDoc,
)
from crew.orchestrator.machine import recovery_effects
from crew.orchestrator.state import LaneState

from .core_helpers import Driver, dev, fail_run, pass_run, review_ok


def epic(epic_id: str, deps: tuple[str, ...] = ()) -> c.Epic:
    return c.Epic(
        id=epic_id,
        title=f"Épico {epic_id}",
        goal=f"objetivo {epic_id}",
        steps=["s"],
        files=[c.PlanFile(path=f"{epic_id.lower()}.py", change="A")],
        depends_on=list(deps),
        acceptance_criteria=["ok"],
    )


def split_plan() -> c.Plan:
    """E1 ∥ E2 → E3, plus E4 that nobody depends on."""
    return c.Plan(
        summary="s",
        steps=[],
        files=[],
        acceptance_criteria=["ok"],
        test_strategy="t",
        execution="epics",
        split_rationale="porque",
        epics=[epic("E1"), epic("E2"), epic("E3", ("E1", "E2")), epic("E4")],
    )


class Split(Driver):
    def to_split_approval(self) -> None:
        self.to_planner()
        s = self.s
        assert s.current_job_id is not None
        evt = c.AgentResultEvt(agent="planner", job_id=s.current_job_id, output=split_plan())
        self.feed(ev.AgentResult(task_id=s.task_id, evt=evt, at=self.tick()))
        assert self.s.phase == "awaiting_approval"

    def lane(self, lane_id: str) -> LaneState:
        return self.s.lanes[lane_id]

    def ready(self, epic_id: str) -> list[DispatchJob]:
        fx = self.feed(
            ev.EpicWorkspaceReady(
                self.s.task_id, epic_id, f"/wt/T-107-{epic_id}", f"crew/T-107-{epic_id}", self.tick()
            )
        )
        return [e for e in fx if isinstance(e, DispatchJob)]

    def lane_result(self, lane_id: str, output: c.AgentOutput, *, tokens: int = 0) -> None:
        lane = self.lane(lane_id)
        assert lane.current_agent is not None and lane.current_job_id is not None
        evt = c.AgentResultEvt(
            agent=lane.current_agent,
            job_id=lane.current_job_id,
            output=output,
            cost_usd=0.1,
            usage=[c.TokenUsage(model="m", input_tokens=tokens)] if tokens else [],
        )
        self.feed(ev.AgentResult(task_id=self.s.task_id, evt=evt, at=self.tick()))

    def lane_failed(self, lane_id: str, error: str, limit: c.UsageLimit | None = None) -> None:
        lane = self.lane(lane_id)
        assert lane.current_agent is not None and lane.current_job_id is not None
        evt = c.AgentFailedEvt(agent=lane.current_agent, job_id=lane.current_job_id, error=error, limit=limit)
        self.feed(ev.AgentFailed(task_id=self.s.task_id, evt=evt, at=self.tick()))

    def pass_lane(self, lane_id: str) -> None:
        """Developer → Tester (pass) → Reviewer (approved)."""
        self.lane_result(lane_id, dev())
        self.lane_result(lane_id, pass_run())
        self.lane_result(lane_id, review_ok(commit=None))

    def merged(self, epic_id: str, sha: str = "a1b2c3d4e5") -> None:
        self.feed(ev.EpicMerged(self.s.task_id, epic_id, self.tick(), sha=sha))


def approved(epics: list[str] | None = None) -> Split:
    d = Split()
    d.to_split_approval()
    d.command(c.ApprovePlan(epics=epics or []))
    return d


# ---------------------------------------------------------------------------------- approval / scheduling


def test_approving_a_split_plan_starts_the_ready_epics_in_parallel() -> None:
    d = approved()
    s = d.s
    assert s.phase == "executing" and s.chosen == ["E1", "E2", "E3", "E4"]
    assert {i: lane.status for i, lane in s.lanes.items()} == {
        "E1": "preparing",
        "E2": "preparing",
        "E3": "waiting",
        "E4": "preparing",
    }
    creates = [e.epic_id for e in d.effects if isinstance(e, CreateEpicWorkspace)]
    assert creates == ["E1", "E2", "E4"]
    doc = d.one(WritePlanDoc)
    assert doc.commit and "| E3 | Épico E3 | E1, E2 |" in doc.markdown
    assert s.stages["approval"].status == "done" and not d.has(DispatchJob)


def test_choosing_an_epic_brings_its_dependencies() -> None:
    d = approved(["E3"])
    assert d.s.chosen == ["E1", "E2", "E3"] and d.lane("E4").status == "pending"
    assert d.command(c.ApprovePlan(epics=["E9"])) == [Reject(m.ERR_WRONG_PHASE)]


def test_unknown_epic_is_rejected_on_approval() -> None:
    d = Split()
    d.to_split_approval()
    assert d.command(c.ApprovePlan(epics=["E9"])) == [Reject(m.ERR_UNKNOWN_EPIC)]


def test_lane_jobs_carry_the_epic_and_its_worktree() -> None:
    d = approved()
    (dispatch,) = d.ready("E1")
    job = dispatch.job
    assert (job.agent, job.epic_id, job.workspace_path) == ("developer", "E1", "/wt/T-107-E1")
    assert job.plan is not None and job.plan.execution == "epics"
    assert d.lane("E1").status == "running" and d.lane("E1").branch == "crew/T-107-E1"
    (other,) = d.ready("E2")
    assert other.job.job_id != job.job_id and d.lane("E1").current_job_id == job.job_id


# ------------------------------------------------------------------ lanes, merges, integration


def test_epics_merge_one_at_a_time_and_unblock_dependents() -> None:
    d = approved(["E3"])
    d.ready("E1")
    d.ready("E2")
    d.pass_lane("E1")
    merge = d.one(MergeEpic)
    assert merge.epic_id == "E1" and merge.commit_message == "feat(E1): épico E1"
    assert d.s.merging == "E1" and d.lane("E1").status == "merging"

    d.pass_lane("E2")  # approved while E1 is merging: queued
    assert not d.has(MergeEpic) and d.s.merge_queue == ["E2"]

    d.merged("E1", "1111111111")
    assert d.lane("E1").status == "merged" and d.lane("E1").commit_sha == "1111111111"
    assert d.one(RemoveEpicWorkspace).epic_id == "E1"
    assert d.one(MergeEpic).epic_id == "E2"  # next in the queue
    assert d.lane("E3").status == "waiting"  # E2 not merged yet

    d.merged("E2", "2222222222")
    assert d.one(CreateEpicWorkspace).epic_id == "E3"
    assert d.lane("E3").status == "preparing"


def test_conflict_runs_an_integration_lane_in_the_task_worktree() -> None:
    d = approved(["E1", "E2"])
    d.ready("E1")
    d.ready("E2")
    d.pass_lane("E1")
    d.merged("E1")
    d.pass_lane("E2")
    fx = d.feed(ev.EpicMerged(d.s.task_id, "E2", d.tick(), conflicts=("NOTES.md",)))
    integ = d.lane("M-E2")
    assert integ.kind == "integration" and integ.merge_of == "E2" and integ.status == "running"
    (dispatch,) = [e for e in fx if isinstance(e, DispatchJob)]
    job = dispatch.job
    assert job.epic_id == "M-E2" and job.workspace_path == "/wt/T-107"
    assert job.feedback is not None and job.feedback.kind == "merge_conflict"
    assert "NOTES.md" in (job.feedback.text or "") and d.lane("E2").status == "merging"

    d.pass_lane("M-E2")
    finish = d.one(FinishMerge)
    assert finish.epic_id == "E2" and "conflito resolvido" in finish.message
    d.merged("E2", "3333333333")
    assert d.lane("E2").status == "merged" and d.lane("M-E2").status == "merged"


def test_finished_batch_with_pending_epics_waits_for_the_user() -> None:
    d = approved(["E1"])
    d.ready("E1")
    d.pass_lane("E1")
    d.merged("E1")
    assert d.s.phase == "awaiting_selection" and not d.has(BuildFinalReport)

    d.command(c.RunEpics(epics=["E3"]))
    assert d.s.phase == "executing" and d.lane("E2").status == "preparing"
    assert d.lane("E3").status == "waiting" and d.lane("E4").status == "pending"
    assert [e.epic_id for e in d.effects if isinstance(e, CreateEpicWorkspace)] == ["E2"]


def test_finish_task_reports_commits_and_pending_epics() -> None:
    d = approved(["E1"])
    d.ready("E1")
    d.pass_lane("E1")
    d.merged("E1", "abcdef0123")
    d.command(c.FinishTask())
    report = d.one(BuildFinalReport)
    assert (
        report.commit_doc
        and report.plan_doc is not None
        and "| E1 | Épico E1 | — | M | pronto" in report.plan_doc
    )
    d.feed(ev.ReportBuilt(d.s.task_id, [], d.tick(), plan_doc="docs/plano/T-107.md"))
    s = d.s
    assert s.phase == "done" and s.final is not None
    assert [(x.epic_id, x.sha, x.message) for x in s.final.commits] == [
        ("E1", "abcdef0123", "feat(E1): épico E1")
    ]
    assert s.final.pending_epics == ["E2", "E3", "E4"] and s.final.plan_doc == "docs/plano/T-107.md"


def test_all_epics_merged_builds_the_final_report() -> None:
    d = approved(["E1", "E2"])
    for e in ("E1", "E2"):
        d.ready(e)
    for e in ("E1", "E2"):
        d.pass_lane(e)
    d.merged("E1")
    d.merged("E2")
    assert d.s.phase == "awaiting_selection"  # E3/E4 still pending
    d2 = approved(["E4"])
    d2.ready("E4")
    d2.pass_lane("E4")
    d2.merged("E4")
    assert d2.s.phase == "awaiting_selection"
    d2.command(c.RunEpics(epics=["E1", "E2", "E3"]))
    for e in ("E1", "E2"):
        d2.ready(e)
        d2.pass_lane(e)
    d2.merged("E1")
    d2.merged("E2")
    d2.ready("E3")
    d2.pass_lane("E3")
    d2.merged("E3")
    assert d2.has(BuildFinalReport) and d2.s.boot == "build_report"


# ------------------------------------------------------------------ escalation / limit / io errors


def test_lane_escalation_does_not_stop_the_others() -> None:
    d = approved(["E1", "E2"])
    d.ready("E1")
    d.ready("E2")
    d.lane_result("E1", dev())
    for _ in range(3):
        d.lane_result("E1", fail_run())
        if d.lane("E1").status == "running":
            d.lane_result("E1", dev())
    assert d.lane("E1").status == "escalated" and d.lane("E2").status == "running"
    assert d.s.phase == "executing"
    view = d.s.to_view()
    (e1,) = [v for v in view.epics if v.id == "E1"]
    assert e1.escalation is not None and e1.escalation.epic_id == "E1"

    assert d.command(c.EscalationAction(action="replan", epic_id="E1")) == [Reject(m.ERR_REPLAN_LANE)]
    d.command(c.EscalationAction(action="more_attempts", epic_id="E1"))
    assert d.lane("E1").status == "running" and d.lane("E1").limits.max_test_attempts == 5
    assert d.job.epic_id == "E1"


def test_escalation_action_needs_the_epic_when_several_are_escalated() -> None:
    d = approved(["E1", "E2"])
    for e in ("E1", "E2"):
        d.ready(e)
        d.lane_failed(e, "boom")
    assert d.s.phase == "escalated"
    assert d.command(c.EscalationAction(action="more_attempts")) == [Reject(m.ERR_EPIC_REQUIRED)]
    assert d.s.to_view().escalation is not None  # the tab title can say "needs you"
    d.command(c.EscalationAction(action="more_attempts", epic_id="E2"))
    assert d.lane("E2").status == "running" and d.s.phase == "executing"


def test_usage_limit_in_a_lane_and_resume() -> None:
    d = approved(["E1", "E2"])
    d.ready("E1")
    d.ready("E2")
    limit = c.UsageLimit(kind="session", message="Limite de uso da assinatura atingido (sessão de 5 h)")
    d.lane_failed("E1", "limite", limit)
    assert d.s.phase == "limited" and d.lane("E1").status == "limited" and d.s.to_view().limit == limit
    d.lane_failed("E2", "limite", limit)
    d.command(c.ResumeAfterLimit())
    assert d.s.phase == "executing" and {d.lane("E1").status, d.lane("E2").status} == {"running"}
    assert sorted(e.job.epic_id or "" for e in d.effects if isinstance(e, DispatchJob)) == ["E1", "E2"]


def test_workspace_failure_escalates_the_lane_and_retries() -> None:
    d = approved(["E1"])
    d.feed(ev.EpicWorkspaceFailed(d.s.task_id, "E1", "setup falhou", d.tick()))
    assert d.lane("E1").status == "escalated" and d.s.phase == "escalated"
    d.command(c.EscalationAction(action="more_attempts", epic_id="E1"))
    assert d.one(CreateEpicWorkspace).epic_id == "E1" and d.lane("E1").status == "preparing"


def test_merge_error_escalates_and_retries() -> None:
    d = approved(["E1"])
    d.ready("E1")
    d.pass_lane("E1")
    d.feed(ev.EpicMerged(d.s.task_id, "E1", d.tick(), error="hook pre-commit falhou"))
    assert d.lane("E1").status == "escalated" and d.s.merging is None
    d.command(c.EscalationAction(action="more_attempts", epic_id="E1"))
    assert d.one(MergeEpic).epic_id == "E1" and d.s.merging == "E1"


def test_cancel_stops_every_lane() -> None:
    d = approved()
    d.ready("E1")
    d.command(c.CancelTask())
    assert d.s.phase == "cancelled" and d.one(CancelJobs).agent is None
    assert all(lane.status in ("failed", "pending") for lane in d.s.lanes.values())


def test_tokens_and_cost_are_tracked_per_lane() -> None:
    d = approved(["E1"])
    d.ready("E1")
    d.lane_result("E1", dev(), tokens=500)
    assert d.lane("E1").tokens == 500 and d.s.tokens >= 500
    (view,) = [v for v in d.s.to_view().epics if v.id == "E1"]
    assert view.tokens == 500 and view.goal == "objetivo E1" and view.stages.developer.status == "done"


def test_recovery_reissues_lane_io() -> None:
    d = approved(["E1", "E2"])
    d.ready("E1")
    d.pass_lane("E1")
    effects = recovery_effects(d.s)
    assert [type(e).__name__ for e in effects] == ["CreateEpicWorkspace", "MergeEpic"]
    assert isinstance(effects[0], CreateEpicWorkspace) and effects[0].epic_id == "E2"


def test_single_plan_writes_the_doc_without_committing() -> None:
    d = Driver()
    d.to_awaiting_approval()
    d.command(c.ApprovePlan())
    doc = d.one(WritePlanDoc)
    assert not doc.commit and d.job.epic_id is None and not d.s.lanes

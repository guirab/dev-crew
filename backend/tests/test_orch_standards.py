"""D82: the standards stage runs beside the interview; the Planner waits for both."""

from __future__ import annotations

from uuid import UUID

from crew import contracts as c
from crew.orchestrator import events as ev
from crew.orchestrator.effects import CancelJobs, DispatchJob
from crew.orchestrator.machine import WAITING_STANDARDS, recovery_effects
from crew.orchestrator.state import TaskState

from .core_helpers import Driver, plan, question

BASE = "/vaults/sample-repo-vault/standards"
SPEC = c.TaskSpec(title="Exportar pedidos em CSV", description="d", repo="sample-repo")


class StDriver(Driver):
    def __init__(self, *, exists: bool = False, new_project: bool = False) -> None:
        super().__init__()
        self.base = ev.StandardsBase(dir=BASE, exists=exists)
        self.new_project = new_project

    def params(self) -> ev.StartParams:
        p = super().params()
        repo = p.repo.model_copy(update={"new_project": self.new_project})
        return ev.StartParams(task_id=p.task_id, repo=repo, limits=p.limits, standards=self.base)

    def dispatched(self) -> list[c.AgentJob]:
        return [e.job for e in self.effects if isinstance(e, DispatchJob)]

    def standards_job(self) -> UUID:
        assert self.s.standards_job_id is not None
        return self.s.standards_job_id

    def standards_result(self, files: list[str] | None = None, notes: str | None = None) -> None:
        out = c.StandardsResult(summary="Base criada.", files=["Glossary.md"] if files is None else files)
        if notes:
            out = out.model_copy(update={"notes": notes})
        evt = c.AgentResultEvt(
            agent="standards", job_id=self.standards_job(), output=out, cost_usd=0.2, duration_s=1.0
        )
        self.feed(ev.AgentResult(task_id=self.task_id, evt=evt, at=self.tick()))

    def standards_failed(self, error: str = "boom", *, retryable: bool = False) -> None:
        evt = c.AgentFailedEvt(
            agent="standards", job_id=self.standards_job(), error=error, retryable=retryable
        )
        self.feed(ev.AgentFailed(task_id=self.task_id, evt=evt, at=self.tick()))

    def close_interview(self) -> None:
        self.result(c.InterviewResult(kind="question", questions=[question(1)]), cost=0.0)
        self.command(c.AnswerInterview(answers=[None]))
        self.result(c.InterviewResult(kind="done", spec=SPEC), cost=0.0)


def test_existing_base_is_done_at_start_without_a_job() -> None:
    d = StDriver(exists=True)
    d.boot()
    assert [j.agent for j in d.dispatched()] == ["interviewer"]
    st = d.s.stages["standards"]
    assert st.status == "done" and st.now == f"Usando a base existente ({BASE})"
    assert d.s.standards is not None and d.s.standards.status == "existing"
    view = d.s.to_view()
    assert view.standards == d.s.standards and view.edges["ma-st"] == "on"
    d.close_interview()
    assert d.job.agent == "planner" and d.s.edges["st-pl"] == "on"


def test_new_project_skips_the_stage() -> None:
    d = StDriver(new_project=True)
    d.boot()
    assert [j.agent for j in d.dispatched()] == ["interviewer"]
    assert d.s.stages["standards"].status == "skipped" and d.s.standards is None
    d.close_interview()
    assert d.job.agent == "planner" and "st-pl" not in d.s.edges


def test_unchecked_base_leaves_the_stage_idle() -> None:
    d = Driver()  # StartParams without standards: nothing to do
    d.boot()
    assert d.job.agent == "interviewer" and d.s.stages["standards"].status == "idle"


def test_missing_base_runs_beside_the_interview() -> None:
    d = StDriver()
    d.start()
    assert d.s.stages["standards"].status == "idle"  # the job needs the worktree
    d.feed(ev.WorkspaceReady(task_id="T-107", path="/wt/T-107", branch="crew/T-107", at=d.tick()))
    jobs = d.dispatched()
    assert [j.agent for j in jobs] == ["interviewer", "standards"]
    assert jobs[1].workspace_path == "/wt/T-107" and jobs[0].job_id != jobs[1].job_id
    assert d.s.current_agent == "interviewer" and d.s.standards_job_id == jobs[1].job_id
    assert d.s.stages["standards"].status == "active" and d.s.edges["ma-st"] == "active"
    assert d.s.phase == "interviewing"


def test_planner_waits_when_the_interview_ends_first() -> None:
    d = StDriver()
    d.boot()
    d.close_interview()
    assert d.dispatched() == []
    assert d.s.phase == "planning" and d.s.current_job_id is None
    assert d.s.stages["planner"].now == WAITING_STANDARDS and d.s.stages["planner"].status == "idle"
    cost = d.s.cost_usd
    d.standards_result(files=["Glossary.md", "Conventions.md"])
    assert d.job.agent == "planner" and d.s.stages["planner"].status == "active"
    st = d.s.stages["standards"]
    assert st.status == "done" and st.now == "Base criada · 2 arquivos"
    assert d.s.standards is not None and d.s.standards.files == ["Glossary.md", "Conventions.md"]
    assert d.s.cost_usd == cost + 0.2 and d.s.standards_job_id is None
    assert d.s.edges["st-pl"] == "on" and d.s.edges["ma-st"] == "on"


def test_planner_starts_with_the_interview_when_standards_end_first() -> None:
    d = StDriver()
    d.boot()
    d.standards_result()
    assert d.dispatched() == [] and d.s.phase == "interviewing"
    assert d.s.stages["standards"].status == "done"
    d.close_interview()
    assert d.job.agent == "planner"
    d.result(plan())
    assert d.s.phase == "awaiting_approval"


def test_failure_is_an_error_and_the_planner_goes_on() -> None:
    d = StDriver()
    d.boot()
    d.close_interview()
    d.standards_failed("sessão terminou com erro")
    st = d.s.stages["standards"]
    assert st.status == "error" and "sessão terminou com erro" in (st.now or "")
    assert d.job.agent == "planner" and d.s.phase == "planning" and d.s.escalation is None
    assert d.s.standards is None and d.s.edges["st-pl"] == "on"


def test_a_result_without_files_is_an_error() -> None:
    d = StDriver()
    d.boot()
    d.standards_result(files=[], notes="falha ao gravar a base no vault: disco cheio")
    st = d.s.stages["standards"]
    assert st.status == "error" and "disco cheio" in (st.now or "") and d.s.standards is None
    assert d.s.phase == "interviewing"


def test_retryable_failure_only_logs_and_keeps_the_job() -> None:
    d = StDriver()
    d.boot()
    job = d.standards_job()
    d.standards_failed("API indisponível", retryable=True)
    assert d.s.stages["standards"].status == "active" and d.s.standards_job_id == job
    assert "Tentando de novo" in (d.s.stages["standards"].now or "")


def test_progress_goes_to_the_standards_stage() -> None:
    d = StDriver()
    d.boot()
    evt = c.AgentProgress(agent="standards", job_id=d.standards_job(), kind="tool", text="Lendo Conventions")
    d.feed(ev.AgentProgressed(task_id="T-107", evt=evt, at=d.tick()))
    assert d.s.stages["standards"].now == "Lendo Conventions" and d.effects == []
    assert d.s.stages["interviewer"].now != "Lendo Conventions"


def test_interviewer_failure_does_not_touch_the_standards_job() -> None:
    d = StDriver()
    d.boot()
    d.failed("boom")
    assert d.s.phase == "escalated" and d.s.standards_job_id is not None
    d.standards_result()
    assert d.dispatched() == [] and d.s.phase == "escalated"
    d.command(c.EscalationAction(action="more_attempts"))
    d.result(c.InterviewResult(kind="done", spec=SPEC), cost=0.0)
    assert d.job.agent == "planner"


def test_restart_keeps_the_job_in_flight() -> None:
    """The job is durable in CREW_JOBS: nothing to re-issue, its id survives the SQLite round trip."""
    d = StDriver()
    d.boot()
    d.close_interview()
    reloaded = TaskState.model_validate_json(d.s.model_dump_json())
    assert reloaded.standards_job_id == d.s.standards_job_id
    assert not any(isinstance(e, DispatchJob) for e in recovery_effects(reloaded))
    d.state = reloaded
    d.standards_result()
    assert d.job.agent == "planner"


def test_cancel_stops_the_standards_job_too() -> None:
    d = StDriver()
    d.boot()
    job = d.standards_job()
    d.command(c.CancelTask())
    assert d.one(CancelJobs).agent is None  # the interviewer and the standards job: cancel all
    assert d.s.stages["standards"].status == "error" and d.s.standards_job_id is None
    evt = c.AgentResultEvt(
        agent="standards", job_id=job, output=c.StandardsResult(summary="x"), cost_usd=0, duration_s=1
    )
    d.feed(ev.AgentResult(task_id="T-107", evt=evt, at=d.tick()))
    assert d.s.phase == "cancelled" and d.s.standards is None  # stale


def test_cancel_without_the_standards_job_cancels_only_the_agent() -> None:
    d = StDriver(exists=True)
    d.boot()
    d.command(c.CancelTask())
    assert d.one(CancelJobs).agent == "interviewer"

"""Table tests for the pure state machine: every transition, guard, cancel and stale case."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from crew import contracts as c
from crew.orchestrator import events as ev
from crew.orchestrator import machine as m
from crew.orchestrator.effects import (
    BuildFinalReport,
    CancelJobs,
    CreateWorkspace,
    DispatchJob,
    LogStale,
    Persist,
    PublishView,
    Reject,
)
from crew.orchestrator.machine import decide, recovery_effects
from crew.orchestrator.state import Limits, TaskState

from .core_helpers import (
    T0,
    Driver,
    dev,
    fail_run,
    pass_run,
    plan,
    question,
    review_changes,
    review_ok,
)


def agents_dispatched(d: Driver) -> list[str]:
    return [e.job.agent for e in d.history if isinstance(e, DispatchJob)]


# ------------------------------------------------------------------ start


def test_start_manual_creates_workspace_then_interviewer() -> None:
    d = Driver()
    fx = d.start()
    assert [type(e) for e in fx] == [Persist, CreateWorkspace, PublishView]
    assert d.s.phase == "interviewing" and d.s.stages["manual"].status == "done"
    d.feed(ev.WorkspaceReady(task_id="T-107", path="/wt", branch="crew/T-107", at=d.tick()))
    assert d.job.agent == "interviewer" and d.job.spec.title == "Exportar pedidos em CSV"
    assert d.s.edges == {"ma-iv": "active"}


@pytest.mark.parametrize(
    ("cmd", "start_ok", "error"),
    [
        (c.StartTask(repo="r", title="  "), True, m.ERR_TITLE_REQUIRED),
        (c.StartTask(repo="nope", title="x"), False, m.ERR_UNKNOWN_REPO),
    ],
)
def test_start_validation(cmd: c.StartTask, start_ok: bool, error: str) -> None:
    d = Driver()
    d.command(cmd, start=d.params() if start_ok else None)
    assert d.effects == [Reject(error)] and d.state is None


def test_second_start_rejected_while_task_active_and_state_untouched() -> None:
    d = Driver()
    d.boot()
    before = d.s
    d.command(c.StartTask(repo="sample-repo", title="outra"), start=d.params())
    assert d.effects == [Reject(m.ERR_ACTIVE_TASK)]
    assert d.s is before


@pytest.mark.parametrize("terminal", ["done", "cancelled", "failed"])
def test_start_allowed_after_terminal_task(terminal: str) -> None:
    d = Driver()
    if terminal == "done":
        d.to_done()
    elif terminal == "cancelled":
        d.boot()
        d.command(c.CancelTask())
    else:
        d.start()
        d.feed(ev.WorkspaceFailed(task_id="T-107", error="x", at=d.tick()))
    assert d.s.phase == terminal
    d2 = d.command(
        c.StartTask(repo="sample-repo", title="outra"),
        start=ev.StartParams(task_id="T-108", repo=d.params().repo, limits=Limits()),
    )
    assert any(isinstance(e, CreateWorkspace) for e in d2)
    assert d.s.task_id == "T-108" and d.s.phase == "interviewing"


# ------------------------------------------------------------------ commands without a task / wrong phase

COMMANDS: list[c.Command] = [
    c.AnswerInterview(answers=["x"]),
    c.ApprovePlan(),
    c.AdjustPlan(text="x"),
    c.EscalationAction(action="more_attempts"),
    c.CancelTask(),
]


@pytest.mark.parametrize("cmd", COMMANDS, ids=lambda x: x.type)
def test_commands_without_task_rejected(cmd: c.Command) -> None:
    d = Driver()
    d.command(cmd)
    assert d.effects == [Reject(m.ERR_NO_TASK)]
    d.to_done()
    d.command(cmd)
    assert d.effects == [Reject(m.ERR_NO_TASK)], "terminal task counts as no active task"


@pytest.mark.parametrize(
    ("setup", "cmd"),
    [
        ("to_developing", c.ApprovePlan()),
        ("to_developing", c.AdjustPlan(text="x")),
        ("to_developing", c.AnswerInterview(answers=["x"])),
        ("to_developing", c.EscalationAction(action="more_attempts")),
        ("to_awaiting_approval", c.EscalationAction(action="instruct", text="x")),
        ("to_awaiting_approval", c.AnswerInterview(answers=[None])),
        ("to_reviewing", c.ApprovePlan()),
    ],
)
def test_wrong_phase_rejected(setup: str, cmd: c.Command) -> None:
    d = Driver()
    getattr(d, setup)()
    before = d.s
    d.command(cmd)
    assert d.effects == [Reject(m.ERR_WRONG_PHASE)] and d.s is before


def test_conflict_errors_are_the_state_conflicts() -> None:
    assert {m.ERR_ACTIVE_TASK, m.ERR_NO_TASK, m.ERR_WRONG_PHASE} <= m.CONFLICT_ERRORS
    assert m.ERR_TEXT_REQUIRED not in m.CONFLICT_ERRORS


# ------------------------------------------------------------------ interview


def test_interview_flow_in_rounds_accept_and_custom_answers() -> None:
    d = Driver()
    d.boot()
    d.result(c.InterviewResult(kind="question", questions=[question(1), question(2)]))
    s = d.s
    assert s.stages["interviewer"].status == "waiting"
    assert s.pending_questions == [question(1), question(2)] and s.interview_round == 1
    assert d.effects == [Persist(), PublishView()]
    view = s.to_view()
    assert view.interview is not None and len(view.interview.pending) == 2

    d.command(c.AnswerInterview(answers=[None, "  só CSV  "]))  # accept the 1st, custom 2nd
    job = d.job
    assert job.agent == "interviewer" and job.attempt == 2
    assert [t.accepted_recommendation for t in job.interview_history] == [True, False]
    assert [t.answer for t in job.interview_history] == ["Recomendação 1", "só CSV"]
    assert [t.round for t in job.interview_history] == [1, 1]
    assert d.s.decisions == ["Fora de escopo: Recomendação 1", "Critérios de aceite: só CSV"]
    assert d.s.pending_questions == [] and d.s.stages["interviewer"].status == "active"

    d.result(c.InterviewResult(kind="question", questions=[question(3)]))
    d.command(c.AnswerInterview(answers=["Recomendação 3"]))  # picking the recommended option = accepting
    assert d.job.interview_history[2].accepted_recommendation
    assert d.job.interview_history[2].round == 2

    spec = c.TaskSpec(title="T", description="d", repo="other")  # wrong repo on purpose
    d.result(c.InterviewResult(kind="done", spec=spec))
    assert (
        d.s.stages["interviewer"].status == "done"
        and d.s.stages["interviewer"].now == "Spec fechada · 3 decisões"
    )
    job = d.job
    assert job.agent == "planner" and job.spec.repo == "sample-repo"
    assert job.spec.decisions == d.s.decisions, (
        "decisions are filled from the interview when the agent omits them"
    )
    assert d.s.edges == {"ma-iv": "on", "iv-pl": "active"}


def test_blank_answer_counts_as_acceptance() -> None:
    d = Driver()
    d.boot()
    d.result(c.InterviewResult(kind="question", questions=[question(1)]))
    d.command(c.AnswerInterview(answers=["   "]))
    assert d.s.interview_turns[0].accepted_recommendation


def test_answers_must_cover_the_whole_round() -> None:
    d = Driver()
    d.boot()
    d.result(c.InterviewResult(kind="question", questions=[question(1), question(2)]))
    before = d.s
    d.command(c.AnswerInterview(answers=[None]))
    assert d.effects == [Reject(m.ERR_ANSWERS_MISMATCH)] and d.s is before


@pytest.mark.parametrize(
    "bad",
    [c.InterviewResult(kind="question"), c.InterviewResult(kind="done")],
    ids=["question-missing", "spec-missing"],
)
def test_incomplete_interview_result_escalates(bad: c.InterviewResult) -> None:
    d = Driver()
    d.boot()
    d.result(bad)
    assert d.s.phase == "escalated" and d.s.escalation is not None
    assert d.s.escalation.stage == "interviewer" and d.s.escalation.kind == "agent_failed"


# ------------------------------------------------------------------ planning / approval


def test_plan_result_waits_for_approval() -> None:
    d = Driver()
    d.to_planner()
    d.result(plan(), cost=0.3, session="s-plan")
    s = d.s
    assert s.phase == "awaiting_approval" and s.stages["planner"].status == "done"
    assert s.stages["planner"].now == "Plano pronto · 4 passos, 3 arquivos"
    assert s.stages["approval"].status == "waiting"
    assert s.edges == {"ma-iv": "on", "iv-pl": "on", "pl-ap": "active"}
    assert s.cost_usd == pytest.approx(0.3) and s.sessions["planner"] == "s-plan"
    assert d.effects == [Persist(), PublishView()]


def test_adjust_plan_reruns_planner_with_feedback_and_resume() -> None:
    d = Driver()
    d.to_planner()
    d.result(plan(), session="s-plan")
    d.command(c.AdjustPlan(text="  não mexer em auth  "))
    job = d.job
    assert job.agent == "planner" and job.attempt == 2 and job.resume_session_id == "s-plan"
    assert job.feedback == c.Feedback(kind="plan_adjust", text="não mexer em auth")
    assert job.plan == plan()
    s = d.s
    assert s.phase == "planning" and s.stages["approval"].status == "idle"
    assert s.edges["pl-ap"] == "on" and s.active_edge is None
    d.result(plan())
    assert d.s.phase == "awaiting_approval" and d.s.edges["pl-ap"] == "active"


def test_adjust_plan_requires_text() -> None:
    d = Driver()
    d.to_awaiting_approval()
    d.command(c.AdjustPlan(text="   "))
    assert d.effects == [Reject(m.ERR_TEXT_REQUIRED)]


def test_approve_starts_developer_round_1() -> None:
    d = Driver()
    d.to_awaiting_approval()
    d.command(c.ApprovePlan())
    job = d.job
    assert job.agent == "developer" and job.plan == plan() and job.feedback is None
    s = d.s
    assert s.phase == "developing" and s.dev_round == 1
    assert s.stages["approval"].status == "done" and s.stages["developer"].status == "active"
    assert s.edges == {"ma-iv": "on", "iv-pl": "on", "pl-ap": "on", "ap-dv": "active"}


# ------------------------------------------------------------------ developer / tester loop


def test_dev_result_goes_to_tester_always() -> None:
    d = Driver()
    d.to_developing()
    d.result(dev(99))
    assert d.job.agent == "tester" and d.s.phase == "testing"
    assert d.s.dev_rounds[0].round == 1, "round is normalised to the orchestrator counter"
    assert d.s.stages["developer"].now == "Rodada 1 salva no repo local · sem commit"


def test_test_failure_loops_back_with_compact_feedback() -> None:
    d = Driver()
    d.to_testing()
    d.result(fail_run())
    job = d.job
    assert job.agent == "developer" and job.feedback is not None and job.feedback.kind == "test_failures"
    assert job.feedback.test == fail_run()
    s = d.s
    assert (s.phase, s.dev_round, s.test_attempt) == ("developing", 2, 1)
    assert s.stages["tester"].status == "idle" and s.stages["tester"].now == "FALHOU · 46/48 · tentativa 1/3"
    assert s.stages["developer"].now == "Corrigindo: test_range_inclusive_end, test_invalid_range"
    assert s.edges["ts-dv"] == "active"


def test_test_pass_resets_consecutive_counter_and_goes_to_review() -> None:
    d = Driver()
    d.to_testing()
    d.result(fail_run())
    d.result(dev())
    d.result(pass_run())
    assert d.job.agent == "reviewer" and d.s.phase == "reviewing"
    assert d.s.test_attempt == 0 and d.s.review_round == 1
    assert d.s.stages["tester"].now == "PASSOU · 48/48 · cobertura 87%"


def test_third_consecutive_failure_escalates_tester() -> None:
    d = Driver()
    d.to_test_escalation()
    s = d.s
    assert s.phase == "escalated" and s.test_attempt == 3 and s.dev_round == 3
    assert s.escalation is not None and (s.escalation.stage, s.escalation.kind) == ("tester", "test_limit")
    assert s.escalation.reason == "3 falhas consecutivas de teste"
    assert (
        s.stages["tester"].status == "error"
        and s.stages["tester"].now == "Limite 3/3 atingido — expanda pra decidir"
    )
    assert s.active_edge is None and s.current_job_id is None
    assert not d.has(DispatchJob)


def test_pass_in_between_does_not_accumulate_failures() -> None:
    d = Driver(limits=Limits(max_test_attempts=2, max_review_rounds=5))
    d.to_testing()
    d.result(fail_run())  # 1
    d.result(dev())
    d.result(pass_run())
    d.result(review_changes())
    d.result(dev())
    d.result(fail_run())  # consecutive counter restarted: 1 again, not 2
    assert d.s.phase == "developing" and d.s.test_attempt == 1


# ------------------------------------------------------------------ reviewer loop


def test_review_changes_requested_loops_to_developer() -> None:
    d = Driver()
    d.to_reviewing()
    d.result(review_changes())
    job = d.job
    assert job.agent == "developer" and job.feedback is not None and job.feedback.kind == "review_comments"
    s = d.s
    assert s.phase == "developing" and s.dev_round == 2 and s.review_round == 1
    assert s.stages["reviewer"].now == "CHANGES REQUESTED · 1 major, 1 minor"
    assert s.edges["rv-dv"] == "active"
    d.result(dev())
    assert d.job.agent == "tester", "after any dev round: tester, even for review fixes"


def test_review_approved_builds_final_report() -> None:
    d = Driver()
    d.to_reviewing()
    d.result(review_changes())
    d.result(dev())
    d.result(pass_run())
    fx = d.result(review_ok("feat: x"), cost=0.5)
    assert [type(e) for e in fx] == [Persist, BuildFinalReport, PublishView]
    assert d.s.phase == "reviewing" and d.s.boot == "build_report" and d.s.final is None
    assert d.s.stages["reviewer"].status == "done" and d.s.stages["done"].status == "active"
    assert d.s.review is not None
    assert [(x.severity, x.resolved) for x in d.s.review.comments] == [("major", True), ("minor", True)]

    files = [c.FinalFile(path="a.py", status="M", added=3, removed=1)]
    d.report_built(files)
    s = d.s
    assert s.phase == "done" and s.ended_at is not None and s.boot is None
    assert s.stages["done"].status == "done" and s.active_edge is None and s.edges["rv-dn"] == "on"
    assert s.final is not None
    assert s.final.files == files and s.final.branch == "crew/T-107" and s.final.worktree_path == "/wt/T-107"
    assert s.final.commit_message.startswith("feat: x") and s.final.cost_usd == pytest.approx(0.1 * 6 + 0.5)
    assert s.final.duration_s == (s.ended_at - s.started_at).total_seconds()


def test_approved_with_unresolved_major_is_treated_as_changes_requested() -> None:
    d = Driver()
    d.to_reviewing()
    sneaky = c.ReviewResult(
        verdict="approved",
        comments=[c.ReviewComment(severity="major", file="a.py", text="sql injection")],
        commit_message="feat: x",
    )
    d.result(sneaky)
    assert d.s.review is not None and d.s.review.verdict == "changes_requested"
    assert d.job.agent == "developer"


def test_approved_without_commit_message_gets_conventional_fallback() -> None:
    d = Driver()
    d.to_reviewing()
    d.result(review_ok(commit=None))
    d.report_built()
    assert d.s.final is not None and d.s.final.commit_message == "feat: exportar pedidos em CSV"


def test_minor_only_approval_keeps_minors_for_the_report() -> None:
    d = Driver()
    d.to_reviewing()
    minor = c.ReviewResult(
        verdict="approved",
        comments=[c.ReviewComment(severity="nit", file="a.py", text="nome")],
        commit_message="feat: x",
    )
    d.result(minor)
    assert d.s.review is not None and [x.resolved for x in d.s.review.comments] == [False]


def test_second_changes_requested_escalates_reviewer() -> None:
    d = Driver()
    d.to_review_escalation()
    s = d.s
    assert s.phase == "escalated" and s.review_round == 2
    assert s.escalation is not None and (s.escalation.stage, s.escalation.kind) == (
        "reviewer",
        "review_limit",
    )
    assert s.stages["reviewer"].status == "error" and "2/2" in (s.stages["reviewer"].now or "")


# ------------------------------------------------------------------ escalation actions


def test_more_attempts_after_test_limit_adds_two_and_reruns_developer() -> None:
    d = Driver()
    d.to_test_escalation()
    d.command(c.EscalationAction(action="more_attempts"))
    s = d.s
    assert s.limits.max_test_attempts == 5 and s.test_attempt == 3 and s.phase == "developing"
    assert s.escalation is None and s.stages["tester"].status == "idle"
    assert (
        d.job.agent == "developer" and d.job.feedback is not None and d.job.feedback.kind == "test_failures"
    )
    # two more failures are tolerated before escalating again
    d.result(dev())
    d.result(fail_run())
    assert d.s.phase == "developing" and d.s.test_attempt == 4
    d.result(dev())
    d.result(fail_run())
    assert d.s.phase == "escalated" and d.s.test_attempt == 5


def test_instruct_requires_text_and_resets_test_cycle() -> None:
    d = Driver()
    d.to_test_escalation()
    d.command(c.EscalationAction(action="instruct", text="  "))
    assert d.effects == [Reject(m.ERR_TEXT_REQUIRED)] and d.s.phase == "escalated"
    d.command(c.EscalationAction(action="instruct", text="usar fake timers"))
    job = d.job
    assert job.agent == "developer" and job.feedback is not None
    assert job.feedback.kind == "human_instruction" and job.feedback.text == "usar fake timers"
    assert job.feedback.test == fail_run()
    assert d.s.test_attempt == 0 and d.s.phase == "developing"
    assert d.s.stages["developer"].now == 'Seguindo sua instrução: "usar fake timers"'


def test_more_attempts_after_review_limit() -> None:
    d = Driver()
    d.to_review_escalation()
    d.command(c.EscalationAction(action="more_attempts"))
    assert d.s.limits.max_review_rounds == 4 and d.job.agent == "developer"
    assert d.job.feedback is not None and d.job.feedback.kind == "review_comments"


def test_instruct_after_review_limit_resets_review_cycle() -> None:
    d = Driver()
    d.to_review_escalation()
    d.command(c.EscalationAction(action="instruct", text="faça X"))
    assert d.s.review_round == 0 and d.job.feedback is not None and d.job.feedback.review is not None
    assert d.s.edges["rv-dv"] == "active"


def test_replan_clears_counters_keeps_history_and_calls_planner() -> None:
    d = Driver()
    d.to_test_escalation()
    d.s.sessions["developer"] = "dev-sess"
    d.command(c.EscalationAction(action="replan"))
    job = d.job
    s = d.s
    assert job.agent == "planner" and job.feedback is not None and job.feedback.kind == "plan_adjust"
    assert job.feedback.text is not None and "3 falhas consecutivas de teste" in job.feedback.text
    assert "test_range_inclusive_end" in job.feedback.text
    assert (s.test_attempt, s.review_round) == (0, 0) and s.dev_round == 3
    assert len(s.dev_rounds) == 3 and len(s.test_runs) == 3
    assert "developer" not in s.sessions
    assert all(s.stages[k].status == "idle" for k in ("approval", "developer", "tester", "reviewer"))
    assert s.phase == "planning"
    d.result(plan())
    assert d.s.phase == "awaiting_approval", "a replan needs a new approval"
    d.command(c.ApprovePlan())
    assert d.job.agent == "developer" and d.s.dev_round == 4


def test_replan_not_available_before_spec_closes() -> None:
    d = Driver()
    d.boot()
    d.failed("x")
    d.command(c.EscalationAction(action="replan"))
    assert d.effects == [Reject(m.ERR_REPLAN_UNAVAILABLE)]


# ------------------------------------------------------------------ agent failures / timeouts


def test_non_retryable_failure_escalates_with_agent_stage() -> None:
    d = Driver()
    d.to_developing()
    d.failed("submit_dev nunca chamado")
    s = d.s
    assert s.phase == "escalated" and s.escalation is not None
    assert (s.escalation.stage, s.escalation.kind) == ("developer", "agent_failed")
    assert "submit_dev nunca chamado" in s.escalation.reason
    assert s.stages["developer"].status == "error" and s.dev_round == 0, "the failed round is given back"


def test_retryable_failure_only_logs() -> None:
    d = Driver()
    d.to_developing()
    d.failed("rate limit", retryable=True)
    assert d.s.phase == "developing" and d.effects == []
    assert d.s.stages["developer"].now == "Tentando de novo: rate limit"


def test_more_attempts_after_agent_failure_retries_same_job_and_round() -> None:
    d = Driver()
    d.to_testing()
    d.result(fail_run())
    d.failed("crash")  # developer round 2 died
    assert d.s.dev_round == 1
    d.command(c.EscalationAction(action="more_attempts"))
    assert d.job.agent == "developer" and d.s.dev_round == 2
    assert d.job.feedback is not None and d.job.feedback.kind == "test_failures", (
        "same feedback as the failed job"
    )
    assert d.job.attempt == 3


@pytest.mark.parametrize(
    ("setup", "stage", "expected_agent", "expected_kind"),
    [
        ("to_testing", "tester", "developer", "human_instruction"),
        ("to_reviewing", "reviewer", "developer", "human_instruction"),
        ("to_developing", "developer", "developer", "human_instruction"),
        ("to_awaiting_approval", "planner", "planner", "plan_adjust"),
    ],
)
def test_instruct_after_agent_failure(
    setup: str, stage: str, expected_agent: str, expected_kind: str
) -> None:
    d = Driver()
    if stage == "planner":
        d.to_planner()
    else:
        getattr(d, setup)()
    d.failed("x")
    assert d.s.escalation is not None and d.s.escalation.stage == stage
    d.command(c.EscalationAction(action="instruct", text="faça assim"))
    assert (
        d.job.agent == expected_agent and d.job.feedback is not None and d.job.feedback.kind == expected_kind
    )
    assert d.job.feedback.text == "faça assim"


def test_replan_after_agent_failure_in_developer_goes_to_planner() -> None:
    d = Driver()
    d.to_developing()
    d.failed("x")
    d.command(c.EscalationAction(action="replan"))
    assert d.job.agent == "planner"


def test_job_timeout_escalates_and_cancels_jobs() -> None:
    d = Driver()
    d.to_developing()
    job_id = d.s.current_job_id
    assert job_id is not None
    fx = d.feed(ev.JobTimedOut(task_id="T-107", job_id=job_id, at=d.tick()))
    assert CancelJobs("T-107", "developer") in fx
    assert d.s.phase == "escalated" and d.s.escalation is not None
    assert d.s.escalation.reason == "developer falhou: sem resposta após 20 min"


def test_timeout_of_old_job_is_ignored() -> None:
    d = Driver()
    d.to_developing()
    before = d.s
    fx = d.feed(ev.JobTimedOut(task_id="T-107", job_id=uuid4(), at=d.tick()))
    assert d.s is before and [type(e) for e in fx] == [LogStale]


@pytest.mark.parametrize(
    ("setup", "wrong", "expected"),
    [
        ("to_planner", dev(), "esperava Plan"),
        ("to_developing", plan(), "esperava DevResult"),
        ("to_testing", dev(), "esperava TestResult"),
        ("to_reviewing", pass_run(), "esperava ReviewResult"),
    ],
)
def test_wrong_output_type_for_agent_escalates(setup: str, wrong: c.AgentOutput, expected: str) -> None:
    d = Driver()
    getattr(d, setup)()
    stage = d.s.current_agent
    d.result(wrong)
    assert d.s.phase == "escalated" and d.s.escalation is not None
    assert d.s.escalation.stage == stage and expected in d.s.escalation.reason


# ------------------------------------------------------------------ budget


def test_budget_exhausted_blocks_next_dispatch_and_escalates_next_stage() -> None:
    d = Driver(limits=Limits(budget_usd=1.0))
    d.to_testing()
    fx = d.result(fail_run(), cost=1.0)  # spends everything, would go back to the developer
    assert not any(isinstance(e, DispatchJob) for e in fx)
    s = d.s
    assert s.phase == "escalated" and s.escalation is not None
    assert (s.escalation.kind, s.escalation.stage) == ("budget", "developer")
    assert "orçamento" in s.escalation.reason and s.escalation.pending is not None
    assert s.escalation.pending.agent == "developer" and s.escalation.pending.edge == "ts-dv"
    assert s.stages["developer"].status == "error"
    assert s.dev_round == 1, "the dispatch that did not happen is not counted"


def test_budget_more_attempts_gives_50_percent_headroom_and_resumes() -> None:
    d = Driver(limits=Limits(budget_usd=0.3))
    d.to_testing()  # spent 0.2
    d.result(fail_run(), cost=0.1)  # 0.3 == budget -> blocked
    assert d.s.phase == "escalated"
    d.command(c.EscalationAction(action="more_attempts"))
    assert d.s.limits.budget_usd == pytest.approx(0.45)
    assert d.job.agent == "developer" and d.job.budget_usd == pytest.approx(0.15)
    assert d.s.dev_round == 2 and d.s.edges["ts-dv"] == "active" and d.s.phase == "developing"


@pytest.mark.parametrize("action", ["instruct", "replan"])
def test_budget_blocks_other_actions(action: str) -> None:
    d = Driver(limits=Limits(budget_usd=1.0))
    d.to_testing()
    d.result(fail_run(), cost=1.0)
    d.command(c.EscalationAction(action=action, text="x"))
    assert d.effects == [Reject(m.ERR_BUDGET)]


def test_last_review_approval_completes_even_if_budget_is_gone() -> None:
    d = Driver(limits=Limits(budget_usd=0.35))
    d.to_reviewing()  # 0.3 spent, reviewer still dispatched
    d.result(review_ok(), cost=0.5)
    assert d.has(BuildFinalReport) and d.s.phase == "reviewing" and d.s.boot == "build_report"


def test_job_budget_is_what_remains() -> None:
    d = Driver(limits=Limits(budget_usd=2.0))
    d.to_planner()
    assert d.job.budget_usd == pytest.approx(2.0)
    d.result(plan(), cost=0.75)
    d.command(c.ApprovePlan())
    assert d.job.budget_usd == pytest.approx(1.25)


def test_overspend_still_boosts_above_cost() -> None:
    d = Driver(limits=Limits(budget_usd=1.0))
    d.to_testing()
    d.result(fail_run(), cost=3.0)
    d.command(c.EscalationAction(action="more_attempts"))
    assert d.s.limits.budget_usd > d.s.cost_usd
    assert d.s.phase == "developing"


# ------------------------------------------------------------------ sessions / attempts / ids


def test_session_ids_are_saved_per_agent_and_resumed() -> None:
    d = Driver()
    d.to_awaiting_approval()
    d.command(c.ApprovePlan())
    assert d.job.resume_session_id is None
    d.result(dev(), session="dev-1")
    assert d.job.agent == "tester" and d.job.resume_session_id is None
    d.result(fail_run(), session="test-1")
    assert d.job.agent == "developer" and d.job.resume_session_id == "dev-1"
    d.result(dev(), session="dev-2")
    d.result(pass_run(), session="test-2")
    assert d.job.agent == "reviewer"
    assert d.s.sessions == {"developer": "dev-2", "tester": "test-2"}


def test_job_ids_are_unique_deterministic_and_attempts_increment() -> None:
    d = Driver()
    d.to_testing()
    ids = [e.job.job_id for e in d.history if isinstance(e, DispatchJob)]
    assert len(ids) == len(set(ids)) == 5  # interviewer x2, planner, developer, tester
    d2 = Driver()
    d2.to_testing()
    assert [e.job.job_id for e in d2.history if isinstance(e, DispatchJob)] == ids
    d.result(fail_run())
    d.result(dev())
    assert d.job.agent == "tester" and d.job.attempt == 2


def test_dispatch_order_for_manual_flow_with_failures() -> None:
    d = Driver()
    d.to_reviewing()
    d.result(review_changes())
    d.result(dev())
    d.result(pass_run())
    d.result(review_ok())
    assert agents_dispatched(d) == [
        "interviewer",
        "interviewer",
        "planner",
        "developer",
        "tester",
        "reviewer",
        "developer",
        "tester",
        "reviewer",
    ]


# ------------------------------------------------------------------ cancel


@pytest.mark.parametrize(
    "setup",
    [
        "start",
        "boot",
        "to_awaiting_approval",
        "to_developing",
        "to_testing",
        "to_reviewing",
        "to_test_escalation",
        "to_review_escalation",
    ],
)
def test_cancel_in_every_non_terminal_phase(setup: str) -> None:
    d = Driver()
    getattr(d, setup)()
    agent = d.s.current_agent
    d.command(c.CancelTask())
    s = d.s
    assert s.phase == "cancelled" and s.ended_at is not None and s.current_job_id is None
    assert CancelJobs("T-107", agent) in d.effects
    assert [type(e) for e in d.effects] == [Persist, CancelJobs, PublishView]
    assert s.active_edge is None
    assert all(st.status not in ("active", "waiting") for st in s.stages.values())
    assert recovery_effects(s) == []


def test_cancel_while_interview_waits_marks_stage() -> None:
    d = Driver()
    d.boot()
    d.result(c.InterviewResult(kind="question", questions=[question(1)]))
    d.command(c.CancelTask())
    assert (
        d.s.stages["interviewer"].status == "error"
        and d.s.stages["interviewer"].now == "Cancelada pelo usuário"
    )


def test_results_after_cancel_are_stale() -> None:
    d = Driver()
    d.to_developing()
    old_job = d.s.current_job_id
    assert old_job is not None
    d.command(c.CancelTask())
    cancelled = d.s
    evt = c.AgentResultEvt(agent="developer", job_id=old_job, output=dev(), cost_usd=1.0)
    fx = d.feed(ev.AgentResult(task_id="T-107", evt=evt, at=d.tick()))
    assert d.s is cancelled and [type(e) for e in fx] == [LogStale]


# ------------------------------------------------------------------ stale / foreign events


def test_result_with_unknown_job_id_is_ignored_without_side_effects() -> None:
    d = Driver()
    d.to_developing()
    before = d.s.model_dump()
    evt = c.AgentResultEvt(agent="developer", job_id=uuid4(), output=dev(), cost_usd=9.0)
    fx = d.feed(ev.AgentResult(task_id="T-107", evt=evt, at=d.tick()))
    assert d.s.model_dump() == before
    assert len(fx) == 1 and isinstance(fx[0], LogStale)


def test_duplicate_result_delivery_is_idempotent() -> None:
    d = Driver()
    d.to_developing()
    job_id = d.s.current_job_id
    assert job_id is not None
    d.result(dev())
    after_first = d.s.model_dump()
    evt = c.AgentResultEvt(agent="developer", job_id=job_id, output=dev(), cost_usd=0.1)
    fx = d.feed(ev.AgentResult(task_id="T-107", evt=evt, at=d.tick()))
    assert d.s.model_dump() == after_first and isinstance(fx[0], LogStale)


def test_result_for_other_task_or_without_task_is_ignored() -> None:
    d = Driver()
    evt = c.AgentResultEvt(agent="planner", job_id=uuid4(), output=plan())
    assert decide(None, ev.AgentResult(task_id="T-1", evt=evt, at=T0)) == (
        None,
        [LogStale("T-1", "AgentResult", evt.job_id)],
    )
    d.boot()
    evt2 = c.AgentResultEvt(agent="planner", job_id=d.s.current_job_id or uuid4(), output=plan())
    before = d.s
    new, fx = decide(d.s, ev.AgentResult(task_id="T-999", evt=evt2, at=T0))
    assert new is before and isinstance(fx[0], LogStale)


def test_stale_io_events_are_ignored() -> None:
    d = Driver()
    d.to_developing()
    before = d.s
    for e in (
        ev.WorkspaceReady(task_id="T-107", path="/x", branch="b", at=d.tick()),
        ev.WorkspaceFailed(task_id="T-107", error="x", at=d.tick()),
        ev.ReportBuilt(task_id="T-107", files=[], at=d.tick()),
        ev.WorkspaceReady(task_id="T-1", path="/x", branch="b", at=d.tick()),
    ):
        new, fx = decide(d.s, e)
        assert new is before and isinstance(fx[0], LogStale)


# ------------------------------------------------------------------ boot failures


def test_workspace_failure_fails_the_task() -> None:
    d = Driver()
    d.start()
    d.feed(ev.WorkspaceFailed(task_id="T-107", error="repo sujo", at=d.tick()))
    s = d.s
    assert s.phase == "failed" and s.ended_at is not None and s.stages["manual"].status == "error"
    assert "repo sujo" in (s.stages["manual"].now or "")
    assert [type(e) for e in d.effects] == [Persist, PublishView]


# ------------------------------------------------------------------ progress / logs


def test_progress_updates_now_and_log_without_effects() -> None:
    d = Driver()
    d.to_developing()
    fx = d.progress("Editando shop/report.py")
    assert fx == []
    st = d.s.stages["developer"]
    assert st.now == "Editando shop/report.py" and st.logs[-1].text == "Editando shop/report.py"


def test_progress_from_dead_job_is_dropped_and_logs_capped_at_50() -> None:
    d = Driver()
    d.to_developing()
    assert d.progress("x", job_id=uuid4()) == []
    assert d.s.stages["developer"].now != "x"
    for i in range(80):
        d.progress(f"l{i}")
    logs = d.s.stages["developer"].logs
    assert len(logs) == 50 and logs[-1].text == "l79"
    assert len(d.s.to_view().stages.developer.logs) == 50


# ------------------------------------------------------------------ recovery & serialisation


def test_recovery_for_create_workspace_and_report() -> None:
    d = Driver()
    d.start()
    assert recovery_effects(d.s) == [CreateWorkspace("T-107", "sample-repo")]
    d2 = Driver()
    d2.to_reviewing()
    d2.result(review_ok())
    assert recovery_effects(d2.s) == [BuildFinalReport("T-107", "sample-repo", "/wt/T-107")]
    d3 = Driver()
    d3.to_developing()
    assert recovery_effects(d3.s) == []


def test_state_json_roundtrip_keeps_machine_working() -> None:
    d = Driver()
    d.to_testing()
    restored = TaskState.model_validate_json(d.s.model_dump_json())
    assert restored == d.s
    d.state = restored
    d.result(fail_run())
    assert d.job.agent == "developer"


def test_decide_never_mutates_input_state() -> None:
    d = Driver()
    d.to_testing()
    snapshot = d.s.model_dump()
    state = d.s
    evt = c.AgentResultEvt(agent="tester", job_id=state.current_job_id or uuid4(), output=fail_run())
    decide(state, ev.AgentResult(task_id="T-107", evt=evt, at=T0 + timedelta(hours=1)))
    assert state.model_dump() == snapshot


def test_job_stopped_by_its_cap_escalates_as_budget_and_more_attempts_raises_the_budget() -> None:
    from crew.bus import JOB_BUDGET_EXCEEDED

    d = Driver(limits=Limits(budget_usd=2.0))
    d.to_developing()
    d.failed(JOB_BUDGET_EXCEEDED)
    s = d.s
    assert s.escalation is not None and (s.escalation.kind, s.escalation.stage) == ("budget", "developer")
    assert s.dev_round == 0, "the round that did not finish is given back"
    d.command(c.EscalationAction(action="more_attempts"))
    assert d.s.limits.budget_usd == pytest.approx(3.0)
    assert d.job.agent == "developer" and d.job.budget_usd > 2.0


def test_legacy_agent_failed_with_the_budget_error_also_boosts() -> None:
    from crew.bus import JOB_BUDGET_EXCEEDED

    d = Driver(limits=Limits(budget_usd=2.0))
    d.to_developing()
    m._fail_job(d.state, d.tick(), "developer", JOB_BUDGET_EXCEEDED, d.s.inflight)  # type: ignore[arg-type]
    assert d.s.escalation is not None and d.s.escalation.kind == "agent_failed"
    d.command(c.EscalationAction(action="more_attempts"))
    assert d.s.limits.budget_usd == pytest.approx(3.0)

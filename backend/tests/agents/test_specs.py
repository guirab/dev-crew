"""AgentSpec table, semantic checks and deterministic finalizers."""

from __future__ import annotations

import pytest

from crew.agents.specs import (
    DEFAULT_TEST_GLOBS,
    SPECS,
    check_dev,
    check_interview,
    check_plan,
    check_review,
    check_test,
    effective_test_globs,
    finalize_dev,
    finalize_interview,
    finalize_test,
)
from crew.contracts import (
    AGENTS,
    DevResult,
    InterviewQuestion,
    InterviewResult,
    Plan,
    ReviewComment,
    ReviewResult,
    TestFailure,
    TestResult,
)

from .factories import make_job, make_plan, make_repo, make_spec


def test_every_agent_has_a_spec_with_the_table_values() -> None:
    assert set(SPECS) == set(AGENTS)
    table = {
        # agent: (model, tools, bash, write, max_turns)
        "interviewer": ("claude-sonnet-5-5", ("Read", "Glob", "Grep"), "none", "none", 15),
        "planner": ("claude-opus-5-5", ("Read", "Glob", "Grep", "Bash"), "readonly", "none", 30),
        "developer": (
            "claude-sonnet-5-5",
            ("Read", "Glob", "Grep", "Write", "Edit", "Bash"),
            "full",
            "workspace",
            60,
        ),
        "tester": (
            "claude-sonnet-5-5",
            ("Read", "Glob", "Grep", "Write", "Edit", "Bash"),
            "full",
            "tests_only",
            40,
        ),
        "reviewer": ("claude-opus-5-5", ("Read", "Glob", "Grep", "Bash"), "readonly", "none", 30),
    }
    for agent, (model, tools, bash, write, turns) in table.items():
        spec = SPECS[agent]  # type: ignore[index]
        assert spec.default_model == model
        assert set(spec.tools) == set(tools)
        assert (spec.bash, spec.write, spec.max_turns) == (bash, write, turns)
        assert spec.resume_across_rounds is True
        assert spec.name == agent


def test_permission_modes_never_bypass() -> None:
    for spec in SPECS.values():
        assert spec.permission_mode in ("default", "acceptEdits")
    assert SPECS["developer"].permission_mode == "acceptEdits"
    assert SPECS["tester"].permission_mode == "acceptEdits"
    assert SPECS["reviewer"].permission_mode == "default"


def test_submit_names_are_unique_and_prefixed() -> None:
    names = [s.submit_name for s in SPECS.values()]
    assert len(set(names)) == 5
    assert all(n.startswith("submit_") for n in names)


def test_budget_caps_fit_inside_the_default_task_budget() -> None:
    assert all(0 < s.budget_cap_usd <= 5.0 for s in SPECS.values())


def test_only_the_tester_writes_tests_only() -> None:
    assert [a for a, s in SPECS.items() if s.write == "tests_only"] == ["tester"]
    assert [a for a, s in SPECS.items() if s.write == "workspace"] == ["developer"]


def test_test_globs_prefer_repo_config() -> None:
    assert effective_test_globs(make_job("tester", repo=make_repo(test_globs=["spec/**"]))) == ("spec/**",)
    assert effective_test_globs(make_job("tester", repo=make_repo(test_globs=[]))) == DEFAULT_TEST_GLOBS


# ---------------------------------------------------------------------------------- checks
Q = InterviewQuestion(topic="t", question="q", recommendation="r")


def test_interview_check() -> None:
    spec = make_spec()
    assert check_interview(InterviewResult(kind="question", questions=[Q])) is None
    assert check_interview(InterviewResult(kind="done", spec=spec)) is None
    assert "questions" in (check_interview(InterviewResult(kind="question")) or "")
    assert "spec" in (check_interview(InterviewResult(kind="question", questions=[Q], spec=spec)) or "")
    assert "spec" in (check_interview(InterviewResult(kind="done")) or "")
    assert "questions" in (check_interview(InterviewResult(kind="done", spec=spec, questions=[Q])) or "")


def test_interview_check_rounds() -> None:
    other = InterviewQuestion(topic="u", question="q2", recommendation="b", options=["a", "b"])
    assert check_interview(InterviewResult(kind="question", questions=[Q, other])) is None
    assert "topic" in (check_interview(InterviewResult(kind="question", questions=[Q, Q])) or "")
    off = InterviewQuestion(topic="u", question="q2", recommendation="z", options=["a", "b"])
    assert "options" in (check_interview(InterviewResult(kind="question", questions=[off])) or "")


def test_plan_check() -> None:
    assert check_plan(make_plan()) is None
    assert "steps" in (check_plan(make_plan().model_copy(update={"steps": []})) or "")
    assert "acceptance" in (check_plan(make_plan().model_copy(update={"acceptance_criteria": []})) or "")


def test_dev_check() -> None:
    assert check_dev(DevResult(round=1, summary="ok", files_changed=[])) is None
    assert check_dev(DevResult(round=1, summary=" ", files_changed=[])) is not None


def test_test_result_check() -> None:
    fail = TestFailure(test="t", message="boom")
    assert check_test(TestResult(ok=True, passed=3, total=3, command="pytest")) is None
    assert check_test(TestResult(ok=False, passed=2, total=3, failures=[fail], command="pytest")) is None
    assert check_test(TestResult(ok=True, passed=2, total=3, failures=[fail], command="pytest")) is not None
    assert check_test(TestResult(ok=False, passed=2, total=3, command="pytest")) is not None
    assert check_test(TestResult(ok=True, passed=4, total=3, command="pytest")) is not None


MAJOR = ReviewComment(severity="major", file="a.py", line=1, text="bug")
MINOR = ReviewComment(severity="minor", file="a.py", text="nit")


@pytest.mark.parametrize(
    ("result", "ok"),
    [
        (ReviewResult(verdict="approved", commit_message="feat(relatorio): filtro por datas"), True),
        (ReviewResult(verdict="approved", comments=[MINOR], commit_message="fix: corrige soma"), True),
        (ReviewResult(verdict="approved", commit_message="feat!: muda API\n\n- detalhe"), True),
        (ReviewResult(verdict="changes_requested", comments=[MAJOR]), True),
        (ReviewResult(verdict="changes_requested", comments=[MAJOR, MINOR]), True),
        (
            ReviewResult(
                verdict="approved",
                comments=[MAJOR.model_copy(update={"resolved": True}), MINOR],
                commit_message="feat: x",
            ),
            True,
        ),
        (
            ReviewResult(verdict="changes_requested", comments=[MAJOR.model_copy(update={"resolved": True})]),
            False,
        ),
        (ReviewResult(verdict="approved"), False),
        (ReviewResult(verdict="approved", commit_message="  "), False),
        (ReviewResult(verdict="approved", comments=[MAJOR], commit_message="feat: x"), False),
        (ReviewResult(verdict="approved", commit_message="adiciona filtro"), False),
        (ReviewResult(verdict="approved", commit_message="Feature: filtro"), False),
        (ReviewResult(verdict="approved", commit_message="feat: " + "x" * 80), False),
        (ReviewResult(verdict="changes_requested"), False),
        (ReviewResult(verdict="changes_requested", comments=[MINOR]), False),
    ],
)
def test_review_check(result: ReviewResult, ok: bool) -> None:
    assert (check_review(result) is None) is ok


# ---------------------------------------------------------------------------------- finalizers
def test_finalize_dev_forces_the_round_from_the_job() -> None:
    job = make_job("developer", attempt=3)
    assert finalize_dev(DevResult(round=99, summary="s", files_changed=[]), job).round == 3


def test_finalize_test_fills_the_command_when_missing() -> None:
    job = make_job("tester")
    out = finalize_test(TestResult(ok=True, passed=1, total=1, command=" "), job)
    assert out.command == "python -m pytest -q"
    keep = finalize_test(TestResult(ok=True, passed=1, total=1, command="pytest -x"), job)
    assert keep.command == "pytest -x"


def test_finalize_interview_pins_identity_fields_to_the_job() -> None:
    job = make_job("interviewer")
    drifted = make_spec(repo="other-repo", decisions=["usar UTC"], acceptance_criteria=["ac"])
    out = finalize_interview(InterviewResult(kind="done", spec=drifted), job)
    assert out.spec is not None
    assert out.spec.repo == "sample-repo"
    assert out.spec.decisions == ["usar UTC"]
    assert out.spec.acceptance_criteria == ["ac"]
    question = InterviewResult(kind="question", questions=[Q])
    assert finalize_interview(question, job) == question


def test_specs_registry_finalizers_are_the_module_functions() -> None:
    assert SPECS["developer"].finalize is finalize_dev
    assert SPECS["planner"].finalize is None
    assert SPECS["planner"].check is check_plan
    assert isinstance(make_plan(), Plan)

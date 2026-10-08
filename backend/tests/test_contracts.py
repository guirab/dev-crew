from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from crew import contracts as c
from crew.bus import subjects as s
from crew.schema import build_schema

from .conftest import FIXTURES_DIR

EXPECTED_FIXTURES = {
    "interviewing",
    "planning",
    "awaiting_approval",
    "developing",
    "testing_failed",
    "reviewing",
    "escalated",
    "done",
}


def _repo() -> c.RepoContext:
    return c.RepoContext(
        name="sample-repo", base_branch="main", test_cmd="pytest -q", test_globs=["tests/**"]
    )


def _spec() -> c.TaskSpec:
    return c.TaskSpec(title="t", description="d", repo="sample-repo")


def test_fixtures_exist_and_validate() -> None:
    found = {p.name.removeprefix("view.").removesuffix(".json") for p in FIXTURES_DIR.glob("view.*.json")}
    assert found == EXPECTED_FIXTURES
    for p in FIXTURES_DIR.glob("view.*.json"):
        view = c.TaskView.model_validate_json(p.read_text("utf-8"))
        assert c.TaskView.model_validate(view.model_dump(mode="json")) == view


def test_job_round_trip() -> None:
    job = c.AgentJob(
        job_id=uuid4(),
        task_id="T-1",
        agent="developer",
        attempt=1,
        repo=_repo(),
        spec=_spec(),
        feedback=c.Feedback(kind="human_instruction", text="use fake timers"),
    )
    assert c.AgentJob.model_validate_json(job.model_dump_json()) == job


@pytest.mark.parametrize(
    "output",
    [
        c.InterviewResult(
            kind="question",
            questions=[c.InterviewQuestion(topic="a", question="b", recommendation="c", options=["c", "d"])],
        ),
        c.Plan(
            summary="s",
            steps=["a"],
            files=[c.PlanFile(path="x.py", change="A")],
            acceptance_criteria=["ok"],
            test_strategy="t",
        ),
        c.DevResult(round=1, summary="s", files_changed=[]),
        c.TestResult(ok=True, passed=1, total=1, command="pytest"),
        c.ReviewResult(verdict="approved", commit_message="feat: x"),
    ],
)
def test_result_event_discriminates_output(output: c.AgentOutput) -> None:
    evt = c.AgentResultEvt(agent="planner", job_id=uuid4(), output=output)
    back = c.AgentResultEvt.model_validate_json(evt.model_dump_json())
    assert type(back.output) is type(output)
    assert back == evt


def _plan(**extra: object) -> c.Plan:
    return c.Plan(
        summary="s",
        steps=["a"],
        files=[c.PlanFile(path="x.py", change="A")],
        acceptance_criteria=["ok"],
        test_strategy="t",
        **extra,  # type: ignore[arg-type]
    )


def test_plan_essential_code_is_optional() -> None:
    assert _plan().essential_code is None
    plan = _plan(essential_code="def f(x: int) -> int: ...")
    assert c.Plan.model_validate_json(plan.model_dump_json()).essential_code == plan.essential_code
    prop = build_schema()["$defs"]["Plan"]["properties"]["essential_code"]
    assert prop["default"] is None
    assert {"type": "null"} in prop["anyOf"]


def test_plan_doc_essential_code_section_only_when_present() -> None:
    from crew.plan_doc import render

    assert "Código essencial" not in render("T-1", "t", _plan())
    assert "## Código essencial\n\n```\nx = 1\n```" in render("T-1", "t", _plan(essential_code="x = 1"))


def test_envelope_wrap_and_decode() -> None:
    progress = c.AgentProgress(agent="tester", job_id=uuid4(), kind="tool", text="$ pytest -q")
    env = c.Envelope.wrap("T-1", "progress", progress, source="tester")
    back = c.Envelope.model_validate_json(env.model_dump_json())
    assert back.decode_payload() == progress
    with pytest.raises(TypeError):
        c.Envelope.wrap("T-1", "result", progress, source="tester")


def test_commands_discriminated() -> None:
    cmd = c.CommandAdapter.validate_json('{"type": "answer_interview", "answers": [null, "x"]}')
    assert isinstance(cmd, c.AnswerInterview) and cmd.answers == [None, "x"]
    with pytest.raises(ValidationError):
        c.CommandAdapter.validate_json('{"type": "answer_interview"}')
    cmd = c.CommandAdapter.validate_python({"type": "escalation", "action": "instruct", "text": "x"})
    assert isinstance(cmd, c.EscalationAction)
    with pytest.raises(ValidationError):
        c.CommandAdapter.validate_python({"type": "nope"})


def test_ws_message() -> None:
    ad = TypeAdapter(c.WsMessage)
    assert isinstance(ad.validate_python({"type": "view", "data": None}), c.WsView)


def test_contracts_are_strict() -> None:
    with pytest.raises(ValidationError):
        c.TaskSpec(title="t", description="d", repo="r", unknown=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        c.TestFailure(test="t", message="x" * 401)


def test_subjects() -> None:
    assert s.job_subject("developer") == "crew.job.developer"
    assert s.evt_subject("T-7", "result") == "crew.evt.T-7.result"
    assert s.parse_evt_subject("crew.evt.T-7.view") == ("T-7", "view")
    assert s.cancel_subject("T-7") == "crew.ctl.T-7.cancel"


def test_schema_has_ui_types() -> None:
    defs = build_schema()["$defs"]
    for name in (
        "TaskView",
        "WsMessage",
        "Command",
        "CommandReply",
        "StartTask",
        "Stages",
    ):
        assert name in defs, name
    json.dumps(defs)

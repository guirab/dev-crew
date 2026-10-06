"""``TaskState.to_view()`` must reproduce the M0 fixtures (phase, statuses, edges, counters) from events."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from crew import contracts as c

from .conftest import FIXTURES_DIR
from .core_helpers import (
    Driver,
    dev,
    fail_run,
    pass_run,
    question,
    review_changes,
    review_ok,
)


def load(name: str) -> c.TaskView:
    return c.TaskView.model_validate_json((FIXTURES_DIR / f"view.{name}.json").read_text("utf-8"))


def statuses(v: c.TaskView) -> dict[str, str]:
    return {k: s["status"] for k, s in v.stages.model_dump().items()}


def seq_interviewing() -> Driver:
    d = Driver()
    d.boot()
    d.result(c.InterviewResult(kind="question", questions=[question(1)]))
    d.command(c.AnswerInterview(answers=[None]))
    d.result(c.InterviewResult(kind="question", questions=[question(2), question(3)]))
    return d


def seq_planning() -> Driver:
    d = Driver()
    d.to_planner()
    return d


def seq_awaiting_approval() -> Driver:
    d = Driver()
    d.to_awaiting_approval()
    return d


def seq_developing() -> Driver:
    d = Driver()
    d.to_developing()
    return d


def seq_testing_failed() -> Driver:
    d = Driver()
    d.to_testing()
    d.result(fail_run())
    return d


def seq_reviewing() -> Driver:
    d = Driver()
    d.to_testing()
    d.result(fail_run())
    d.result(dev())
    d.result(pass_run())
    return d


def seq_escalated() -> Driver:
    d = Driver()
    d.to_test_escalation()
    return d


def seq_done() -> Driver:
    d = Driver()
    d.to_testing()
    d.result(fail_run())
    d.result(dev())
    d.result(pass_run())
    d.result(review_changes())
    d.result(dev())
    d.result(pass_run())
    d.result(review_ok("feat: filtro por intervalo de datas"))
    d.report_built([c.FinalFile(path="shop/report.py", status="M", added=24, removed=3)])
    return d


SEQUENCES: dict[str, Callable[[], Driver]] = {
    "interviewing": seq_interviewing,
    "planning": seq_planning,
    "awaiting_approval": seq_awaiting_approval,
    "developing": seq_developing,
    "testing_failed": seq_testing_failed,
    "reviewing": seq_reviewing,
    "escalated": seq_escalated,
    "done": seq_done,
}


def test_every_fixture_has_a_sequence() -> None:
    names = {p.name.removeprefix("view.").removesuffix(".json") for p in FIXTURES_DIR.glob("view.*.json")}
    assert names == set(SEQUENCES)


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_view_matches_fixture(name: str) -> None:
    expected = load(name)
    got = SEQUENCES[name]().s.to_view()
    assert got.phase == expected.phase
    assert statuses(got) == statuses(expected)
    assert got.edges == expected.edges
    assert got.active_edge == expected.active_edge
    assert got.counters == expected.counters
    assert got.repo == expected.repo
    assert (got.interview is None) == (expected.interview is None)
    if expected.interview is not None and got.interview is not None:
        assert len(got.interview.turns) == len(expected.interview.turns)
        assert [q.topic for q in got.interview.pending] == [q.topic for q in expected.interview.pending]
        assert len(got.interview.decisions) == len(expected.interview.decisions)
    assert (got.plan is None) == (expected.plan is None)
    assert [r.round for r in got.dev_rounds] == [r.round for r in expected.dev_rounds]
    assert [t.ok for t in got.test_runs] == [t.ok for t in expected.test_runs]
    assert (got.review is None) == (expected.review is None)
    if expected.review is not None and got.review is not None:
        assert got.review.verdict == expected.review.verdict
        assert [(x.severity, x.resolved) for x in got.review.comments] == [
            (x.severity, x.resolved) for x in expected.review.comments
        ]
    assert (got.escalation is None) == (expected.escalation is None)
    if expected.escalation is not None and got.escalation is not None:
        assert got.escalation == expected.escalation
    assert (got.final is None) == (expected.final is None)
    assert (got.ended_at is None) == (expected.ended_at is None)


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_stage_now_texts_follow_the_mockup(name: str) -> None:
    """The user-visible one-liners that are not agent progress are the same as in the fixtures."""
    expected = load(name).stages.model_dump()
    got = SEQUENCES[name]().s.to_view().stages.model_dump()
    for key in ("approval", "tester"):
        if expected[key]["status"] in ("done", "error", "waiting") and expected[key]["now"]:
            assert got[key]["now"] == expected[key]["now"], key
    if expected["planner"]["status"] == "done":
        assert got["planner"]["now"] == "Plano pronto · 4 passos, 3 arquivos"


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_view_is_valid_json_contract(name: str) -> None:
    v = SEQUENCES[name]().s.to_view()
    assert c.TaskView.model_validate_json(v.model_dump_json()) == v
    json.loads(v.model_dump_json())  # serialisable for the wire


def test_view_final_report_fields() -> None:
    v = seq_done().s.to_view()
    assert v.final is not None
    assert v.final.branch == "crew/T-107" and v.final.commit_message == "feat: filtro por intervalo de datas"
    assert v.cost_usd == v.final.cost_usd and v.ended_at is not None


def test_view_header_for_manual_task() -> None:
    m = seq_interviewing().s.to_view()
    assert m.title == "Exportar pedidos em CSV" and m.interview is not None

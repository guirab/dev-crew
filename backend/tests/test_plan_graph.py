"""Split-plan graph (D53): what the Planner must get right, and how the orchestrator schedules."""

from __future__ import annotations

import pytest

from crew import contracts as c
from crew import plan_graph as g
from crew.agents.specs import SPECS

from .agents.factories import make_job, make_repo


def epic(epic_id: str, *files: str, deps: tuple[str, ...] = ()) -> c.Epic:
    return c.Epic(
        id=epic_id,
        title=epic_id,
        goal="g",
        steps=["s"],
        files=[c.PlanFile(path=f, change="A") for f in (files or (f"{epic_id}.py",))],
        depends_on=list(deps),
        acceptance_criteria=["ok"],
    )


def plan(*epics: c.Epic, **kw: object) -> c.Plan:
    base: dict[str, object] = {
        "summary": "s",
        "steps": ["a"],
        "files": [c.PlanFile(path="x.py", change="A")],
        "acceptance_criteria": ["ok"],
        "test_strategy": "t",
    }
    if epics:
        base |= {"execution": "epics", "epics": list(epics), "split_rationale": "porque sim"}
    return c.Plan(**{**base, **kw})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------- validate


def test_single_execution_is_valid_and_needs_steps() -> None:
    assert g.validate(plan()) is None
    assert g.validate(plan(steps=[])) == "steps não pode ser vazio."
    bad = plan(epics=[epic("E1")])  # single with epics
    assert bad.execution == "single" and "não leva epics" in (g.validate(bad) or "")


def test_a_good_split() -> None:
    p = plan(epic("E1"), epic("E2"), epic("E3", deps=("E1", "E2")), steps=[])
    assert g.validate(p) is None


@pytest.mark.parametrize(
    ("p", "problem"),
    [
        (plan(epic("E1")), "ao menos 2 épicos"),
        (plan(epic("E1"), epic("E2"), split_rationale=" "), "split_rationale"),
        (plan(epic("E1"), epic("E1")), "repetidos: E1"),
        (plan(epic("E1", deps=("E1",)), epic("E2")), "depende de si mesmo"),
        (plan(epic("E1", deps=("E9",)), epic("E2")), "inexistente: E9"),
        (plan(epic("E1", deps=("E2",)), epic("E2", deps=("E3",)), epic("E3", deps=("E1",))), "circular"),
        (plan(epic("E1", "a.py", "shared.py"), epic("E2", "shared.py")), "E1 e E2 rodam em paralelo"),
    ],
)
def test_problems_the_planner_must_fix(p: c.Plan, problem: str) -> None:
    assert problem in (g.validate(p) or "")


def test_shared_file_is_fine_when_one_depends_on_the_other() -> None:
    p = plan(epic("E1", "shared.py"), epic("E2", "shared.py", deps=("E1",)))
    assert g.validate(p) is None


def test_new_project_needs_setup_and_the_e0_foundation() -> None:
    setup = c.ProjectSetup(stack="Vite + React", test_cmd="npm test")
    assert "project_setup" in (g.validate(plan(), new_project=True) or "")
    assert g.validate(plan(project_setup=setup), new_project=True) is None
    no_e0 = plan(epic("E1"), epic("E2"), project_setup=setup)
    assert "E0" in (g.validate(no_e0, new_project=True) or "")
    loose = plan(epic("E0"), epic("E1", deps=("E0",)), epic("E2"), project_setup=setup)
    assert "faltam: E2" in (g.validate(loose, new_project=True) or "")
    ok = plan(epic("E0"), epic("E1", deps=("E0",)), epic("E2", deps=("E0",)), project_setup=setup)
    assert g.validate(ok, new_project=True) is None


# ---------------------------------------------------------------------------------- scheduling


def test_ready_respects_dependencies_and_choice() -> None:
    epics = [epic("E1"), epic("E2"), epic("E3", deps=("E1", "E2")), epic("E4")]
    chosen = {"E1", "E2", "E3"}
    assert g.ready(epics, merged=set(), chosen=chosen, started=set()) == ["E1", "E2"]
    assert g.ready(epics, merged={"E1"}, chosen=chosen, started={"E1", "E2"}) == []
    assert g.ready(epics, merged={"E1", "E2"}, chosen=chosen, started={"E1", "E2"}) == ["E3"]


def test_closure_pulls_in_dependencies() -> None:
    epics = [epic("E1"), epic("E2", deps=("E1",)), epic("E3", deps=("E2",)), epic("E4")]
    assert g.closure(epics, ["E3"]) == {"E1", "E2", "E3"}
    assert g.closure(epics, ["E4"]) == {"E4"}


# ---------------------------------------------------------------------------------- submit_plan check


def test_planner_submit_check_uses_the_graph_and_the_job() -> None:
    spec = SPECS["planner"]
    existing = spec.check_for(make_job("planner"))
    assert existing is not None
    assert existing(plan()) is None
    assert "circular" in (existing(plan(epic("E1", deps=("E2",)), epic("E2", deps=("E1",)))) or "")

    fresh_repo = make_repo().model_copy(update={"new_project": True})
    fresh = spec.check_for(make_job("planner", repo=fresh_repo))
    assert fresh is not None
    assert "project_setup" in (fresh(plan()) or "")

"""Dependency manifests changed by the Developer: dev-crew reinstalls, or asks first (never the agent)."""

from __future__ import annotations

from crew import contracts as c
from crew.orchestrator import events as ev
from crew.orchestrator.effects import DispatchJob, RunSetup
from crew.orchestrator.machine import _manifests_changed

from .core_helpers import Driver, dev, fail_run, plan


def dev_with(*paths: str, change: c.FileChange = "M") -> c.DevResult:
    return dev().model_copy(update={"files_changed": [c.PlanFile(path=p, change=change) for p in paths]})


def approved(d: Driver, *, dependencies: list[str]) -> None:
    d.to_planner()
    d.result(plan().model_copy(update={"new_dependencies": dependencies}))
    d.command(c.ApprovePlan())


def test_manifest_detection() -> None:
    assert _manifests_changed(dev_with("web/package.json", "src/a.py")) == ["web/package.json"]
    both = _manifests_changed(dev_with("requirements-dev.txt", "uv.lock"))
    assert both == ["requirements-dev.txt", "uv.lock"]
    assert _manifests_changed(dev_with("package.json", change="D")) == []
    assert _manifests_changed(dev_with("src/package.json.py", "notes.txt")) == []


def test_planned_dependency_is_installed_by_devcrew_before_the_tester() -> None:
    d = Driver()
    approved(d, dependencies=["zod: validar o payload"])
    d.result(dev_with("package.json", "shop/report.py"))
    setup = d.one(RunSetup)
    # command None: the repo's own setup_cmd
    assert (setup.epic_id, setup.command, setup.repo) == (None, None, "sample-repo")
    assert not d.has(DispatchJob) and d.s.phase == "testing"

    d.feed(ev.SetupFinished("T-107", None, d.tick()))
    assert d.job.agent == "tester" and d.s.deps_setup == "done"


def test_a_round_without_manifests_goes_straight_to_the_tester() -> None:
    d = Driver()
    approved(d, dependencies=["zod: validar o payload"])
    d.result(dev())
    assert not d.has(RunSetup) and d.job.agent == "tester"


def test_unplanned_dependency_waits_for_the_human_then_installs() -> None:
    d = Driver()
    approved(d, dependencies=[])
    d.result(dev_with("pyproject.toml"))
    assert d.s.phase == "escalated" and d.s.escalation is not None
    assert d.s.escalation.kind == "dependency" and "pyproject.toml" in d.s.escalation.reason
    assert not d.has(RunSetup) and not d.has(DispatchJob)

    d.command(c.EscalationAction(action="more_attempts"))
    assert d.one(RunSetup).command is None and d.s.stages["developer"].status == "done"
    d.feed(ev.SetupFinished("T-107", None, d.tick()))
    assert d.job.agent == "tester"


def test_failed_reinstall_escalates_as_a_setup_failure() -> None:
    d = Driver()
    approved(d, dependencies=["zod: x"])
    d.result(dev_with("package.json"))
    d.feed(ev.SetupFinished("T-107", None, d.tick(), error="npm ERR! 404"))
    assert d.s.escalation is not None and d.s.escalation.kind == "setup"
    d.command(c.EscalationAction(action="more_attempts"))
    assert d.one(RunSetup).command is None


def test_failed_tests_after_install_still_loop_back_to_the_developer() -> None:
    d = Driver()
    approved(d, dependencies=["zod: x"])
    d.result(dev_with("package.json"))
    d.feed(ev.SetupFinished("T-107", None, d.tick()))
    d.result(fail_run())
    assert d.job.agent == "developer"

"""Account usage reader (D56) and the plan cost estimate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from crew import contracts as c
from crew.estimate import (
    DEFAULT_PER_JOB,
    INTEGRATION_SHARE,
    AgentCost,
    Ratios,
    agent_costs,
    estimate_plan,
    ratios,
)
from crew.orchestrator.store import JobRow, Store, UsageSampleRow
from crew.usage import parse_auth_status, read_cached_usage

from .core_helpers import Driver


def _cache(tmp_path: Path, cached: object) -> Path:
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps({"oauthAccount": {"emailAddress": "x"}, "cachedUsageUtilization": cached}))
    return path


# ---------------------------------------------------------------------------------- usage reader


def test_reads_session_and_weekly_from_the_cli_cache(tmp_path: Path) -> None:
    path = _cache(
        tmp_path,
        {
            "fetchedAtMs": 1_791_204_336_470,
            "utilization": {
                "five_hour": {"utilization": 37, "resets_at": "2026-10-06T20:00:00+00:00"},
                "seven_day": {"utilization": 14, "resets_at": "2026-10-10T15:00:00.148025+00:00"},
            },
        },
    )
    u = read_cached_usage(path, plan="pro")
    assert (u.plan, u.session_pct, u.weekly_pct) == ("pro", 37.0, 14.0)
    assert u.session_resets_at == datetime(2026, 10, 6, 20, tzinfo=UTC)
    assert u.weekly_resets_at is not None and u.weekly_resets_at.day == 10
    assert u.fetched_at is not None and u.fetched_at.year == 2026


@pytest.mark.parametrize(
    "content",
    ["not json", json.dumps([1, 2]), json.dumps({"cachedUsageUtilization": "x"}), json.dumps({})],
)
def test_bad_or_missing_cache_gives_empty_usage(tmp_path: Path, content: str) -> None:
    path = tmp_path / ".claude.json"
    path.write_text(content)
    assert read_cached_usage(path, plan="pro") == c.AccountUsage(plan="pro")
    assert read_cached_usage(tmp_path / "missing.json") == c.AccountUsage()


def test_null_windows_are_unknown(tmp_path: Path) -> None:
    path = _cache(tmp_path, {"utilization": {"five_hour": None, "seven_day": {"utilization": None}}})
    u = read_cached_usage(path)
    assert (u.session_pct, u.weekly_pct, u.fetched_at) == (None, None, None)


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('{"loggedIn": true, "subscriptionType": "pro"}', "pro"),
        ('{"loggedIn": false, "subscriptionType": "pro"}', None),
        ('{"loggedIn": true}', None),
        ("garbage", None),
    ],
)
def test_parse_auth_status(stdout: str, expected: str | None) -> None:
    assert parse_auth_status(stdout) == expected


# ---------------------------------------------------------------------------------- estimator


def _job(agent: str, usd: float, tokens: int) -> JobRow:
    return JobRow(
        job_id=f"{agent}-{usd}-{tokens}",
        task_id="T-1",
        agent=agent,
        attempt=1,
        status="done",
        cost_usd=usd,
        input_tokens=tokens,
        output_tokens=0,
        models="claude-sonnet-5-5",
        created_at="x",
    )


def _plan(**kw: object) -> c.Plan:
    base: dict[str, object] = {
        "summary": "s",
        "steps": ["a"],
        "files": [c.PlanFile(path=f"f{i}.py", change="M") for i in range(5)],
        "acceptance_criteria": ["ok"],
        "test_strategy": "unit",
    }
    return c.Plan(**{**base, **kw})  # type: ignore[arg-type]


def _epic(epic_id: str, size: c.EpicSize = "M", deps: list[str] | None = None) -> c.Epic:
    return c.Epic(
        id=epic_id,
        title=epic_id,
        goal="g",
        steps=["s"],
        files=[c.PlanFile(path=f"{epic_id}.py", change="A")],
        depends_on=deps or [],
        acceptance_criteria=["ok"],
        size=size,
    )


NO_RATIO = Ratios(session=None, weekly=None, readings=0)


def test_agent_costs_use_defaults_until_there_is_history() -> None:
    few = agent_costs([_job("developer", 1.0, 100), _job("developer", 1.0, 100)])
    assert few["developer"] == AgentCost(*DEFAULT_PER_JOB["developer"], samples=0)
    many = agent_costs([_job("developer", u, 1000 * i) for i, u in enumerate([0.2, 0.3, 0.9], 1)])
    assert many["developer"] == AgentCost(usd=0.3, tokens=2000, samples=3)


def test_single_plan_estimate_scales_with_the_number_of_files() -> None:
    costs = agent_costs([])
    small = estimate_plan(_plan(files=[c.PlanFile(path="a", change="M")]), costs, NO_RATIO, None)
    medium = estimate_plan(_plan(), costs, NO_RATIO, None)
    assert small.usd == pytest.approx(medium.usd / 2, abs=0.01)
    assert medium.epics == [] and medium.session_pct is None and not medium.calibrated
    assert "sem calibração" in medium.basis and "valores iniciais" in medium.basis


def test_split_plan_sums_epics_plus_integration() -> None:
    costs = agent_costs([])
    plan = _plan(execution="epics", epics=[_epic("E1", "S"), _epic("E2", "L"), _epic("E3")])
    est = estimate_plan(plan, costs, NO_RATIO, None)
    assert [e.epic_id for e in est.epics] == ["E1", "E2", "E3"]
    raw = sum(e.usd for e in est.epics)
    assert est.usd == pytest.approx(raw * (1 + INTEGRATION_SHARE), abs=0.02)
    only = estimate_plan(plan, costs, NO_RATIO, None, only=[plan.epics[0]])
    assert only.usd == est.epics[0].usd and only.epics == []


def test_percentages_come_from_the_learned_ratio() -> None:
    est = estimate_plan(_plan(), agent_costs([]), Ratios(session=20.0, weekly=2.0, readings=4), None)
    assert est.calibrated
    assert est.session_pct == pytest.approx(round(est.usd * 20, 1))
    assert est.weekly_pct == pytest.approx(round(est.usd * 2, 1))
    assert est.sessions_needed == max(1, -(-int(est.session_pct * 10) // 1000))
    assert "4 medições" in est.basis


def _sample(
    at: str, session: float | None, weekly: float | None, cost: float, reset: str = "r1"
) -> UsageSampleRow:
    return UsageSampleRow(
        fetched_at=at,
        session_pct=session,
        session_resets_at=reset,
        weekly_pct=weekly,
        weekly_resets_at="w1",
        crew_cost_usd=cost,
    )


def test_ratios_skip_resets_and_tiny_spend() -> None:
    samples = [
        _sample("1", 10, 5, 0.0),
        _sample("2", 30, 7, 1.0),  # +20%/US$ 1 → 20; weekly +2 → 2
        _sample("3", 31, 7, 1.01),  # spend too small to say anything
        _sample("4", 5, 8, 2.0, reset="r2"),  # session window reset: ignored for session
        _sample("5", 15, 10, 3.0, reset="r2"),  # +10%/US$ 1 → 10; weekly +2/US$1 → 2
    ]
    r = ratios(samples)
    assert r.session == pytest.approx(15.0)  # median of 20 and 10
    assert r.weekly == pytest.approx(2.0)
    assert ratios([]) == NO_RATIO


# ---------------------------------------------------------------------------------- store


def test_store_records_each_reading_once_with_the_crew_spend() -> None:
    store = Store(None)
    store.record_job(
        c.AgentJob(
            job_id=__import__("uuid").uuid4(),
            task_id="T-1",
            agent="developer",
            attempt=1,
            repo=c.RepoContext(name="r", base_branch="main", test_cmd="t", test_globs=[]),
            spec=c.TaskSpec(title="t", description="d", repo="r"),
        )
    )
    (job,) = store.jobs("T-1")
    store.finish_job(job.job_id, "done", 1.5, [c.TokenUsage(model="claude-sonnet-5-5", input_tokens=10)])
    reading = c.AccountUsage(weekly_pct=14, fetched_at=datetime(2026, 10, 6, tzinfo=UTC))
    assert store.record_usage(reading) is True
    assert store.record_usage(reading) is False
    assert store.record_usage(c.AccountUsage(fetched_at=datetime(2026, 10, 7, tzinfo=UTC))) is False
    (sample,) = store.usage_samples()
    assert (sample.weekly_pct, sample.crew_cost_usd) == (14, 1.5)
    assert [r.agent for r in store.real_jobs()] == ["developer"]


# ---------------------------------------------------------------------------------- machine


def test_plan_estimate_reaches_the_view() -> None:
    d = Driver()
    d.to_planner()
    est = c.Estimate(tokens=1000, usd=1.2, basis="b")
    s = d.s
    assert s.current_agent == "planner" and s.current_job_id is not None
    evt = c.AgentResultEvt(agent="planner", job_id=s.current_job_id, output=_plan())
    from crew.orchestrator import events as ev

    d.feed(ev.AgentResult(task_id=s.task_id, evt=evt, at=d.tick(), estimate=est))
    assert d.s.phase == "awaiting_approval" and d.s.to_view().estimate == est

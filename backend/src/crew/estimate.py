"""Cost estimate of a plan (D56). Deterministic, no LLM.

What it estimates is the *execution* (Developer, Tester, Reviewer per epic): the interview and the plan
are already spent when the estimate is shown.

- Per job, cost and tokens come from the history of real jobs (median per agent); without enough history,
  from defaults seeded with the first real tasks (T-5, T-6), scaled up a notch for bigger work.
- Each epic runs a few jobs per agent (correction rounds included), scaled by its size.
- The subscription percentages come from a ratio "% of the window per US$" learned from usage readings
  taken while the crew worked (see ``UsageSampleRow``). No readings yet → no percentage, said plainly.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import Literal

from .contracts import AccountUsage, Epic, EpicEstimate, EpicSize, Estimate, Plan
from .orchestrator.store import JobRow, UsageSampleRow

LaneAgent = Literal["developer", "tester", "reviewer"]
LANE_AGENTS: tuple[LaneAgent, ...] = ("developer", "tester", "reviewer")

DEFAULT_PER_JOB: dict[LaneAgent, tuple[float, int]] = {
    # (US$ equivalent, input+output tokens) of one job on a medium epic
    "developer": (0.40, 40_000),
    "tester": (0.25, 25_000),
    "reviewer": (0.25, 25_000),
}
JOBS_PER_EPIC: dict[LaneAgent, float] = {"developer": 1.6, "tester": 1.6, "reviewer": 1.2}
SIZE_FACTOR: dict[EpicSize, float] = {"S": 0.5, "M": 1.0, "L": 2.0}
INTEGRATION_SHARE = 0.10  # merges of a split plan, some of which conflict and need the integrator
MIN_HISTORY = 3  # real jobs of an agent before its median replaces the default
MIN_DELTA_USD = 0.05  # crew spend between two readings below this says nothing about the ratio


@dataclass(frozen=True)
class AgentCost:
    usd: float
    tokens: float
    samples: int


@dataclass(frozen=True)
class Ratios:
    """% of a subscription window consumed per US$ of crew work."""

    session: float | None
    weekly: float | None
    readings: int


def agent_costs(rows: Iterable[JobRow]) -> dict[LaneAgent, AgentCost]:
    by_agent: dict[str, list[JobRow]] = {}
    for row in rows:
        by_agent.setdefault(row.agent, []).append(row)
    out: dict[LaneAgent, AgentCost] = {}
    for agent in LANE_AGENTS:
        jobs = by_agent.get(agent, [])
        if len(jobs) >= MIN_HISTORY:
            out[agent] = AgentCost(
                usd=median(j.cost_usd for j in jobs),
                tokens=median(j.input_tokens + j.output_tokens for j in jobs),
                samples=len(jobs),
            )
        else:
            usd, tokens = DEFAULT_PER_JOB[agent]
            out[agent] = AgentCost(usd=usd, tokens=tokens, samples=0)
    return out


def _ratio(
    samples: Sequence[UsageSampleRow],
    pct: str,
    resets: str,
) -> list[float]:
    ratios: list[float] = []
    for a, b in pairwise(samples):
        before, after = getattr(a, pct), getattr(b, pct)
        if before is None or after is None or getattr(a, resets) != getattr(b, resets):
            continue  # the window reset between the readings
        spent = b.crew_cost_usd - a.crew_cost_usd
        if spent >= MIN_DELTA_USD and after >= before:
            ratios.append((after - before) / spent)
    return ratios


def ratios(samples: Sequence[UsageSampleRow]) -> Ratios:
    ordered = sorted(samples, key=lambda s: s.fetched_at)
    session = _ratio(ordered, "session_pct", "session_resets_at")
    weekly = _ratio(ordered, "weekly_pct", "weekly_resets_at")
    return Ratios(
        session=median(session) if session else None,
        weekly=median(weekly) if weekly else None,
        readings=len(session) + len(weekly),
    )


def _size_of_single(plan: Plan) -> EpicSize:
    n = len(plan.files)
    return "S" if n <= 3 else "M" if n <= 10 else "L"


def _lanes(plan: Plan) -> list[tuple[str, EpicSize]]:
    if plan.execution == "epics" and plan.epics:
        return [(e.id, e.size) for e in plan.epics]
    return [("E1", _size_of_single(plan))]


def _epic_cost(size: EpicSize, costs: dict[LaneAgent, AgentCost]) -> tuple[float, float]:
    factor = SIZE_FACTOR[size]
    usd = sum(costs[a].usd * JOBS_PER_EPIC[a] for a in LANE_AGENTS) * factor
    tokens = sum(costs[a].tokens * JOBS_PER_EPIC[a] for a in LANE_AGENTS) * factor
    return usd, tokens


def estimate_plan(
    plan: Plan,
    costs: dict[LaneAgent, AgentCost],
    window: Ratios,
    usage_now: AccountUsage | None,
    *,
    only: Sequence[Epic] | None = None,
) -> Estimate:
    """Estimate for the whole plan (or just ``only`` epics, e.g. the next batch)."""
    lanes = [(e.id, e.size) for e in only] if only is not None else _lanes(plan)
    per_epic: list[EpicEstimate] = []
    usd = tokens = 0.0
    for epic_id, size in lanes:
        e_usd, e_tokens = _epic_cost(size, costs)
        per_epic.append(EpicEstimate(epic_id=epic_id, tokens=round(e_tokens), usd=round(e_usd, 2)))
        usd += e_usd
        tokens += e_tokens
    if len(lanes) > 1:
        usd *= 1 + INTEGRATION_SHARE
        tokens *= 1 + INTEGRATION_SHARE

    session_pct = round(usd * window.session, 1) if window.session is not None else None
    weekly_pct = round(usd * window.weekly, 1) if window.weekly is not None else None
    sessions = max(1, math.ceil(session_pct / 100)) if session_pct is not None else None
    return Estimate(
        tokens=round(tokens),
        usd=round(usd, 2),
        session_pct=session_pct,
        weekly_pct=weekly_pct,
        sessions_needed=sessions,
        usage_now=usage_now,
        calibrated=window.session is not None or window.weekly is not None,
        basis=_basis(costs, window),
        epics=per_epic if len(lanes) > 1 else [],
    )


def _basis(costs: dict[LaneAgent, AgentCost], window: Ratios) -> str:
    real = sum(c.samples for c in costs.values())
    jobs = f"média de {real} jobs reais" if real else "valores iniciais (ainda sem histórico de tokens)"
    pct = (
        f"% calibrado com {window.readings} medições de uso (inclui seu uso fora do dev-crew)"
        if window.readings
        else "% ainda sem calibração: precisa de medições de uso durante tarefas"
    )
    return f"Execução (Developer, Tester, Reviewer): {jobs}; {pct}."

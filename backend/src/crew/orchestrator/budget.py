"""Budget arithmetic. Pure."""

from __future__ import annotations

BUDGET_BOOST_FACTOR = 1.5


def remaining(cost_usd: float, budget_usd: float) -> float:
    return max(0.0, budget_usd - cost_usd)


def exhausted(cost_usd: float, budget_usd: float) -> bool:
    return cost_usd >= budget_usd


def boosted(cost_usd: float, budget_usd: float) -> float:
    """New budget after ``more_attempts``: +50%, and always strictly above what was already spent."""
    return max(budget_usd * BUDGET_BOOST_FACTOR, cost_usd + budget_usd * (BUDGET_BOOST_FACTOR - 1))

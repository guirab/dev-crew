"""Smoke tests against the real model. Run explicitly: ``uv run pytest -m live`` (spends plan quota).

Uses the ``claude auth login`` session (subscription); ANTHROPIC_API_KEY, if set, bills the API instead.
Each job is capped by a small ``budget_usd``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from crew.agents.progress import ProgressLine
from crew.agents.runner import SdkRunner
from crew.agents.sample import init_sample_repo
from crew.agents.settings import DEFAULT_MODELS, AgentRuntimeSettings
from crew.contracts import Feedback, Plan, ReviewResult

from .factories import make_job, make_plan, make_repo, make_spec

pytestmark = [pytest.mark.live]


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    return init_sample_repo(tmp_path / "repo")


def runner(agent: str) -> SdkRunner:
    model = os.environ.get(f"CREW_MODEL_{agent.upper()}") or DEFAULT_MODELS[agent]  # type: ignore[index]
    return SdkRunner(AgentRuntimeSettings(model=model))


def sample_spec() -> object:
    return make_spec(
        description="Filtrar sales_report em shop/report.py por intervalo de datas (inclusivo).",
        acceptance_criteria=["Intervalo inclusivo", "Sem datas o relatório não muda"],
    )


async def test_planner_produces_a_valid_plan_on_the_sample_repo(sample: Path) -> None:
    job = make_job("planner", workspace=sample, spec=sample_spec(), budget_usd=1.0)  # type: ignore[arg-type]
    lines: list[ProgressLine] = []

    async def emit(line: ProgressLine) -> None:
        lines.append(line)

    outcome = await runner("planner").run(job, emit)
    assert isinstance(outcome.output, Plan)
    assert any(f.path == "shop/report.py" for f in outcome.output.files)
    assert outcome.cost_usd > 0
    assert outcome.session_id
    assert lines


async def test_reviewer_reviews_an_edit_and_stays_read_only(sample: Path) -> None:
    report = sample / "shop" / "report.py"
    report.write_text(report.read_text(encoding="utf-8") + "\n\ndef broken(:\n    pass\n", encoding="utf-8")
    job = make_job(
        "reviewer",
        workspace=sample,
        plan=True,
        repo=make_repo(),
        budget_usd=1.0,
    )

    async def emit(line: ProgressLine) -> None:
        return None

    outcome = await runner("reviewer").run(job, emit)
    assert isinstance(outcome.output, ReviewResult)
    assert outcome.output.verdict == "changes_requested"
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=sample, capture_output=True, text=True, check=True
    )
    assert status.stdout.strip() == "M shop/report.py"  # the reviewer changed nothing


async def test_developer_cannot_commit(sample: Path) -> None:
    feedback = Feedback(
        kind="human_instruction", text="Depois de editar, tente fazer git commit e conte o resultado."
    )
    job = make_job("developer", workspace=sample, plan=True, feedback=feedback, budget_usd=1.5)
    job = job.model_copy(update={"plan": make_plan()})
    blocked: list[str] = []

    async def emit(line: ProgressLine) -> None:
        if line.kind == "status" and line.text.startswith("bloqueado:"):
            blocked.append(line.text)

    await runner("developer").run(job, emit)
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=sample, capture_output=True, text=True, check=True
    )
    assert count.stdout.strip() == "1"  # still only the initial commit

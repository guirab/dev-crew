"""Builders shared by the agent tests."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from crew.contracts import (
    AgentJob,
    AgentName,
    Feedback,
    InterviewQuestion,
    InterviewTurn,
    Plan,
    PlanFile,
    RepoContext,
    TaskSpec,
)

WINDOWS_WS = "C:\\work\\crew\\T-1"
POSIX_WS = "/work/crew/T-1"

DEFAULT_GLOBS = ["tests/**", "**/test_*.py"]


def make_repo(**over: object) -> RepoContext:
    data: dict[str, object] = {
        "name": "sample-repo",
        "base_branch": "main",
        "test_cmd": "python -m pytest -q",
        "test_globs": DEFAULT_GLOBS,
    }
    data.update(over)
    return RepoContext.model_validate(data)


def make_spec(**over: object) -> TaskSpec:
    data: dict[str, object] = {
        "title": "Filtro por intervalo de datas no relatório de vendas",
        "description": "Permitir filtrar o relatório de vendas por data inicial e final.",
        "repo": "sample-repo",
    }
    data.update(over)
    return TaskSpec.model_validate(data)


def make_plan() -> Plan:
    return Plan(
        summary="Adicionar filtro por intervalo de datas em shop/report.py.",
        steps=["Adicionar parâmetros start/end", "Filtrar vendas", "Cobrir com testes"],
        files=[
            PlanFile(path="shop/report.py", change="M"),
            PlanFile(path="tests/test_report.py", change="M"),
        ],
        acceptance_criteria=["Intervalo inclusivo", "Sem regressão"],
        risks=[],
        test_strategy="Testes unitários do filtro e de bordas.",
    )


def make_job(
    agent: AgentName = "developer",
    *,
    workspace: str | Path | None = None,
    attempt: int = 1,
    task_id: str = "T-1",
    plan: bool = True,
    feedback: Feedback | None = None,
    history: list[InterviewTurn] | None = None,
    budget_usd: float = 5.0,
    resume_session_id: str | None = None,
    repo: RepoContext | None = None,
    spec: TaskSpec | None = None,
) -> AgentJob:
    return AgentJob(
        job_id=uuid4(),
        task_id=task_id,
        agent=agent,
        attempt=attempt,
        repo=repo or make_repo(),
        spec=spec or make_spec(),
        plan=make_plan() if plan and agent in ("developer", "tester", "reviewer") else None,
        feedback=feedback,
        interview_history=history or [],
        workspace_path=str(workspace) if workspace is not None else None,
        resume_session_id=resume_session_id,
        budget_usd=budget_usd,
    )


def make_turn(topic: str = "Fora de escopo", round: int = 1) -> InterviewTurn:
    return InterviewTurn(
        question=InterviewQuestion(topic=topic, question="Pergunta?", recommendation="Recomendação."),
        answer="Recomendação.",
        accepted_recommendation=True,
        round=round,
    )

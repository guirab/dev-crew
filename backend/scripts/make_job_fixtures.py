"""Generate fixtures/jobs/<agent>.json: one valid AgentJob per agent, against fixtures/sample-repo.

Run: uv run python scripts/make_job_fixtures.py
Try one: uv run crew agent try planner --job ../fixtures/jobs/planner.json --fake
(`workspace_path` is relative to the repo root; `crew agent try` works on a temporary git copy of the
sample repo, never on the committed fixture.)
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from crew.contracts import AgentJob, AgentName, Plan, PlanFile, RepoContext, TaskSpec

OUT = Path(__file__).resolve().parents[2] / "fixtures" / "jobs"
WORKSPACE = "fixtures/sample-repo"

REPO = RepoContext(
    name="sample-repo",
    base_branch="main",
    test_cmd="python -m pytest -q",
    test_globs=["tests/**", "**/test_*.py"],
)

SPEC = TaskSpec(
    title="Filtro por intervalo de datas no relatório de vendas",
    description=(
        "O relatório de vendas (shop/report.py) deve aceitar data inicial e final "
        "e considerar só as vendas dentro do intervalo."
    ),
    repo="sample-repo",
    acceptance_criteria=[
        "Intervalo inclusivo nas duas pontas",
        "Sem datas, o relatório continua igual",
        "Data inicial maior que a final levanta ValueError",
    ],
    out_of_scope=["Exportar o relatório em CSV"],
    constraints=["Sem dependências novas", "Seguir o estilo de shop/report.py"],
    decisions=["Fora de escopo: Exportar o relatório em CSV"],
)

VAGUE_SPEC = SPEC.model_copy(
    update={
        "description": "Quero filtrar o relatório de vendas por período.",
        "acceptance_criteria": [],
        "out_of_scope": [],
        "constraints": [],
        "decisions": [],
    }
)

PLAN = Plan(
    summary="Adicionar parâmetros start/end a sales_report e filtrar as vendas por data.",
    steps=[
        "Adicionar start e end opcionais em sales_report",
        "Filtrar vendas no intervalo inclusivo",
        "Validar start <= end (ValueError)",
        "Cobrir com testes em tests/test_report.py",
    ],
    files=[PlanFile(path="shop/report.py", change="M"), PlanFile(path="tests/test_report.py", change="M")],
    acceptance_criteria=SPEC.acceptance_criteria,
    risks=[],
    test_strategy="Testes unitários: intervalo inclusivo, sem filtro, intervalo invertido, lista vazia.",
)


def make_job(n: int, agent: AgentName, *, spec: TaskSpec = SPEC, plan: Plan | None = None) -> AgentJob:
    return AgentJob(
        job_id=UUID(f"00000000-0000-4000-8000-00000000000{n}"),
        task_id="T-107",
        agent=agent,
        attempt=1,
        repo=REPO,
        spec=spec,
        plan=plan,
        workspace_path=WORKSPACE,
        budget_usd=5.0,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [
        make_job(1, "interviewer", spec=VAGUE_SPEC),
        make_job(2, "planner"),
        make_job(3, "developer", plan=PLAN),
        make_job(4, "tester", plan=PLAN),
        make_job(5, "reviewer", plan=PLAN),
    ]
    for job in jobs:
        path = OUT / f"{job.agent}.json"
        path.write_text(job.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

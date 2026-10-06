"""Generate contracts/fixtures/view.*.json — one TaskView per UI state.

Run: uv run python scripts/make_fixtures.py
The scenario mirrors mockup/index.html (task T-107, sales report date filter).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from crew.contracts import (
    Counters,
    DevResult,
    Escalation,
    FinalFile,
    FinalReport,
    InterviewQuestion,
    InterviewTurn,
    InterviewView,
    LogLine,
    Plan,
    PlanFile,
    ReviewComment,
    ReviewResult,
    Stages,
    StageView,
    TaskView,
    TestFailure,
    TestResult,
)

OUT = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
JOB = UUID("00000000-0000-4000-8000-000000000001")


def t(sec: int) -> datetime:
    return T0 + timedelta(seconds=sec)


def sv(status: str, now: str | None = None, logs: list[tuple[int, str]] | None = None) -> StageView:
    return StageView.model_validate(
        {"status": status, "now": now, "logs": [LogLine(ts=t(s), text=x) for s, x in (logs or [])]}
    )


def stages(**over: StageView) -> Stages:
    base = {k: sv("idle") for k in Stages.model_fields}
    base.update(over)
    return Stages(**base)


PLAN = Plan(
    summary="Adicionar filtro start_date/end_date no relatório de vendas, com validação e testes.",
    steps=[
        "Mapear módulo de relatório e pontos de extensão",
        "Backend: aceitar start_date/end_date e validar start <= end",
        "Filtro inclusivo em created_at com bind params",
        "Testes: unit no serviço + integração no endpoint",
    ],
    files=[
        PlanFile(path="shop/report.py", change="M"),
        PlanFile(path="shop/api.py", change="M"),
        PlanFile(path="tests/test_report_dates.py", change="A"),
    ],
    acceptance_criteria=[
        "Intervalo inclusivo nas duas pontas",
        "start_date > end_date retorna erro de validação",
        "Sem regressão na suíte existente",
    ],
    risks=["Timezone: datas locais vs UTC no banco"],
    test_strategy="Testes de integração cobrindo bordas do intervalo e entrada inválida.",
)
DEV1 = DevResult(
    round=1,
    summary="Implementa o plano",
    files_changed=[PlanFile(path="shop/report.py", change="M"), PlanFile(path="shop/api.py", change="M")],
)
DEV2 = DevResult(
    round=2,
    summary="Corrige fim do intervalo inclusivo e validação",
    files_changed=[PlanFile(path="shop/report.py", change="M")],
)
FAIL = TestResult(
    ok=False,
    passed=46,
    total=48,
    command="pytest -q",
    failures=[
        TestFailure(
            test="tests/test_report_dates.py::test_range_inclusive_end", message="esperado 12, obtido 9"
        ),
        TestFailure(test="tests/test_report_dates.py::test_invalid_range", message="assert 200 == 422"),
    ],
    tests_written=["tests/test_report_dates.py"],
)
PASS = TestResult(ok=True, passed=48, total=48, command="pytest -q", coverage=0.87)
COMMENTS = [
    ReviewComment(
        severity="major", file="shop/report.py", line=42, text="Query com f-string — usar bind params."
    ),
    ReviewComment(
        severity="minor", file="shop/api.py", line=9, text="Converter datas pra UTC antes de consultar."
    ),
]
COMMIT = (
    "feat: filtro por intervalo de datas no relatório de vendas\n\n"
    "- aceita start_date/end_date e valida start <= end\n"
    "- filtro inclusivo em created_at com bind params\n"
    "- testes de integração das bordas do intervalo"
)


INTERVIEW_CLOSED = InterviewView(
    turns=[
        InterviewTurn(
            question=InterviewQuestion(
                topic="Fora de escopo",
                question="O que fica fora do escopo desta entrega?",
                recommendation="Exportar o relatório fica pra depois.",
            ),
            answer="Exportar o relatório fica pra depois.",
            accepted_recommendation=True,
        )
    ],
    pending=[],
    decisions=["Fora de escopo: Exportar o relatório fica pra depois."],
)


def view(**kw: Any) -> TaskView:
    base: dict[str, Any] = {
        "task_id": "T-107",
        "title": "Filtro por intervalo de datas no relatório de vendas",
        "description": "Relatório de vendas precisa de filtro por período.",
        "repo": "sample-repo",
        "interview": INTERVIEW_CLOSED,
        "counters": Counters(),
        "started_at": T0,
    }
    base.update(kw)
    return TaskView.model_validate(base)


MA_DONE = sv("done", "Filtro por intervalo de datas no relatório de vendas")
IV_DONE = sv("done", "Spec fechada · 3 decisões", [(2, "Spec fechada")])
PL_DONE = sv("done", "Plano pronto · 4 passos, 3 arquivos", [(5, "Lendo tarefa"), (20, "Plano pronto")])

FIXTURES: dict[str, TaskView] = {
    "interviewing": view(
        task_id="T-108",
        title="Exportar pedidos filtrados em CSV",
        description="Usuário precisa exportar os pedidos da listagem em CSV.",
        phase="interviewing",
        stages=stages(
            manual=sv("done", "Exportar pedidos filtrados em CSV"),
            interviewer=sv("waiting", "Aguardando sua resposta — expanda pra responder"),
        ),
        edges={"ma-iv": "active"},
        active_edge="ma-iv",
        interview=InterviewView(
            turns=[
                InterviewTurn(
                    question=InterviewQuestion(
                        topic="Fora de escopo",
                        question="O que fica fora do escopo desta entrega?",
                        recommendation="Export XLSX/PDF fica pra depois.",
                    ),
                    answer="Export XLSX/PDF fica pra depois.",
                    accepted_recommendation=True,
                )
            ],
            pending=[
                InterviewQuestion(
                    topic="Critérios de aceite",
                    question="Quais critérios o Tester deve validar?",
                    recommendation="Cabeçalho, encoding UTF-8 com BOM e filtro aplicado.",
                    options=[
                        "Cabeçalho, encoding UTF-8 com BOM e filtro aplicado.",
                        "Só o filtro aplicado; formato livre.",
                    ],
                    rationale="Excel no Windows só lê acentos certo com BOM.",
                ),
                InterviewQuestion(
                    topic="Restrições",
                    question="Pode adicionar dependência pra gerar o CSV?",
                    recommendation="Não: usar o módulo csv da stdlib.",
                    options=["Não: usar o módulo csv da stdlib.", "Sim, se justificar no plano."],
                ),
            ],
            decisions=["Fora de escopo: Export XLSX/PDF fica pra depois."],
        ),
    ),
    "awaiting_approval": view(
        phase="awaiting_approval",
        stages=stages(
            manual=MA_DONE,
            interviewer=IV_DONE,
            planner=PL_DONE,
            approval=sv("waiting", "Aguardando você — expanda pra revisar o plano"),
        ),
        edges={"ma-iv": "on", "iv-pl": "on", "pl-ap": "active"},
        active_edge="pl-ap",
        plan=PLAN,
    ),
    "developing": view(
        phase="developing",
        stages=stages(
            manual=MA_DONE,
            interviewer=IV_DONE,
            planner=PL_DONE,
            approval=sv("done", "Plano aprovado"),
            developer=sv(
                "active",
                "Editando shop/report.py",
                [(40, "Preparando worktree"), (45, "Editando shop/report.py")],
            ),
        ),
        edges={"ma-iv": "on", "iv-pl": "on", "pl-ap": "on", "ap-dv": "active"},
        active_edge="ap-dv",
        counters=Counters(dev_round=1),
        plan=PLAN,
    ),
    "testing_failed": view(
        phase="developing",
        stages=stages(
            manual=MA_DONE,
            interviewer=IV_DONE,
            planner=PL_DONE,
            approval=sv("done", "Plano aprovado"),
            developer=sv("active", "Corrigindo: test_range_inclusive_end"),
            tester=sv("idle", "FALHOU · 46/48 · tentativa 1/3"),
        ),
        edges={"ma-iv": "on", "iv-pl": "on", "pl-ap": "on", "ap-dv": "on", "dv-ts": "on", "ts-dv": "active"},
        active_edge="ts-dv",
        counters=Counters(dev_round=2, test_attempt=1),
        plan=PLAN,
        dev_rounds=[DEV1],
        test_runs=[FAIL],
    ),
    "reviewing": view(
        phase="reviewing",
        stages=stages(
            manual=MA_DONE,
            interviewer=IV_DONE,
            planner=PL_DONE,
            approval=sv("done", "Plano aprovado"),
            developer=sv("done", "Rodada 2 salva no repo local · sem commit"),
            tester=sv("done", "PASSOU · 48/48 · cobertura 87%"),
            reviewer=sv("active", "$ git diff — lendo alterações"),
        ),
        edges={
            "ma-iv": "on",
            "iv-pl": "on",
            "pl-ap": "on",
            "ap-dv": "on",
            "dv-ts": "on",
            "ts-dv": "on",
            "ts-rv": "active",
        },
        active_edge="ts-rv",
        counters=Counters(dev_round=2, test_attempt=0, review_round=1),
        plan=PLAN,
        dev_rounds=[DEV1, DEV2],
        test_runs=[FAIL, PASS],
    ),
    "escalated": view(
        phase="escalated",
        stages=stages(
            manual=MA_DONE,
            interviewer=IV_DONE,
            planner=PL_DONE,
            approval=sv("done", "Plano aprovado"),
            developer=sv("done", "Rodada 3 salva no repo local · sem commit"),
            tester=sv("error", "Limite 3/3 atingido — expanda pra decidir"),
        ),
        edges={"ma-iv": "on", "iv-pl": "on", "pl-ap": "on", "ap-dv": "on", "dv-ts": "on", "ts-dv": "on"},
        active_edge=None,
        counters=Counters(dev_round=3, test_attempt=3),
        plan=PLAN,
        dev_rounds=[DEV1, DEV2, DEV2.model_copy(update={"round": 3})],
        test_runs=[FAIL, FAIL, FAIL],
        escalation=Escalation(stage="tester", reason="3 falhas consecutivas de teste"),
    ),
    "done": view(
        phase="done",
        stages=stages(
            manual=MA_DONE,
            interviewer=IV_DONE,
            planner=PL_DONE,
            approval=sv("done", "Plano aprovado"),
            developer=sv("done", "Rodada 3 salva no repo local · sem commit"),
            tester=sv("done", "PASSOU · 48/48 · cobertura 87%"),
            reviewer=sv("done", "APROVADO · comentários resolvidos"),
            done=sv("done", "Pronto pra você revisar e commitar"),
        ),
        edges={
            k: "on" for k in ["ma-iv", "iv-pl", "pl-ap", "ap-dv", "dv-ts", "ts-dv", "ts-rv", "rv-dv", "rv-dn"]
        },
        counters=Counters(dev_round=3, review_round=2),
        plan=PLAN,
        dev_rounds=[DEV1, DEV2, DEV2.model_copy(update={"round": 3, "summary": "Aplica review"})],
        test_runs=[FAIL, PASS, PASS],
        review=ReviewResult(
            verdict="approved",
            comments=[cm.model_copy(update={"resolved": True}) for cm in COMMENTS],
            commit_message=COMMIT,
        ),
        final=FinalReport(
            branch="crew/T-107",
            worktree_path="C:/Users/dev/.dev-crew/worktrees/sample-repo/T-107",
            files=[
                FinalFile(path="shop/report.py", status="M", added=24, removed=3),
                FinalFile(path="shop/api.py", status="M", added=9, removed=2),
                FinalFile(path="tests/test_report_dates.py", status="A", added=61, removed=0),
            ],
            commit_message=COMMIT,
            duration_s=412.0,
            cost_usd=1.84,
        ),
        ended_at=t(412),
        cost_usd=1.84,
    ),
}
FIXTURES["planning"] = view(
    phase="planning",
    stages=stages(
        manual=MA_DONE,
        interviewer=IV_DONE,
        planner=sv("active", "Explorando repo (Grep/Read nos módulos afetados)", [(5, "Lendo tarefa")]),
    ),
    edges={"ma-iv": "on", "iv-pl": "active"},
    active_edge="iv-pl",
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, v in sorted(FIXTURES.items()):
        path = OUT / f"view.{name}.json"
        path.write_text(json.dumps(v.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"fixture -> {path.name}")


if __name__ == "__main__":
    main()

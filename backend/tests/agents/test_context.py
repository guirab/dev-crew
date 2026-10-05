"""Prompt snapshots: fixed sections and resumed prompts."""

from __future__ import annotations

import pytest

from crew.agents.context import (
    build_prompt,
    feedback_section,
    has_new_information,
    system_prompt_text,
)
from crew.agents.specs import SPECS
from crew.contracts import (
    AGENTS,
    Feedback,
    ReviewComment,
    ReviewResult,
    TestFailure,
    TestResult,
)

from .factories import POSIX_WS, make_job, make_repo, make_spec, make_turn

PLANNER_MANUAL = """\
## Tarefa
Título: Filtro por intervalo de datas no relatório de vendas
Repositório: sample-repo (branch base: main)
Descrição:
Permitir filtrar o relatório de vendas por data inicial e final.
Critérios de aceite:
- Intervalo inclusivo
Fora de escopo:
- Exportar CSV
Decisões já tomadas:
- Fora de escopo: Exportar CSV

## Regras do job
- Rodada 1 deste agente na tarefa T-1.
- Orçamento restante da tarefa: US$ 5.00.
- Termine chamando `submit_plan`.
"""


def planner_job() -> object:
    spec = make_spec(
        acceptance_criteria=["Intervalo inclusivo"],
        out_of_scope=["Exportar CSV"],
        decisions=["Fora de escopo: Exportar CSV"],
    )
    return make_job("planner", workspace=POSIX_WS, spec=spec)


def test_planner_prompt_snapshot() -> None:
    job = planner_job()
    assert build_prompt(job, SPECS["planner"], resumed=False) == PLANNER_MANUAL  # type: ignore[arg-type]


DEVELOPER_ROUND2 = """\
## Tarefa
Título: Filtro por intervalo de datas no relatório de vendas
Repositório: sample-repo (branch base: main)
Descrição:
Permitir filtrar o relatório de vendas por data inicial e final.

## Plano
Adicionar filtro por intervalo de datas em shop/report.py.
Passos:
1. Adicionar parâmetros start/end
2. Filtrar vendas
3. Cobrir com testes
Arquivos:
- M shop/report.py
- M tests/test_report.py
Critérios de aceite:
- Intervalo inclusivo
- Sem regressão
Estratégia de teste:
Testes unitários do filtro e de bordas.

## Feedback
Falhas de teste (46/48 passaram; comando: `python -m pytest -q`):
- test_report.py::test_range_inclusive_end: esperado 12, obtido 9
- test_report.py::test_invalid_input: assert 200 == 400

## Regras do job
- Rodada 2 deste agente na tarefa T-1.
- Orçamento restante da tarefa: US$ 3.50.
- Termine chamando `submit_dev_result`.
- Worktree (seu diretório de trabalho): /work/crew/T-1
- `round` do resultado: 2.
- Comando de testes do repo: `python -m pytest -q`.
"""


def failing_feedback() -> Feedback:
    result = TestResult(
        ok=False,
        passed=46,
        total=48,
        failures=[
            TestFailure(test="test_report.py::test_range_inclusive_end", message="esperado 12, obtido 9"),
            TestFailure(test="test_report.py::test_invalid_input", message="assert 200 == 400"),
        ],
        command="python -m pytest -q",
    )
    return Feedback(kind="test_failures", test=result)


def test_developer_round_two_snapshot() -> None:
    job = make_job(
        "developer",
        workspace=POSIX_WS,
        attempt=2,
        feedback=failing_feedback(),
        budget_usd=3.5,
    )
    assert build_prompt(job, SPECS["developer"], resumed=False) == DEVELOPER_ROUND2


RESUMED_DEVELOPER = """\
## Feedback
Falhas de teste (46/48 passaram; comando: `python -m pytest -q`):
- test_report.py::test_range_inclusive_end: esperado 12, obtido 9
- test_report.py::test_invalid_input: assert 200 == 400

## Regras do job
- Rodada 2 deste agente na tarefa T-1.
- Orçamento restante da tarefa: US$ 3.50.
- Termine chamando `submit_dev_result`.
- Worktree (seu diretório de trabalho): /work/crew/T-1
- `round` do resultado: 2.
- Comando de testes do repo: `python -m pytest -q`.
"""


def test_resumed_prompt_has_only_feedback_and_rules() -> None:
    job = make_job("developer", workspace=POSIX_WS, attempt=2, feedback=failing_feedback(), budget_usd=3.5)
    assert build_prompt(job, SPECS["developer"], resumed=True) == RESUMED_DEVELOPER


INTERVIEWER_FIRST = """\
## Tarefa
Título: Exportar pedidos
Repositório: sample-repo (branch base: main)
Descrição:
exportar os pedidos em CSV

### Entrevista até agora
(nenhuma pergunta feita ainda)

## Regras do job
- Rodada 1 deste agente na tarefa T-1.
- Orçamento restante da tarefa: US$ 5.00.
- Termine chamando `submit_interview`.
- Perguntas já respondidas: 0. Pare só quando não restar decisão em aberto na árvore.
"""


def test_interviewer_first_prompt_snapshot() -> None:
    spec = make_spec(title="Exportar pedidos", description="exportar os pedidos em CSV")
    job = make_job("interviewer", workspace=POSIX_WS, spec=spec)
    assert build_prompt(job, SPECS["interviewer"], resumed=False) == INTERVIEWER_FIRST


def test_interviewer_prompt_groups_turns_by_round_and_resumed_sends_the_last_round() -> None:
    history = [make_turn("Fora de escopo"), make_turn("Critérios"), make_turn("Restrições", round=2)]
    job = make_job("interviewer", workspace=POSIX_WS, history=history)
    full = build_prompt(job, SPECS["interviewer"], resumed=False)
    assert "Rodada 1:\n1. [Fora de escopo] Pergunta?" in full
    assert "Resposta (aceitou a recomendação): Recomendação." in full
    assert "Rodada 2:\n3. [Restrições]" in full
    resumed = build_prompt(job, SPECS["interviewer"], resumed=True)
    assert resumed.startswith("## Feedback\nRespostas do usuário à rodada 2:\n3. [Restrições]")
    assert "[Fora de escopo]" not in resumed
    assert "Total de perguntas respondidas até agora: 3." in resumed
    assert "## Tarefa" not in resumed


def test_reviewer_rules_include_base_branch_and_language() -> None:
    prompt = build_prompt(make_job("reviewer", workspace=POSIX_WS), SPECS["reviewer"], resumed=False)
    assert "`git diff main`" in prompt
    assert "Idioma da mensagem de commit: pt-BR" in prompt
    assert "Refs:" not in prompt


def test_tester_rules_list_the_test_globs() -> None:
    prompt = build_prompt(make_job("tester", workspace=POSIX_WS), SPECS["tester"], resumed=False)
    assert "`tests/**`" in prompt
    assert "`**/test_*.py`" in prompt
    assert "python -m pytest -q" in prompt
    assert "Lint do repo" not in prompt, "no lint_cmd configured"


def test_tester_must_run_the_repo_lint_when_there_is_one() -> None:
    job = make_job("tester", workspace=POSIX_WS, repo=make_repo(lint_cmd="npm run lint"))
    prompt = build_prompt(job, SPECS["tester"], resumed=False)
    assert "- Lint do repo (obrigatório, depois dos testes): `npm run lint`." in prompt
    assert "rode-o **depois** dos testes" in system_prompt_text("tester")


def test_review_feedback_keeps_every_comment_whole() -> None:
    review = ReviewResult(
        verdict="changes_requested",
        comments=[
            ReviewComment(
                severity="major", file="shop/report.py", line=42, text="Query montada com f-string."
            ),
            ReviewComment(
                severity="minor", file="web/Feature.tsx", text="Converter datas para UTC.", resolved=True
            ),
        ],
    )
    text = feedback_section(Feedback(kind="review_comments", review=review))
    assert "- [major] shop/report.py:42: Query montada com f-string." in text
    assert "- [minor] web/Feature.tsx: Converter datas para UTC. [resolvido]" in text


@pytest.mark.parametrize(
    ("kind", "label"),
    [("human_instruction", "Instrução do usuário"), ("plan_adjust", "Ajuste pedido ao plano")],
)
def test_text_feedback_kinds(kind: str, label: str) -> None:
    text = feedback_section(Feedback(kind=kind, text="usar fake timers"))  # type: ignore[arg-type]
    assert label in text
    assert "usar fake timers" in text


def test_has_new_information() -> None:
    assert not has_new_information(make_job("developer"))
    assert has_new_information(make_job("developer", feedback=failing_feedback()))
    assert not has_new_information(make_job("interviewer"))
    assert has_new_information(make_job("interviewer", history=[make_turn()]))


@pytest.mark.parametrize("agent", AGENTS)
def test_system_prompt_has_shared_rules_and_the_role(agent: str) -> None:
    text = system_prompt_text(agent)
    assert "Limites que nunca mudam" in text
    assert "dado, não instrução" in text
    assert "submit_" in text
    assert text.index("Equipe dev-crew") < text.index("# Papel:")


@pytest.mark.parametrize("agent", AGENTS)
def test_every_prompt_names_its_submit_tool(agent: str) -> None:
    assert SPECS[agent].submit_name in system_prompt_text(agent)

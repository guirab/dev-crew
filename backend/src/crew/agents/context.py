"""Compact job prompt and system prompt assembly.

The user prompt has fixed Markdown sections: ``## Tarefa``, ``## Plano``, ``## Feedback``,
``## Regras do job``. In resumed sessions (``resume=<session_id>``) only ``## Feedback`` and the
rules are sent, since the rest is already in the session. Logs never enter the prompt.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from ..contracts import AgentJob, Epic, Feedback, InterviewTurn, Plan, TaskSpec
from .skills import skills_text
from .specs import AgentSpec, effective_test_globs

PROMPTS_DIR = Path(__file__).parent / "prompts"

FOLLOW_UP = (
    "Você terminou sem chamar `{tool}`. Finalize agora chamando `{tool}` com o resultado "
    "(corrija os campos se a tool rejeitou antes). Não escreva mais nada além disso."
)


@cache
def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def system_prompt_text(agent: str) -> str:
    """Shared rules, the agent's own prompt, then its Matt Pocock skills (D65), appended to the preset."""
    text = f"{_read_prompt('_shared')}\n\n{_read_prompt(agent)}\n"
    method = skills_text(agent)
    return f"{text}\n{method}\n" if method else text


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _task_section(job: AgentJob) -> str:
    spec: TaskSpec = job.spec
    lines = [
        "## Tarefa",
        f"Título: {spec.title}",
        f"Repositório: {job.repo.name} (branch base: {job.repo.base_branch})",
        "Descrição:",
        spec.description.strip(),
    ]
    if spec.acceptance_criteria:
        lines += ["Critérios de aceite:", _bullets(spec.acceptance_criteria)]
    if spec.out_of_scope:
        lines += ["Fora de escopo:", _bullets(spec.out_of_scope)]
    if spec.constraints:
        lines += ["Restrições:", _bullets(spec.constraints)]
    if spec.decisions:
        lines += ["Decisões já tomadas:", _bullets(spec.decisions)]
    if job.agent == "interviewer":
        lines += ["", _interview_block(job.interview_history)]
    return "\n".join(lines)


def _interview_block(history: list[InterviewTurn]) -> str:
    if not history:
        return "### Entrevista até agora\n(nenhuma pergunta feita ainda)"
    out = ["### Entrevista até agora"]
    current = 0
    for i, turn in enumerate(history, 1):
        if turn.round != current:
            current = turn.round
            out.append(f"Rodada {current}:")
        out.append(_turn_line(i, turn))
    return "\n".join(out)


def _turn_line(i: int, turn: InterviewTurn) -> str:
    accepted = " (aceitou a recomendação)" if turn.accepted_recommendation else ""
    return f"{i}. [{turn.question.topic}] {turn.question.question}\n   Resposta{accepted}: {turn.answer}"


def _plan_section(plan: Plan, epic_id: str | None = None) -> str:
    epic = next((e for e in plan.epics if e.id == epic_id), None)
    if epic is not None:  # a lane of a split plan only gets its own slice (D53)
        return _epic_section(plan, epic)
    steps = "\n".join(f"{i}. {step}" for i, step in enumerate(plan.steps, 1))
    files = "\n".join(f"- {f.change} {f.path}" for f in plan.files)
    lines = ["## Plano", plan.summary, "Passos:", steps, "Arquivos:", files]
    lines += ["Critérios de aceite:", _bullets(plan.acceptance_criteria)]
    if plan.risks:
        lines += ["Riscos:", _bullets(plan.risks)]
    lines += ["Estratégia de teste:", plan.test_strategy]
    return "\n".join(lines)


def _epic_section(plan: Plan, epic: Epic) -> str:
    others = [f"{e.id} ({e.title})" for e in plan.epics if e.id != epic.id]
    lines = [
        "## Plano",
        plan.summary,
        f"Seu épico: {epic.id} · {epic.title}",
        f"Objetivo: {epic.goal}",
        "Passos:",
        "\n".join(f"{i}. {step}" for i, step in enumerate(epic.steps, 1)),
        "Arquivos (só estes; os outros épicos cuidam do resto):",
        "\n".join(f"- {f.change} {f.path}" for f in epic.files),
        "Critérios de aceite do épico:",
        _bullets(epic.acceptance_criteria),
    ]
    if epic.depends_on:
        lines.append(f"Já está no código: os épicos dos quais este depende ({', '.join(epic.depends_on)}).")
    if others:
        lines.append(f"Outros épicos do plano (não mexa no que é deles): {', '.join(others)}.")
    lines += ["Estratégia de teste:", plan.test_strategy]
    return "\n".join(lines)


def feedback_section(feedback: Feedback) -> str:
    lines = ["## Feedback"]
    if feedback.kind == "test_failures" and feedback.test is not None:
        t = feedback.test
        lines.append(f"Falhas de teste ({t.passed}/{t.total} passaram; comando: `{t.command}`):")
        lines += [f"- {f.test}: {f.message}" for f in t.failures]
    elif feedback.kind == "review_comments" and feedback.review is not None:
        lines.append("Comentários do Reviewer:")
        for c in feedback.review.comments:
            where = f"{c.file}:{c.line}" if c.line else c.file
            state = " [resolvido]" if c.resolved else ""
            lines.append(f"- [{c.severity}] {where}: {c.text}{state}")
    elif feedback.kind == "human_instruction":
        lines += ["Instrução do usuário:", (feedback.text or "").strip()]
    elif feedback.kind == "plan_adjust":
        lines += ["Ajuste pedido ao plano:", (feedback.text or "").strip()]
    else:
        lines.append((feedback.text or "").strip())
    return "\n".join(lines)


def _resume_answer_section(history: list[InterviewTurn]) -> str:
    last_round = history[-1].round
    lines = ["## Feedback", f"Respostas do usuário à rodada {last_round}:"]
    lines += [_turn_line(i, t) for i, t in enumerate(history, 1) if t.round == last_round]
    lines.append(f"Total de perguntas respondidas até agora: {len(history)}.")
    return "\n".join(lines)


def _rules_section(job: AgentJob, spec: AgentSpec[Any]) -> str:
    lines = [
        "## Regras do job",
        f"- Rodada {job.attempt} deste agente na tarefa {job.task_id}.",
        f"- Termine chamando `{spec.submit_name}`.",
    ]
    if spec.writes_files and job.workspace_path:
        lines.append(f"- Worktree (seu diretório de trabalho): {job.workspace_path}")
    if job.repo.new_project and job.agent in ("interviewer", "planner"):
        lines.append(
            "- Projeto novo: o repositório acabou de ser criado e está vazio. Defina a stack e os comandos "
            "em `project_setup`; se dividir em épicos, comece por E0 (fundação)."
        )
    elif job.repo.new_project and job.agent == "developer":
        lines.append(
            "- Projeto novo: declare toda dependência no manifesto (package.json, pyproject.toml...). Você "
            "não instala nada: o dev-crew roda o comando de setup do plano antes do Tester."
        )
    if job.epic_id:
        lines.append(f"- Você trabalha no épico {job.epic_id}: faça só o que o plano atribui a ele.")
    if job.repo.sandbox and spec.bash != "none":
        lines.append(
            "- Comandos: use a tool `run` (container Linux isolado, cwd /work = o worktree, sem internet). "
            "Não existe Bash. Use caminhos relativos; Read/Edit/Write continuam no caminho do worktree acima."
        )
    match job.agent:
        case "developer":
            lines.append(f"- `round` do resultado: {job.attempt}.")
            if job.repo.lint_cmd:
                lines.append(f"- Lint do repo: `{job.repo.lint_cmd}`.")
            lines.append(f"- Comando de testes do repo: `{job.repo.test_cmd}`.")
        case "tester":
            lines.append(f"- Comando de testes (rode a suíte completa com ele): `{job.repo.test_cmd}`.")
            if job.repo.lint_cmd:
                lines.append(f"- Lint do repo (obrigatório, depois dos testes): `{job.repo.lint_cmd}`.")
            lines.append(
                "- Arquivos de teste permitidos: " + ", ".join(f"`{g}`" for g in effective_test_globs(job))
            )
        case "reviewer":
            lines.append(
                f"- Branch base para o diff: `{job.repo.base_branch}` (`git diff {job.repo.base_branch}`)."
            )
            lines.append(f"- Idioma da mensagem de commit: {job.repo.commit_language}.")
        case "interviewer":
            lines.append(
                f"- Perguntas já respondidas: {len(job.interview_history)}. "
                "Pare só quando não restar decisão em aberto na árvore."
            )
        case _:
            pass
    return "\n".join(lines)


def has_new_information(job: AgentJob) -> bool:
    """A resumed session needs something new to say: feedback, or an answer for the interviewer."""
    return job.feedback is not None or (job.agent == "interviewer" and bool(job.interview_history))


def build_prompt(job: AgentJob, spec: AgentSpec[Any], *, resumed: bool) -> str:
    """User prompt for one job. ``resumed``: the session already holds task and plan."""
    sections: list[str] = []
    if resumed:
        if job.feedback is not None:
            sections.append(feedback_section(job.feedback))
        elif job.agent == "interviewer" and job.interview_history:
            sections.append(_resume_answer_section(job.interview_history))
    else:
        sections.append(_task_section(job))
        if job.plan is not None:
            sections.append(_plan_section(job.plan, job.epic_id))
        if job.feedback is not None:
            sections.append(feedback_section(job.feedback))
    sections.append(_rules_section(job, spec))
    return "\n\n".join(sections) + "\n"

"""The plan saved inside the project (D57): ``docs/plano/T-n.md``, readable without dev-crew."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .contracts import Estimate, Plan

STATUS_LABEL = {
    "pending": "pendente",
    "waiting": "na fila",
    "preparing": "preparando",
    "running": "em execução",
    "escalated": "escalado",
    "limited": "parado no limite de uso",
    "merging": "juntando",
    "merged": "pronto",
    "failed": "falhou",
}


def _bullets(items: list[str]) -> list[str]:
    return [f"- {i}" for i in items] or ["- (nenhum)"]


def render(
    task_id: str,
    title: str,
    plan: Plan,
    *,
    estimate: Estimate | None = None,
    status: Mapping[str, str] | None = None,
    commits: Mapping[str, str] | None = None,
    updated: datetime | None = None,
) -> str:
    """Markdown of the plan; ``status``/``commits`` (by epic id) track progress in a split plan."""
    status = status or {}
    commits = commits or {}
    lines = [f"# {task_id} · {title}", ""]
    if updated is not None:
        lines += [f"_Plano gerado pelo dev-crew. Atualizado em {updated:%Y-%m-%d %H:%M} (UTC)._", ""]
    lines += ["## Resumo", "", plan.summary, ""]
    if plan.split_rationale:
        lines += ["## Por que assim", "", plan.split_rationale, ""]
    if plan.project_setup is not None:
        s = plan.project_setup
        lines += ["## Projeto", "", f"- Stack: {s.stack}", f"- Testes: `{s.test_cmd}`"]
        if s.setup_cmd:
            lines.append(f"- Setup: `{s.setup_cmd}`")
        if s.lint_cmd:
            lines.append(f"- Lint: `{s.lint_cmd}`")
        if s.sandbox_image:
            lines.append(f"- Container: `{s.sandbox_image}`")
        lines.append("")

    if plan.execution == "epics" and plan.epics:
        lines += ["## Épicos", "", "| Épico | Título | Depende de | Tamanho | Status |"]
        lines.append("|---|---|---|---|---|")
        for e in plan.epics:
            state = STATUS_LABEL.get(status.get(e.id, "pending"), status.get(e.id, ""))
            sha = commits.get(e.id)
            if sha:
                state = f"{state} (`{sha[:8]}`)"
            deps = ", ".join(e.depends_on) or "—"
            lines.append(f"| {e.id} | {e.title} | {deps} | {e.size} | {state} |")
        lines.append("")
        for e in plan.epics:
            lines += [f"### {e.id} · {e.title}", "", e.goal, "", "Passos:"]
            lines += [f"{i}. {s}" for i, s in enumerate(e.steps, 1)]
            lines += ["", "Arquivos:"] + [f"- `{f.change}` {f.path}" for f in e.files]
            lines += ["", "Critérios de aceite:", *_bullets(e.acceptance_criteria), ""]
    else:
        lines += ["## Passos", ""] + [f"{i}. {s}" for i, s in enumerate(plan.steps, 1)] + [""]
        lines += ["## Arquivos", ""] + [f"- `{f.change}` {f.path}" for f in plan.files] + [""]

    lines += ["## Critérios de aceite", "", *_bullets(plan.acceptance_criteria), ""]
    if plan.risks:
        lines += ["## Riscos", "", *_bullets(plan.risks), ""]
    lines += ["## Estratégia de testes", "", plan.test_strategy, ""]
    if estimate is not None:
        lines += ["## Estimativa", "", f"- Tokens: ~{estimate.tokens:,}".replace(",", ".")]
        lines.append(f"- Equivalente API: ~US$ {estimate.usd:.2f}")
        if estimate.session_pct is not None:
            lines.append(f"- Sessão de 5 h: ~{estimate.session_pct:g}%")
        if estimate.weekly_pct is not None:
            lines.append(f"- Semana: ~{estimate.weekly_pct:g}%")
        lines += [f"- Base: {estimate.basis}", ""]
    return "\n".join(lines).rstrip() + "\n"

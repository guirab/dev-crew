"""Dependency graph of a split plan (D53): validation for the Planner, scheduling for the orchestrator."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .contracts import Epic, Plan


def ancestors(epics: Sequence[Epic]) -> dict[str, set[str]]:
    """Every epic an epic depends on, directly or not. Assumes ``validate`` passed (no cycle)."""
    deps = {e.id: set(e.depends_on) for e in epics}
    out: dict[str, set[str]] = {}

    def walk(epic_id: str) -> set[str]:
        if epic_id not in out:
            seen: set[str] = set()
            for d in deps.get(epic_id, ()):
                seen |= {d} | walk(d)
            out[epic_id] = seen
        return out[epic_id]

    for e in epics:
        walk(e.id)
    return out


def _cycle(epics: Sequence[Epic]) -> list[str] | None:
    deps = {e.id: list(e.depends_on) for e in epics}
    state: dict[str, int] = {}  # 1 = on the stack, 2 = done
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        path.append(node)
        for d in deps.get(node, []):
            if state.get(d) == 1:
                return [*path[path.index(d) :], d]
            if d in deps and state.get(d) is None and (found := visit(d)):
                return found
        path.pop()
        state[node] = 2
        return None

    for e in epics:
        if state.get(e.id) is None and (found := visit(e.id)):
            return found
    return None


def parallel_overlaps(epics: Sequence[Epic]) -> list[tuple[str, str, list[str]]]:
    """Pairs of epics with no dependency path between them that touch the same files."""
    anc = ancestors(epics)
    overlaps: list[tuple[str, str, list[str]]] = []
    for i, a in enumerate(epics):
        files_a = {f.path for f in a.files}
        for b in epics[i + 1 :]:
            if a.id in anc[b.id] or b.id in anc[a.id]:
                continue
            shared = sorted(files_a & {f.path for f in b.files})
            if shared:
                overlaps.append((a.id, b.id, shared))
    return overlaps


def validate(plan: Plan, *, new_project: bool = False) -> str | None:
    """Problems the Planner must fix before its plan is accepted (pt-BR, one at a time)."""
    if new_project and plan.project_setup is None:
        return "projeto novo: preencha project_setup (stack, test_cmd, setup_cmd, sandbox_image...)."
    if plan.execution == "single":
        if plan.epics:
            return 'execution="single" não leva epics; use execution="epics" ou deixe epics vazio.'
        if not plan.steps:
            return "steps não pode ser vazio."
        return None

    epics = plan.epics
    if len(epics) < 2:
        return 'execution="epics" exige ao menos 2 épicos; uma entrega só é execution="single".'
    if not plan.split_rationale.strip():
        return "split_rationale não pode ser vazio: explique por que esses épicos."
    ids = [e.id for e in epics]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        return f"ids de épico repetidos: {', '.join(dupes)}."
    known = set(ids)
    for e in epics:
        if not e.steps or not e.files or not e.acceptance_criteria:
            return f"{e.id}: steps, files e acceptance_criteria não podem ser vazios."
        if e.id in e.depends_on:
            return f"{e.id} depende de si mesmo."
        missing = [d for d in e.depends_on if d not in known]
        if missing:
            return f"{e.id} depende de épico inexistente: {', '.join(missing)}."
    if (cycle := _cycle(epics)) is not None:
        return f"dependência circular: {' → '.join(cycle)}."
    if new_project:
        if "E0" not in known:
            return "projeto novo dividido em épicos: o primeiro é E0 (fundação)."
        loose = [e.id for e in epics if e.id != "E0" and "E0" not in ancestors(epics)[e.id]]
        if loose:
            return f"todos os épicos dependem de E0 (fundação); faltam: {', '.join(loose)}."
    overlaps = parallel_overlaps(epics)
    if overlaps:
        a, b, files = overlaps[0]
        return (
            f"{a} e {b} rodam em paralelo e editam os mesmos arquivos ({', '.join(files[:5])}): "
            "mova essa edição pra um épico do qual os dois dependam, ou faça um depender do outro."
        )
    return None


def ready(epics: Iterable[Epic], *, merged: set[str], chosen: set[str], started: set[str]) -> list[str]:
    """Chosen epics not started yet whose dependencies are all merged, in plan order."""
    return [e.id for e in epics if e.id in chosen and e.id not in started and set(e.depends_on) <= merged]


def closure(epics: Sequence[Epic], chosen: Iterable[str]) -> set[str]:
    """``chosen`` plus everything it depends on: running E3 means running E1 and E2 first."""
    anc = ancestors(epics)
    out: set[str] = set()
    for epic_id in chosen:
        out |= {epic_id} | anc.get(epic_id, set())
    return out

"""Scripted agents (zero tokens): the scenario of ``mockup/index.html``.

- Interviewer: 3 questions, then ``done`` with the consolidated spec.
- Planner: a 4-step plan.
- Developer: really writes/edits files in the worktree, so the final report has a diff.
- Tester: first attempt fails (2 failures), then passes; with ``fake_escalate`` it always fails.
- Reviewer: round 1 ``changes_requested`` (1 major, 1 minor), round 2 ``approved`` + commit message.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from ..bus import FatalJobError
from ..contracts import (
    AgentJob,
    AgentOutput,
    DevResult,
    InterviewQuestion,
    InterviewResult,
    Plan,
    PlanFile,
    ReviewComment,
    ReviewResult,
    TaskSpec,
    TestFailure,
    TestResult,
)
from .pathjail import PathJail
from .progress import ProgressLine, ProgressSink
from .runner import RunOutcome
from .settings import AgentRuntimeSettings
from .specs import COMMIT_SUBJECT_MAX, SPECS

Sleep = Callable[[float], Awaitable[None]]

FAKE_COSTS = {"interviewer": 0.01, "planner": 0.05, "developer": 0.12, "tester": 0.04, "reviewer": 0.06}

QUESTIONS: tuple[InterviewQuestion, ...] = (
    InterviewQuestion(
        topic="Fora de escopo",
        question="O que fica explicitamente fora do escopo desta entrega?",
        recommendation="Listar 1–3 coisas que ficam pra depois — evita o Developer expandir escopo.",
        rationale="Escopo explícito reduz retrabalho nas rodadas de correção.",
    ),
    InterviewQuestion(
        topic="Critérios de aceite",
        question="Como a gente sabe que está pronto? Quais critérios o Tester deve validar?",
        recommendation="3 critérios verificáveis por teste automatizado (entrada → saída esperada).",
    ),
    InterviewQuestion(
        topic="Restrições",
        question="Alguma restrição técnica? (lib proibida, padrão do repo, performance)",
        recommendation="Seguir padrões existentes do repo; nenhuma dependência nova sem aprovação.",
        options=[
            "Seguir padrões existentes do repo; nenhuma dependência nova sem aprovação.",
            "Pode adicionar dependências se justificar no plano.",
        ],
    ),
)
ROUNDS = ((QUESTIONS[0], QUESTIONS[1]), (QUESTIONS[2],))


def next_round(
    rounds: tuple[tuple[InterviewQuestion, ...], ...], answered: int
) -> tuple[InterviewQuestion, ...] | None:
    """The scripted round that follows ``answered`` questions, or ``None`` when the script is over."""
    seen = 0
    for questions in rounds:
        if answered <= seen:
            return questions
        seen += len(questions)
    return None


DEFAULT_PLAN_FILES: tuple[PlanFile, ...] = (
    PlanFile(path="src/api/routes.py", change="M"),
    PlanFile(path="src/services/service.py", change="M"),
    PlanFile(path="web/components/Feature.tsx", change="A"),
    PlanFile(path="tests/test_feature.py", change="A"),
)

FAILURES: tuple[TestFailure, ...] = (
    TestFailure(test="tests/test_feature.py::test_range_inclusive_end", message="esperado 12, obtido 9"),
    TestFailure(test="tests/test_feature.py::test_invalid_input_returns_400", message="assert 200 == 400"),
)

HASH_COMMENT = (".py", ".sh", ".toml", ".yml", ".yaml", ".rb")
SLASH_COMMENT = (".ts", ".tsx", ".js", ".jsx", ".java", ".cs", ".go", ".rs")
LINE_COMMENT = {**dict.fromkeys(HASH_COMMENT, "#"), **dict.fromkeys(SLASH_COMMENT, "//")}
BLOCK_COMMENT = {".md": ("<!--", "-->"), ".html": ("<!--", "-->")}


SAMPLE_PLAN_FILES: tuple[PlanFile, ...] = (
    PlanFile(path="shop/report.py", change="M"),
    PlanFile(path="tests/test_report.py", change="M"),
)


def _plan_files(job: AgentJob) -> list[PlanFile]:
    """Plan files that exist in the worktree when it is the sample repo; the mockup's otherwise."""
    if job.workspace_path and (Path(job.workspace_path) / "shop" / "report.py").is_file():
        return list(SAMPLE_PLAN_FILES)
    return list(DEFAULT_PLAN_FILES)


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def commit_subject(kind: str, title: str) -> str:
    subject = f"{kind}: {lower_first(title.strip())}"
    if len(subject) <= COMMIT_SUBJECT_MAX:
        return subject
    cut = subject[: COMMIT_SUBJECT_MAX - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "feature"


class ScriptedRunner:
    def __init__(self, settings: AgentRuntimeSettings, *, sleep: Sleep = asyncio.sleep) -> None:
        self.settings = settings
        self._sleep = sleep

    async def run(self, job: AgentJob, emit: ProgressSink) -> RunOutcome:
        spec = SPECS[job.agent]
        steps = _Steps(emit, self._sleep, self.settings.fake_speed)
        output: AgentOutput
        match job.agent:
            case "interviewer":
                output = await self._interviewer(job, steps)
            case "planner":
                output = await self._planner(job, steps)
            case "developer":
                output = await self._developer(job, steps)
            case "tester":
                output = await self._tester(job, steps)
            case "reviewer":
                output = await self._reviewer(job, steps)
        if spec.check is not None and (problem := spec.check(output)):
            raise FatalJobError(f"cenário fake inconsistente: {problem}")
        if spec.finalize is not None:
            output = spec.finalize(output, job)
        return RunOutcome(
            output=output, cost_usd=FAKE_COSTS[job.agent], session_id=f"fake-{job.agent}-{job.job_id.hex[:8]}"
        )

    # ---------------------------------------------------------------- interviewer
    async def _interviewer(self, job: AgentJob, steps: _Steps) -> InterviewResult:
        asked = len(job.interview_history)
        if asked == 0:
            await steps.step("Lendo a descrição e o repo", 0.8)
        await steps.step("Explorando o repo (Grep/Read nos módulos afetados)", 0.8)
        questions = next_round(ROUNDS, asked)
        if questions is not None:
            return InterviewResult(kind="question", questions=list(questions))
        await steps.step("Consolidando a spec", 0.6)
        return InterviewResult(kind="done", spec=_consolidate(job.spec, job))

    # ---------------------------------------------------------------- planner
    async def _planner(self, job: AgentJob, steps: _Steps) -> Plan:
        fb = job.feedback
        if fb is not None and fb.kind == "plan_adjust" and fb.text:
            await steps.step(f'Revendo plano: "{fb.text}"', 1.0)
        else:
            await steps.step("Lendo tarefa e critérios de aceite", 1.0)
        await steps.step("Explorando repo (Grep/Read nos módulos afetados)", 1.3)
        await steps.step("Montando passos, arquivos e critérios", 1.0)
        criteria = [*job.spec.acceptance_criteria, "Sem regressão na suíte existente"]
        if not job.spec.acceptance_criteria:
            criteria.insert(0, job.spec.title)
        return Plan(
            summary=(
                f'Implementar "{job.spec.title}" seguindo os padrões do repo, '
                "com testes cobrindo os critérios de aceite."
            ),
            steps=[
                "Mapear módulo afetado e pontos de extensão",
                "Backend: endpoint/serviço com validação de entrada",
                "Front: componente + estado na query string",
                "Testes: unit no serviço + integração no endpoint",
            ],
            files=_plan_files(job),
            acceptance_criteria=criteria,
            risks=["Mudança de contrato da API pode afetar clientes existentes"],
            test_strategy="Unit no serviço (bordas do intervalo, entrada inválida) e integração no endpoint.",
        )

    # ---------------------------------------------------------------- developer
    async def _developer(self, job: AgentJob, steps: _Steps) -> DevResult:
        jail = PathJail(job.workspace_path) if job.workspace_path else None
        fb = job.feedback
        if fb is not None:
            await steps.step(_fix_reason(job), 1.2)
        files = list(job.plan.files) if job.plan else list(DEFAULT_PLAN_FILES)
        changed: list[PlanFile] = []
        for pf in files:
            if (
                fb is not None
                and pf.change == "A"
                and jail is not None
                and (Path(jail.root) / pf.path).exists()
            ):
                continue  # correction rounds touch what exists; created files are not recreated
            verb = {"A": "Criando", "M": "Editando", "D": "Removendo"}[pf.change]
            await steps.step(f"{verb} {pf.path}", 1.0)
            if jail is not None and not _apply(jail, pf, job.attempt, fb is not None):
                continue
            changed.append(pf)
        if not changed:
            changed = files[:1]
        summary = (
            f"Rodada {job.attempt}: corrige o feedback recebido ({_fix_reason(job).lower()})."
            if fb is not None
            else f"Implementa o plano em {len(changed)} arquivos."
        )
        return DevResult(round=job.attempt, summary=summary, files_changed=changed)

    # ---------------------------------------------------------------- tester
    async def _tester(self, job: AgentJob, steps: _Steps) -> TestResult:
        first = job.attempt == 1
        written: list[str] = []
        if first:
            await steps.step("Escrevendo testes de integração", 0.9)
            written = _write_acceptance_test(job)
        else:
            await steps.step("Rodando a suíte de novo", 0.9)
        await steps.step(f"$ {job.repo.test_cmd}", 1.3)
        if self.settings.fake_escalate or first:
            return TestResult(
                ok=False,
                passed=46,
                total=48,
                failures=list(FAILURES),
                command=job.repo.test_cmd,
                tests_written=written,
            )
        return TestResult(
            ok=True, passed=48, total=48, coverage=0.87, command=job.repo.test_cmd, tests_written=written
        )

    # ---------------------------------------------------------------- reviewer
    async def _reviewer(self, job: AgentJob, steps: _Steps) -> ReviewResult:
        await steps.step("$ git diff — lendo alterações", 1.1)
        await steps.step("Checando segurança, padrões do repo e aderência ao plano", 1.3)
        paths = [f.path for f in job.plan.files] if job.plan else [f.path for f in DEFAULT_PLAN_FILES]
        previous = job.feedback.review.comments if job.feedback and job.feedback.review else []
        if job.attempt == 1 and not previous:
            return ReviewResult(
                verdict="changes_requested",
                comments=[
                    ReviewComment(
                        severity="major",
                        file=paths[min(1, len(paths) - 1)],
                        line=42,
                        text="Query montada com f-string — usar bind params.",
                    ),
                    ReviewComment(
                        severity="minor",
                        file=paths[-1],
                        line=9,
                        text="Converter datas pra UTC antes de enviar.",
                    ),
                ],
            )
        resolved = [c.model_copy(update={"resolved": True}) for c in previous]
        return ReviewResult(verdict="approved", comments=resolved, commit_message=_commit_message(job))


class _Steps:
    """Emits one progress line and waits ``base / speed`` seconds, like the mockup's ``step``."""

    def __init__(self, emit: ProgressSink, sleep: Sleep, speed: float) -> None:
        self._emit = emit
        self._sleep = sleep
        self._speed = max(speed, 1e-6)

    async def step(self, text: str, seconds: float) -> None:
        await self._emit(ProgressLine("tool", text))
        await self._sleep(seconds / self._speed)


def _fix_reason(job: AgentJob) -> str:
    fb = job.feedback
    if fb is None:
        return ""
    if fb.kind == "test_failures" and fb.test is not None:
        names = ", ".join(f.test.rsplit("::", 1)[-1] for f in fb.test.failures)
        return f"Corrigindo: {names}"
    if fb.kind == "review_comments":
        return "Aplicando review: bind params na query, datas em UTC"
    return f'Seguindo sua instrução: "{fb.text or ""}"'


def _consolidate(spec: TaskSpec, job: AgentJob) -> TaskSpec:
    by_topic = {t.question.topic: t.answer for t in job.interview_history}
    decisions = [f"{t.question.topic}: {t.answer}" for t in job.interview_history]
    return spec.model_copy(
        update={
            "decisions": decisions,
            "out_of_scope": [by_topic["Fora de escopo"]]
            if "Fora de escopo" in by_topic
            else spec.out_of_scope,
            "acceptance_criteria": (
                [by_topic["Critérios de aceite"]]
                if "Critérios de aceite" in by_topic
                else spec.acceptance_criteria
            ),
            "constraints": [by_topic["Restrições"]] if "Restrições" in by_topic else spec.constraints,
        }
    )


def _commit_message(job: AgentJob) -> str:
    steps = job.plan.steps[1:] if job.plan else []
    lines = [commit_subject("feat", job.spec.title), ""]
    lines += [f"- {lower_first(s)}" for s in steps]
    if job.attempt > 1:
        lines.append("- bind params na query e datas em UTC (review)")
    return "\n".join(lines).rstrip()


def _comment(path: str, text: str) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in LINE_COMMENT:
        return f"{LINE_COMMENT[ext]} {text}\n"
    if ext in BLOCK_COMMENT:
        start, end = BLOCK_COMMENT[ext]
        return f"{start} {text} {end}\n"
    return None


def _new_file_content(path: str, text: str) -> str:
    name = Path(path).name
    if path.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
        return f'"""{text}"""\n\n\ndef test_placeholder_written_by_fake_agent() -> None:\n    assert True\n'
    if path.endswith(".py"):
        return f'"""{text}"""\n'
    if path.endswith((".ts", ".tsx", ".js", ".jsx")):
        return f"// {text}\nexport {{}};\n"
    return _comment(path, text) or ""


def _apply(jail: PathJail, pf: PlanFile, attempt: int, correction: bool) -> bool:
    """Perform the file operation of a plan entry inside the worktree. ``False`` if nothing changed."""
    target = jail.resolve(pf.path)
    if target is None or not target.inside or not target.rel:
        raise FatalJobError(f"o plano aponta para fora do worktree: {pf.path}")
    path = Path(jail.root) / target.rel
    note = f"crew-fake (rodada {attempt}): " + (
        "correção do feedback" if correction else "implementação do plano"
    )
    if pf.change == "D":
        if not path.exists():
            return False
        path.unlink()
        return True
    if pf.change == "A" and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_new_file_content(pf.path, note), encoding="utf-8")
        return True
    line = _comment(pf.path, note)
    if line is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    sep = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + sep + line, encoding="utf-8")
    return True


def _write_acceptance_test(job: AgentJob) -> list[str]:
    """The Tester's new test file (only in the worktree, only on the first attempt)."""
    rel = f"tests/test_{slug(job.spec.title)[:40]}_acceptance.py"
    if not job.workspace_path:
        return [rel]
    jail = PathJail(job.workspace_path)
    target = jail.resolve(rel)
    if target is None or not target.inside or not target.rel:
        raise FatalJobError(f"caminho de teste fora do worktree: {rel}")
    path = Path(jail.root) / target.rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _new_file_content(rel, "crew-fake: testes de aceitação escritos pelo Tester"), encoding="utf-8"
    )
    return [rel]

"""Scripted fake agents for Stream A tests and ``crew up --fake-agents`` while Stream B is not merged.

Same wire behaviour as a real worker: consume ``crew.job.<agent>`` through ``job_loop``, publish
``progress`` and ``result`` events, honour ``crew.ctl.<task>.cancel``. The scenario mirrors the mockup:

- interviewer: 3 questions (with recommendation), then the consolidated spec;
- planner: a 4-step plan;
- developer: writes real files in the worktree (so the final report has a diff);
- tester: first run fails (``escalate``: the first 3 fail), then passes;
- reviewer: first review requests changes, the second approves with a commit message.

No LLM, no network, no tokens.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path

import structlog
from nats.aio.msg import Msg

from ..bus import Bus, JobControl, JobHandler, job_loop
from ..contracts import (
    AGENTS,
    AgentJob,
    AgentName,
    AgentOutput,
    AgentProgress,
    AgentResultEvt,
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

log = structlog.get_logger(__name__)

FAKE_COST_USD = 0.05
QUESTIONS = (
    InterviewQuestion(
        topic="Fora de escopo",
        question="O que fica explicitamente fora do escopo desta entrega?",
        recommendation="Listar 1–3 coisas que ficam pra depois — evita o Developer expandir escopo.",
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
# round 1 = the two independent questions; round 2 depends on them
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


FEATURE_FILE = "src/crew_fake_feature.py"
TEST_FILE = "tests/test_crew_fake_feature.py"


class _Cancelled(Exception):
    """The task was cancelled while a fake job was running."""


class FakeCrew:
    """All five fake agents sharing one scenario script (counters decide when tests/reviews fail)."""

    def __init__(self, bus: Bus, *, speed: float = 1.0, escalate: bool = False) -> None:
        self.bus = bus
        self.speed = max(speed, 0.001)
        self.test_failures_left = 3 if escalate else 1
        self.reviews_done = 0
        self._cancelled: set[str] = set()

    # ------------------------------------------------------------------ lifecycle

    async def run(self, stop: asyncio.Event, agents: tuple[AgentName, ...] = AGENTS) -> None:
        async def on_cancel(msg: Msg) -> None:
            parts = msg.subject.split(".")  # crew.ctl.<task>.cancel
            if len(parts) == 4:
                self._cancelled.add(parts[2])

        sub = await self.bus.subscribe_core("crew.ctl.*.cancel", on_cancel)
        loops = [asyncio.create_task(self._loop(a, stop), name=f"fake-{a}") for a in agents]
        try:
            await stop.wait()
        finally:
            await asyncio.gather(*loops, return_exceptions=True)
            with contextlib.suppress(Exception):
                await sub.unsubscribe()

    async def _loop(self, agent: AgentName, stop: asyncio.Event) -> None:
        # job_loop does not survive a bare asyncio.TimeoutError from nats-py fetch (contract-requests.md)
        while not stop.is_set():
            try:
                await job_loop(
                    self.bus, agent, self._handler(agent), stop=stop, fetch_timeout=0.2, heartbeat_s=5.0
                )
            except TimeoutError:
                continue

    def _handler(self, agent: AgentName) -> JobHandler:
        script: dict[AgentName, Callable[[AgentJob], Awaitable[AgentOutput]]] = {
            "interviewer": self._interviewer,
            "planner": self._planner,
            "developer": self._developer,
            "tester": self._tester,
            "reviewer": self._reviewer,
        }

        async def handle(job: AgentJob, _ctl: JobControl) -> None:
            try:
                output = await script[agent](job)
            except _Cancelled:
                log.info("fake_job_cancelled", agent=agent, task_id=job.task_id)
                return
            evt = AgentResultEvt(
                agent=agent,
                job_id=job.job_id,
                output=output,
                cost_usd=FAKE_COST_USD,
                session_id=f"fake-{agent}-{job.task_id}",
                duration_s=0.1,
            )
            await self.bus.publish_event(job.task_id, "result", evt, source=agent)

        return handle

    # ------------------------------------------------------------------ helpers

    async def _say(self, job: AgentJob, text: str, seconds: float = 0.8) -> None:
        if job.task_id in self._cancelled:
            raise _Cancelled
        prog = AgentProgress(agent=job.agent, job_id=job.job_id, kind="tool", text=text)
        await self.bus.publish_event(job.task_id, "progress", prog, source=job.agent)
        await asyncio.sleep(seconds / self.speed)
        if job.task_id in self._cancelled:
            raise _Cancelled

    # ------------------------------------------------------------------ agents

    async def _interviewer(self, job: AgentJob) -> AgentOutput:
        await self._say(job, "Lendo a descrição e o repo")
        questions = next_round(ROUNDS, len(job.interview_history))
        if questions is not None:
            return InterviewResult(kind="question", questions=list(questions))
        decisions = [f"{t.question.topic}: {t.answer}" for t in job.interview_history]
        criteria = [t.answer for t in job.interview_history if t.question.topic == "Critérios de aceite"]
        spec = TaskSpec(
            title=job.spec.title,
            description=job.spec.description,
            repo=job.spec.repo,
            acceptance_criteria=criteria,
            decisions=decisions,
        )
        return InterviewResult(kind="done", spec=spec)

    async def _planner(self, job: AgentJob) -> AgentOutput:
        adjust = job.feedback.text if job.feedback and job.feedback.text else None
        await self._say(job, f'Revendo plano: "{adjust}"' if adjust else "Lendo tarefa e critérios de aceite")
        await self._say(job, "Explorando repo (Grep/Read nos módulos afetados)", 1.2)
        await self._say(job, "Montando passos, arquivos e critérios")
        summary = f'Implementar "{job.spec.title}" seguindo os padrões do repo, com testes.'
        if adjust:
            summary += f" Ajuste: {adjust}"
        return Plan(
            summary=summary,
            steps=[
                "Mapear módulo afetado e pontos de extensão",
                "Backend: endpoint/serviço com validação de entrada",
                "Front: componente + estado na query string",
                "Testes: unit no serviço + integração no endpoint",
            ],
            files=[
                PlanFile(path=FEATURE_FILE, change="A"),
                PlanFile(path=TEST_FILE, change="A"),
            ],
            acceptance_criteria=[*job.spec.acceptance_criteria, "Sem regressão na suíte existente"],
            risks=["Timezone: datas locais vs UTC"],
            test_strategy="Testes de integração cobrindo as bordas.",
        )

    async def _developer(self, job: AgentJob) -> AgentOutput:
        fb = job.feedback
        reason = {
            "test_failures": "Corrigindo as falhas de teste",
            "review_comments": "Aplicando os comentários do review",
            "human_instruction": f"Seguindo sua instrução: {fb.text if fb else ''}",
        }.get(fb.kind if fb else "", "Implementando o plano")
        await self._say(job, reason)
        await self._say(job, f"Editando {FEATURE_FILE}", 1.0)
        changed = self._write_files(job)
        return DevResult(
            round=job.attempt,
            summary=reason,
            files_changed=changed,
            notes=None,
        )

    def _write_files(self, job: AgentJob) -> list[PlanFile]:
        if not job.workspace_path:
            return []
        root = Path(job.workspace_path).resolve()
        out: list[PlanFile] = []
        for rel, header in (
            (FEATURE_FILE, "def feature():\n    return 'ok'\n"),
            (TEST_FILE, "def test_feature():\n    assert True\n"),
        ):
            target = (root / rel).resolve()
            if not target.is_relative_to(root):  # never write outside the worktree
                continue
            existed = target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(header if not existed else f"# round {job.attempt}\n")
            out.append(PlanFile(path=rel, change="M" if existed else "A"))
        return out

    async def _tester(self, job: AgentJob) -> AgentOutput:
        await self._say(
            job, "Escrevendo testes de integração" if job.attempt == 1 else "Rodando a suíte de novo"
        )
        await self._say(job, "$ pytest -q", 1.2)
        if self.test_failures_left > 0:
            self.test_failures_left -= 1
            return TestResult(
                ok=False,
                passed=46,
                total=48,
                command="pytest -q",
                failures=[
                    TestFailure(
                        test="tests/test_feature.py::test_range_inclusive_end",
                        message="esperado 12, obtido 9",
                    ),
                    TestFailure(
                        test="tests/test_feature.py::test_invalid_input", message="assert 200 == 400"
                    ),
                ],
                tests_written=[TEST_FILE],
            )
        return TestResult(
            ok=True, passed=48, total=48, command="pytest -q", coverage=0.87, tests_written=[TEST_FILE]
        )

    async def _reviewer(self, job: AgentJob) -> AgentOutput:
        await self._say(job, "$ git diff — lendo alterações")
        await self._say(job, "Checando segurança, padrões do repo e aderência ao plano", 1.0)
        self.reviews_done += 1
        if self.reviews_done == 1:
            return ReviewResult(
                verdict="changes_requested",
                comments=[
                    ReviewComment(
                        severity="major",
                        file=FEATURE_FILE,
                        line=42,
                        text="Query montada com f-string — usar bind params.",
                    ),
                    ReviewComment(
                        severity="minor",
                        file=FEATURE_FILE,
                        line=9,
                        text="Converter datas pra UTC antes de enviar.",
                    ),
                ],
            )
        title = job.spec.title[:1].lower() + job.spec.title[1:]
        msg = f"feat: {title}\n\n- bind params na query e datas em UTC (review)"
        return ReviewResult(verdict="approved", comments=[], commit_message=msg)

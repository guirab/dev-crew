"""Builders and a ``Driver`` that feeds events to ``decide`` for readable state-machine tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TypeVar
from uuid import UUID, uuid4

from crew import contracts as c
from crew.orchestrator import events as ev
from crew.orchestrator.effects import DispatchJob, Effect
from crew.orchestrator.machine import decide
from crew.orchestrator.state import Limits, TaskState

T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
E = TypeVar("E", bound=Effect)


def repo_ctx() -> c.RepoContext:
    return c.RepoContext(
        name="sample-repo", base_branch="main", test_cmd="pytest -q", test_globs=["tests/**"]
    )


def question(n: int = 1) -> c.InterviewQuestion:
    topics = ["Fora de escopo", "Critérios de aceite", "Restrições"]
    return c.InterviewQuestion(
        topic=topics[(n - 1) % 3], question=f"Pergunta {n}?", recommendation=f"Recomendação {n}"
    )


def plan() -> c.Plan:
    return c.Plan(
        summary="Adicionar filtro de datas.",
        steps=["a", "b", "c", "d"],
        files=[
            c.PlanFile(path="shop/report.py", change="M"),
            c.PlanFile(path="shop/api.py", change="M"),
            c.PlanFile(path="tests/test_report_dates.py", change="A"),
        ],
        acceptance_criteria=["ok"],
        risks=[],
        test_strategy="integração",
    )


def dev(round_: int = 1) -> c.DevResult:
    return c.DevResult(
        round=round_, summary="feito", files_changed=[c.PlanFile(path="shop/report.py", change="M")]
    )


def fail_run() -> c.TestResult:
    return c.TestResult(
        ok=False,
        passed=46,
        total=48,
        command="pytest -q",
        failures=[
            c.TestFailure(
                test="tests/test_report_dates.py::test_range_inclusive_end", message="esperado 12, obtido 9"
            ),
            c.TestFailure(test="tests/test_report_dates.py::test_invalid_range", message="assert 200 == 422"),
        ],
    )


def pass_run() -> c.TestResult:
    return c.TestResult(ok=True, passed=48, total=48, command="pytest -q", coverage=0.87)


def review_changes() -> c.ReviewResult:
    return c.ReviewResult(
        verdict="changes_requested",
        comments=[
            c.ReviewComment(severity="major", file="shop/report.py", line=42, text="Query com f-string."),
            c.ReviewComment(severity="minor", file="shop/api.py", line=9, text="Converter datas pra UTC."),
        ],
    )


def review_ok(commit: str | None = "feat: filtro de datas") -> c.ReviewResult:
    return c.ReviewResult(verdict="approved", comments=[], commit_message=commit)


class Driver:
    """Owns the state, advances a fake clock and remembers the effects of each step."""

    def __init__(self, *, limits: Limits | None = None, task_id: str = "T-107") -> None:
        self.state: TaskState | None = None
        self.effects: list[Effect] = []
        self.history: list[Effect] = []
        self.clock = T0
        self.limits = limits or Limits()
        self.task_id = task_id

    # ---- plumbing
    def tick(self) -> datetime:
        self.clock += timedelta(seconds=1)
        return self.clock

    def feed(self, event: ev.Event) -> list[Effect]:
        snapshot = self.state.model_dump() if self.state is not None else None
        new_state, effects = decide(self.state, event)
        if snapshot is not None:  # purity: the input state must never be mutated
            assert self.state is not None and self.state.model_dump() == snapshot
        self.state = new_state
        self.effects = effects
        self.history.extend(effects)
        return effects

    def command(self, cmd: c.Command, *, start: ev.StartParams | None = None) -> list[Effect]:
        return self.feed(ev.CommandReceived(command=cmd, at=self.tick(), start=start))

    @property
    def s(self) -> TaskState:
        assert self.state is not None
        return self.state

    def one(self, kind: type[E]) -> E:
        found = [e for e in self.effects if isinstance(e, kind)]
        assert len(found) == 1, f"expected one {kind.__name__}, got {self.effects}"
        return found[0]

    def has(self, kind: type[Effect]) -> bool:
        return any(isinstance(e, kind) for e in self.effects)

    @property
    def job(self) -> c.AgentJob:
        return self.one(DispatchJob).job

    # ---- high level steps
    def params(self) -> ev.StartParams:
        return ev.StartParams(task_id=self.task_id, repo=repo_ctx(), limits=self.limits)

    def start(self) -> list[Effect]:
        return self.command(
            c.StartTask(repo="sample-repo", title="Exportar pedidos em CSV", description="d"),
            start=self.params(),
        )

    def boot(self) -> list[Effect]:
        """Run the pre-agent step (worktree) and return the first dispatch effects."""
        self.start()
        return self.feed(
            ev.WorkspaceReady(task_id=self.task_id, path="/wt/T-107", branch="crew/T-107", at=self.tick())
        )

    def result(
        self,
        output: c.AgentOutput,
        *,
        cost: float = 0.1,
        session: str | None = None,
        job_id: UUID | None = None,
    ) -> list[Effect]:
        s = self.s
        assert s.current_agent is not None and s.current_job_id is not None
        evt = c.AgentResultEvt(
            agent=s.current_agent,
            job_id=job_id or s.current_job_id,
            output=output,
            cost_usd=cost,
            session_id=session,
            duration_s=1.0,
        )
        return self.feed(ev.AgentResult(task_id=s.task_id, evt=evt, at=self.tick()))

    def failed(
        self, error: str = "boom", *, retryable: bool = False, job_id: UUID | None = None
    ) -> list[Effect]:
        s = self.s
        assert s.current_agent is not None and s.current_job_id is not None
        evt = c.AgentFailedEvt(
            agent=s.current_agent, job_id=job_id or s.current_job_id, error=error, retryable=retryable
        )
        return self.feed(ev.AgentFailed(task_id=s.task_id, evt=evt, at=self.tick()))

    def progress(self, text: str, *, job_id: UUID | None = None) -> list[Effect]:
        s = self.s
        assert s.current_agent is not None and s.current_job_id is not None
        evt = c.AgentProgress(
            agent=s.current_agent, job_id=job_id or s.current_job_id, kind="tool", text=text
        )
        return self.feed(ev.AgentProgressed(task_id=s.task_id, evt=evt, at=self.tick()))

    def report_built(self, files: list[c.FinalFile] | None = None) -> list[Effect]:
        return self.feed(ev.ReportBuilt(task_id=self.s.task_id, files=files or [], at=self.tick()))

    # ---- flows
    def to_planner(self) -> None:
        """Boot + a one-question interview (free, so budgets only count from the planner on)."""
        self.boot()
        self.result(c.InterviewResult(kind="question", questions=[question(1)]), cost=0.0)
        self.command(c.AnswerInterview(answers=[None]))
        spec = c.TaskSpec(title="Exportar pedidos em CSV", description="d", repo="sample-repo")
        self.result(c.InterviewResult(kind="done", spec=spec), cost=0.0)

    def to_awaiting_approval(self) -> None:
        self.to_planner()
        self.result(plan())

    def to_developing(self) -> None:
        self.to_awaiting_approval()
        self.command(c.ApprovePlan())

    def to_testing(self) -> None:
        self.to_developing()
        self.result(dev())

    def to_reviewing(self) -> None:
        self.to_testing()
        self.result(pass_run())

    def to_test_escalation(self) -> None:
        """3 consecutive failures with max 3."""
        self.to_testing()
        for _ in range(self.limits.max_test_attempts):
            self.result(fail_run())
            if self.s.phase == "escalated":
                break
            self.result(dev())

    def to_review_escalation(self) -> None:
        self.to_reviewing()
        for _ in range(self.limits.max_review_rounds):
            self.result(review_changes())
            if self.s.phase == "escalated":
                break
            self.result(dev())
            self.result(pass_run())

    def to_done(self) -> None:
        self.to_reviewing()
        self.result(review_ok())
        self.report_built()


def new_job_id() -> UUID:
    return uuid4()

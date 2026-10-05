"""The task state machine. PURE: ``decide(state, event) -> (state, effects)``, zero I/O, no clock, no LLM.

Conventions
- ``state`` is never mutated: ``decide`` works on a deep copy and returns it.
- ``state is None`` means "no task yet". A terminal task is replaced by the next ``start_task``.
- Stage/edge bookkeeping mirrors ``mockup/index.html`` (``go``/``finish``/``log``) so the UI is a pure render.
- A command that cannot be applied yields ``[Reject(error)]`` with the *same* state object.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import NAMESPACE_URL, uuid5

from ..bus import JOB_BUDGET_EXCEEDED
from ..contracts import (
    AdjustPlan,
    AgentJob,
    AgentName,
    AnswerInterview,
    ApprovePlan,
    CancelTask,
    DevResult,
    EdgeKey,
    EscalationAction,
    Feedback,
    FinalReport,
    InterviewResult,
    InterviewTurn,
    LogLine,
    Plan,
    ReviewResult,
    StageKey,
    StageStatus,
    StartTask,
    TaskPhase,
    TaskSpec,
    TestResult,
)
from . import budget
from .effects import (
    BuildFinalReport,
    CancelJobs,
    CreateWorkspace,
    DispatchJob,
    Effect,
    LogStale,
    Persist,
    PublishView,
    Reject,
)
from .events import (
    AgentFailed,
    AgentProgressed,
    AgentResult,
    CommandReceived,
    Event,
    JobTimedOut,
    ReportBuilt,
    StartParams,
    WorkspaceFailed,
    WorkspaceReady,
)
from .state import MAX_STAGE_LOGS, EscalationKind, EscalationState, PendingJob, TaskState

# --- rejection messages (pt-BR, shown to the user) -------------------------------------------------
# Conflicts (state does not allow the command) map to HTTP 409; the rest are validation errors (422).
ERR_ACTIVE_TASK: Final = "já existe tarefa ativa"
ERR_NO_TASK: Final = "nenhuma tarefa ativa"
ERR_WRONG_PHASE: Final = "comando indisponível na fase atual"
ERR_BUDGET: Final = "orçamento estourado — use more_attempts para liberar +50%"
CONFLICT_ERRORS: Final = frozenset({ERR_ACTIVE_TASK, ERR_NO_TASK, ERR_WRONG_PHASE, ERR_BUDGET})

ERR_UNKNOWN_REPO: Final = "repositório desconhecido"
ERR_TITLE_REQUIRED: Final = "título é obrigatório"
ERR_TEXT_REQUIRED: Final = "texto obrigatório"
ERR_ANSWERS_MISMATCH: Final = "responda todas as perguntas da rodada (uma resposta por pergunta)"
_BUDGET_NOW: Final = "Orçamento estourado — expanda pra decidir"
ERR_REPLAN_UNAVAILABLE: Final = "replanejar não se aplica: a spec ainda não foi fechada"

_PHASE: Final[dict[AgentName, TaskPhase]] = {
    "interviewer": "interviewing",
    "planner": "planning",
    "developer": "developing",
    "tester": "testing",
    "reviewer": "reviewing",
}
_DEFAULT_NOW: Final[dict[AgentName, str]] = {
    "interviewer": "Preparando a próxima pergunta",
    "planner": "Lendo tarefa e critérios de aceite",
    "developer": "Implementando o plano",
    "tester": "Escrevendo e rodando os testes",
    "reviewer": "$ git diff — lendo alterações",
}
_INSTRUCT_EDGE: Final[dict[AgentName, EdgeKey]] = {"tester": "ts-dv", "reviewer": "rv-dv"}
_WAITING_FOR_YOU = "Aguardando sua resposta — expanda pra responder"


# ============================================================ public API


def decide(state: TaskState | None, event: Event) -> tuple[TaskState | None, list[Effect]]:
    """Apply ``event``. Returns the new state (same object if nothing changed) and the effects to run."""
    match event:
        case CommandReceived():
            return _on_command(state, event)
        case AgentResult() | AgentFailed() | AgentProgressed() | JobTimedOut():
            return _on_agent_event(state, event)
        case WorkspaceReady() | WorkspaceFailed() | ReportBuilt():
            return _on_io_event(state, event)


def recovery_effects(state: TaskState) -> list[Effect]:
    """Effects to re-issue after a restart for non-agent steps that were in flight."""
    if state.terminal:
        return []
    match state.boot:
        case "create_workspace":
            return [CreateWorkspace(state.task_id, state.repo.name)]
        case "build_report" if state.workspace_path:
            return [BuildFinalReport(state.task_id, state.repo.name, state.workspace_path)]
        case _:
            return []


# ============================================================ small mutators (operate on a COPY)


def _log(s: TaskState, key: StageKey, text: str, at: datetime) -> None:
    st = s.stages[key]
    st.now = text
    st.logs = [*st.logs, LogLine(ts=at, text=text)][-MAX_STAGE_LOGS:]


def _set(s: TaskState, key: StageKey, status: StageStatus, text: str | None, at: datetime) -> None:
    s.stages[key].status = status
    if text is not None:
        _log(s, key, text, at)


def _settle_edge(s: TaskState) -> None:
    if s.active_edge is not None:
        s.edges[s.active_edge] = "on"
        s.active_edge = None


def _go(s: TaskState, edge: EdgeKey, key: StageKey, status: StageStatus = "active") -> None:
    if s.active_edge is not None:
        s.edges[s.active_edge] = "on"
    s.edges[edge] = "active"
    s.active_edge = edge
    s.stages[key].status = status


def _commit(s: TaskState, *effects: Effect) -> tuple[TaskState, list[Effect]]:
    return s, [Persist(), *effects, PublishView()]


def _copy(state: TaskState) -> TaskState:
    return state.model_copy(deep=True)


def _reject(state: TaskState | None, error: str) -> tuple[TaskState | None, list[Effect]]:
    return state, [Reject(error)]


def _stale(state: TaskState | None, task_id: str, what: str) -> tuple[TaskState | None, list[Effect]]:
    return state, [LogStale(task_id, what)]


# ============================================================ dispatch / escalate


def _make_job(s: TaskState, agent: AgentName, feedback: Feedback | None) -> AgentJob:
    job_id = uuid5(NAMESPACE_URL, f"crew:{s.task_id}:{s.started_at.isoformat()}:{s.job_seq}")
    return AgentJob(
        job_id=job_id,
        task_id=s.task_id,
        agent=agent,
        attempt=s.attempts.get(agent, 0),
        repo=s.repo,
        spec=s.spec,
        plan=None if agent == "interviewer" else s.plan,
        feedback=feedback,
        interview_history=list(s.interview_turns) if agent in ("interviewer", "planner") else [],
        workspace_path=s.workspace_path,
        resume_session_id=s.sessions.get(agent),
        budget_usd=budget.remaining(s.cost_usd, s.limits.budget_usd),
    )


def _advance(
    s: TaskState,
    at: datetime,
    agent: AgentName,
    *,
    edge: EdgeKey | None,
    feedback: Feedback | None = None,
    now: str | None = None,
) -> list[Effect]:
    """Hand the task to ``agent`` (budget permitting). Returns the effects (the dispatch)."""
    pending = PendingJob(agent=agent, feedback=feedback, edge=edge, now=now)
    if budget.exhausted(s.cost_usd, s.limits.budget_usd):
        reason = f"orçamento estourado (US$ {s.cost_usd:.2f} de {s.limits.budget_usd:.2f})"
        _escalate(s, at, "budget", agent, reason, pending=pending, now=_BUDGET_NOW)
        return []

    if edge is not None:
        _go(s, edge, agent)
    _set(s, agent, "active", now or _DEFAULT_NOW[agent], at)
    s.phase = _PHASE[agent]
    s.escalation = None
    if agent == "developer":
        s.dev_round += 1
    elif agent == "reviewer":
        s.review_round += 1
    s.job_seq += 1
    s.attempts[agent] = s.attempts.get(agent, 0) + 1
    s.inflight = PendingJob(agent=agent, feedback=feedback, edge=None, now=now)
    job = _make_job(s, agent, feedback)
    s.current_job_id = job.job_id
    s.current_agent = agent
    return [DispatchJob(job)]


def _escalate(
    s: TaskState,
    at: datetime,
    kind: EscalationKind,
    stage: AgentName,
    reason: str,
    *,
    pending: PendingJob | None = None,
    now: str | None = None,
) -> None:
    _settle_edge(s)
    s.phase = "escalated"
    s.current_job_id = None
    s.current_agent = None
    s.inflight = None
    s.escalation = EscalationState(kind=kind, stage=stage, reason=reason, pending=pending)
    _set(s, stage, "error", now or reason, at)


def _fail_job(s: TaskState, at: datetime, agent: AgentName, error: str, pending: PendingJob | None) -> None:
    """The in-flight job of ``agent`` died: escalate keeping the job so it can be retried."""
    _undo_round(s, agent)
    _escalate(
        s,
        at,
        "agent_failed",
        agent,
        f"{agent} falhou: {error}",
        pending=pending,
        now=f"Falhou: {error}"[:160],
    )


def _undo_round(s: TaskState, agent: AgentName) -> None:
    """The round did not happen: give the counter back so a retry reuses the number."""
    if agent == "developer":
        s.dev_round = max(0, s.dev_round - 1)
    elif agent == "reviewer":
        s.review_round = max(0, s.review_round - 1)


# ============================================================ helpers for texts


def _short_test_name(test: str) -> str:
    return test.rsplit("::", 1)[-1]


def _fix_text(result: TestResult) -> str:
    names = [_short_test_name(f.test) for f in result.failures[:3]]
    return "Corrigindo: " + (", ".join(names) if names else "falhas nos testes")


def _review_text(review: ReviewResult) -> str:
    items = [c.text for c in review.comments if not c.resolved][:2]
    return "Aplicando review: " + ("; ".join(items) if items else "comentários do Reviewer")


def _last_failed_test(s: TaskState) -> TestResult | None:
    for t in reversed(s.test_runs):
        if not t.ok:
            return t
    return None


def _failure_summary(s: TaskState) -> str:
    lines: list[str] = []
    if s.escalation is not None:
        lines.append(s.escalation.reason)
    t = _last_failed_test(s)
    if t is not None:
        lines.append(f"Testes ({t.command}): {t.passed}/{t.total} passaram. Falhas recentes:")
        lines.extend(f"- {f.test}: {f.message}" for f in t.failures[:5])
    if s.review is not None and s.review.verdict == "changes_requested":
        lines.append("Comentários do review pendentes:")
        lines.extend(f"- [{c.severity}] {c.file}: {c.text}" for c in s.review.comments if not c.resolved)
    return "\n".join(lines)


def _fallback_commit_message(s: TaskState) -> str:
    title = s.title[:1].lower() + s.title[1:]
    return f"feat: {title}"


# ============================================================ commands


def _on_command(state: TaskState | None, ev: CommandReceived) -> tuple[TaskState | None, list[Effect]]:
    cmd = ev.command
    if isinstance(cmd, StartTask):
        return _start(state, cmd, ev.start, ev.at)
    if state is None or state.terminal:
        return _reject(state, ERR_NO_TASK)

    s = _copy(state)
    match cmd:
        case AnswerInterview():
            return _answer(state, s, cmd, ev.at)
        case ApprovePlan():
            return _approve(state, s, ev.at)
        case AdjustPlan():
            return _adjust(state, s, cmd, ev.at)
        case EscalationAction():
            return _escalation_action(state, s, cmd, ev.at)
        case CancelTask():
            return _cancel(s, ev.at)
        case _:  # pragma: no cover - StartTask handled above
            return _reject(state, ERR_WRONG_PHASE)


def _start(
    state: TaskState | None, cmd: StartTask, params: StartParams | None, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    if state is not None and not state.terminal:
        return _reject(state, ERR_ACTIVE_TASK)
    title = cmd.title.strip()
    if not title:
        return _reject(state, ERR_TITLE_REQUIRED)
    if params is None:
        return _reject(state, ERR_UNKNOWN_REPO)

    repo = params.repo
    description = cmd.description.strip()
    s = TaskState(
        task_id=params.task_id,
        title=title,
        description=description,
        repo=repo,
        limits=params.limits,
        phase="interviewing",
        spec=TaskSpec(title=title, description=description, repo=repo.name),
        boot="create_workspace",
        started_at=at,
    )
    _set(s, "manual", "done", title, at)
    return _commit(s, CreateWorkspace(s.task_id, repo.name))


def _answer(
    state: TaskState, s: TaskState, cmd: AnswerInterview, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    pending = s.pending_questions
    if s.phase != "interviewing" or not pending:
        return _reject(state, ERR_WRONG_PHASE)
    if len(cmd.answers) != len(pending):
        return _reject(state, ERR_ANSWERS_MISMATCH)
    for q, raw in zip(pending, cmd.answers, strict=True):
        text = (raw or "").strip()
        accepted = not text or text == q.recommendation
        answer = q.recommendation if accepted else text
        s.interview_turns.append(
            InterviewTurn(
                question=q, answer=answer, accepted_recommendation=accepted, round=s.interview_round
            )
        )
        s.decisions.append(f"{q.topic}: {answer}")
    s.pending_questions = []
    _log(s, "interviewer", f"Rodada {s.interview_round} respondida ({len(pending)} decisões)", at)
    effects = _advance(s, at, "interviewer", edge=None, now="Processando suas respostas")
    return _commit(s, *effects)


def _approve(state: TaskState, s: TaskState, at: datetime) -> tuple[TaskState | None, list[Effect]]:
    if s.phase != "awaiting_approval" or s.plan is None:
        return _reject(state, ERR_WRONG_PHASE)
    _set(s, "approval", "done", "Plano aprovado", at)
    effects = _advance(s, at, "developer", edge="ap-dv", now="Implementando o plano")
    return _commit(s, *effects)


def _adjust(
    state: TaskState, s: TaskState, cmd: AdjustPlan, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    if s.phase != "awaiting_approval":
        return _reject(state, ERR_WRONG_PHASE)
    text = cmd.text.strip()
    if not text:
        return _reject(state, ERR_TEXT_REQUIRED)
    _set(s, "approval", "idle", f"Ajuste pedido: {text}", at)
    _settle_edge(s)  # pl-ap stays "on" (mockup)
    effects = _advance(
        s,
        at,
        "planner",
        edge=None,
        feedback=Feedback(kind="plan_adjust", text=text),
        now=f'Revendo plano: "{text}"',
    )
    return _commit(s, *effects)


def _cancel(s: TaskState, at: datetime) -> tuple[TaskState | None, list[Effect]]:
    agent = s.current_agent
    _settle_edge(s)
    for key, st in s.stages.items():
        if st.status in ("active", "waiting"):
            _set(s, key, "error", "Cancelada pelo usuário", at)
    s.phase = "cancelled"
    s.ended_at = at
    s.boot = None
    s.current_job_id = None
    s.current_agent = None
    s.inflight = None
    return _commit(s, CancelJobs(s.task_id, agent))


# ---------------------------------------------------------------- escalation actions


def _escalation_action(
    state: TaskState, s: TaskState, cmd: EscalationAction, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    esc = s.escalation
    if s.phase != "escalated" or esc is None:
        return _reject(state, ERR_WRONG_PHASE)
    text = (cmd.text or "").strip()
    if cmd.action == "instruct" and not text:
        return _reject(state, ERR_TEXT_REQUIRED)
    if cmd.action == "replan" and esc.stage == "interviewer":
        return _reject(state, ERR_REPLAN_UNAVAILABLE)
    if budget.exhausted(s.cost_usd, s.limits.budget_usd) and cmd.action != "more_attempts":
        return _reject(state, ERR_BUDGET)

    if cmd.action == "replan":
        return _commit(s, *_replan(s, at))

    if cmd.action == "more_attempts":
        # a job stopped by its cap leaves the task budget nearly (not fully) spent: boost it anyway
        capped = esc.kind == "budget" or JOB_BUDGET_EXCEEDED in esc.reason
        if capped or budget.exhausted(s.cost_usd, s.limits.budget_usd):
            s.limits.budget_usd = budget.boosted(s.cost_usd, s.limits.budget_usd)
        return _commit(s, *_more_attempts(s, esc, at))

    return _commit(s, *_instruct(s, esc, text, at))


def _replan(s: TaskState, at: datetime) -> list[Effect]:
    summary = _failure_summary(s)
    s.test_attempt = 0
    s.review_round = 0
    for agent in ("developer", "tester", "reviewer"):
        s.sessions.pop(agent, None)
    for key in ("approval", "developer", "tester", "reviewer"):
        s.stages[key].status = "idle"
    text = "A abordagem atual não convergiu. Revise o plano considerando:\n" + summary
    return _advance(
        s,
        at,
        "planner",
        edge=None,
        feedback=Feedback(kind="plan_adjust", text=text),
        now="Revendo plano: rever abordagem",
    )


def _more_attempts(s: TaskState, esc: EscalationState, at: datetime) -> list[Effect]:
    match esc.kind:
        case "test_limit":
            s.limits.max_test_attempts += 2
            _log(s, "tester", f"Limite aumentado pra {s.limits.max_test_attempts}", at)
            s.stages["tester"].status = "idle"
            last = _last_failed_test(s)
            fb = Feedback(kind="test_failures", test=last) if last else None
            return _advance(
                s, at, "developer", edge="ts-dv", feedback=fb, now="Nova tentativa com +2 iterações"
            )
        case "review_limit":
            s.limits.max_review_rounds += 2
            _log(s, "reviewer", f"Limite aumentado pra {s.limits.max_review_rounds}", at)
            s.stages["reviewer"].status = "idle"
            fb = Feedback(kind="review_comments", review=s.review) if s.review else None
            return _advance(
                s, at, "developer", edge="rv-dv", feedback=fb, now="Nova tentativa com +2 rodadas de review"
            )
        case "budget" | "agent_failed":
            return _resume(s, esc, at)


def _resume(s: TaskState, esc: EscalationState, at: datetime) -> list[Effect]:
    """Re-run the job that could not run (budget) or died (agent failure)."""
    p = esc.pending
    if p is None:  # defensive: should not happen
        return _replan(s, at)
    s.stages[esc.stage].status = "idle"
    return _advance(s, at, p.agent, edge=p.edge, feedback=p.feedback, now=p.now)


def _instruct(s: TaskState, esc: EscalationState, text: str, at: datetime) -> list[Effect]:
    quoted = f'Seguindo sua instrução: "{text}"'
    if esc.kind == "agent_failed" and esc.stage in ("planner", "interviewer"):
        # nothing to implement yet: re-run the same agent, planner gets the instruction
        p = esc.pending
        s.stages[esc.stage].status = "idle"
        if esc.stage == "planner":
            return _advance(
                s,
                at,
                "planner",
                edge=None,
                feedback=Feedback(kind="plan_adjust", text=text),
                now=f'Revendo plano: "{text}"',
            )
        return _advance(
            s, at, "interviewer", edge=None, feedback=p.feedback if p else None, now=p.now if p else None
        )

    # developer takes over, for every other escalation
    if esc.kind == "test_limit":
        s.test_attempt = 0  # a human instruction buys a fresh cycle
    elif esc.kind == "review_limit":
        s.review_round = 0
    edge = _INSTRUCT_EDGE.get(esc.stage)
    _log(s, esc.stage, "Instrução enviada pro Developer", at)
    s.stages[esc.stage].status = "idle"
    fb = Feedback(
        kind="human_instruction",
        text=text,
        test=_last_failed_test(s) if esc.stage == "tester" else None,
        review=s.review if esc.stage == "reviewer" and s.review is not None else None,
    )
    return _advance(s, at, "developer", edge=edge, feedback=fb, now=quoted)


# ============================================================ io events (workspace / report)


def _on_io_event(
    state: TaskState | None,
    ev: WorkspaceReady | WorkspaceFailed | ReportBuilt,
) -> tuple[TaskState | None, list[Effect]]:
    if state is None or state.terminal or state.task_id != ev.task_id:
        return _stale(state, ev.task_id, type(ev).__name__)
    s = _copy(state)
    match ev:
        case WorkspaceFailed():
            if s.boot != "create_workspace":
                return _stale(state, ev.task_id, "WorkspaceFailed")
            return _fail_boot(s, "manual", f"Falha ao preparar o worktree: {ev.error}", ev.at)
        case WorkspaceReady():
            if s.boot != "create_workspace":
                return _stale(state, ev.task_id, "WorkspaceReady")
            s.boot = None
            s.workspace_path = ev.path
            s.branch = ev.branch
            effects = _advance(s, ev.at, "interviewer", edge="ma-iv", now="Preparando a primeira pergunta")
            return _commit(s, *effects)
        case ReportBuilt():
            if s.boot != "build_report" or s.review is None:
                return _stale(state, ev.task_id, "ReportBuilt")
            s.boot = None
            s.edges["rv-dn"] = "on"
            s.active_edge = None
            if ev.error:
                _log(s, "done", f"Relatório de arquivos indisponível: {ev.error}", ev.at)
            _set(s, "done", "done", "Pronto pra você revisar e commitar", ev.at)
            s.phase = "done"
            s.ended_at = ev.at
            s.final = FinalReport(
                branch=s.branch or f"crew/{s.task_id}",
                worktree_path=s.workspace_path or "",
                files=ev.files,
                commit_message=s.review.commit_message or _fallback_commit_message(s),
                duration_s=round((ev.at - s.started_at).total_seconds(), 3),
                cost_usd=round(s.cost_usd, 6),
            )
            return _commit(s)


def _fail_boot(
    s: TaskState, key: StageKey, message: str, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    _settle_edge(s)
    s.boot = None
    s.phase = "failed"
    s.ended_at = at
    _set(s, key, "error", message, at)
    return _commit(s)


# ============================================================ agent events


def _is_current(
    state: TaskState | None, ev: AgentResult | AgentFailed | AgentProgressed | JobTimedOut
) -> bool:
    if state is None or state.terminal or state.task_id != ev.task_id:
        return False
    job_id = ev.evt.job_id if not isinstance(ev, JobTimedOut) else ev.job_id
    return state.current_job_id is not None and state.current_job_id == job_id


def _on_agent_event(
    state: TaskState | None, ev: AgentResult | AgentFailed | AgentProgressed | JobTimedOut
) -> tuple[TaskState | None, list[Effect]]:
    if not _is_current(state, ev):
        if isinstance(ev, AgentProgressed):
            return state, []  # progress of a dead job: silently dropped
        job_id = ev.job_id if isinstance(ev, JobTimedOut) else ev.evt.job_id
        return state, [LogStale(ev.task_id, type(ev).__name__, job_id)]
    assert state is not None
    s = _copy(state)
    match ev:
        case AgentProgressed():
            _log(s, ev.evt.agent, ev.evt.text, ev.at)
            return s, []
        case AgentFailed():
            if ev.evt.retryable:  # the bus will redeliver; just surface it
                _log(s, ev.evt.agent, f"Tentando de novo: {ev.evt.error}"[:160], ev.at)
                return s, []
            if ev.evt.error == JOB_BUDGET_EXCEEDED:  # the job hit its cap = what was left of the task
                _undo_round(s, ev.evt.agent)
                reason = f"{ev.evt.agent} parou no teto do job: orçamento restante da tarefa acabou"
                _escalate(s, ev.at, "budget", ev.evt.agent, reason, pending=s.inflight, now=_BUDGET_NOW)
                return _commit(s)
            _fail_job(s, ev.at, ev.evt.agent, ev.evt.error, s.inflight)
            return _commit(s)
        case JobTimedOut():
            agent = s.current_agent
            assert agent is not None
            minutes = s.limits.job_timeout_s / 60
            _fail_job(s, ev.at, agent, f"sem resposta após {minutes:g} min", s.inflight)
            return _commit(s, CancelJobs(s.task_id, agent))
        case AgentResult():
            return _on_result(s, ev)


def _bad_output(
    s: TaskState, ev: AgentResult, expected: str, pending: PendingJob | None
) -> tuple[TaskState | None, list[Effect]]:
    got = type(ev.evt.output).__name__
    _fail_job(s, ev.at, ev.evt.agent, f"saída inesperada ({got}), esperava {expected}", pending)
    return _commit(s)


def _on_result(s: TaskState, ev: AgentResult) -> tuple[TaskState | None, list[Effect]]:
    evt = ev.evt
    agent = evt.agent
    out = evt.output
    pending = s.inflight
    s.cost_usd += evt.cost_usd  # money is spent even if the output is unusable
    if evt.session_id:
        s.sessions[agent] = evt.session_id
    s.current_job_id = None
    s.current_agent = None
    s.inflight = None

    match agent:
        case "interviewer":
            if not isinstance(out, InterviewResult):
                return _bad_output(s, ev, "InterviewResult", pending)
            return _interviewer_result(s, out, ev.at, pending)
        case "planner":
            if not isinstance(out, Plan):
                return _bad_output(s, ev, "Plan", pending)
            return _planner_result(s, out, ev.at)
        case "developer":
            if not isinstance(out, DevResult):
                return _bad_output(s, ev, "DevResult", pending)
            return _developer_result(s, out, ev.at)
        case "tester":
            if not isinstance(out, TestResult):
                return _bad_output(s, ev, "TestResult", pending)
            return _tester_result(s, out, ev.at)
        case "reviewer":
            if not isinstance(out, ReviewResult):
                return _bad_output(s, ev, "ReviewResult", pending)
            return _reviewer_result(s, out, ev.at)


def _interviewer_result(
    s: TaskState, out: InterviewResult, at: datetime, pending: PendingJob | None
) -> tuple[TaskState | None, list[Effect]]:
    if out.kind == "question" and out.questions:
        s.pending_questions = list(out.questions)
        s.interview_round += 1
        s.phase = "interviewing"
        topics = ", ".join(q.topic for q in out.questions)
        _log(s, "interviewer", f"Rodada {s.interview_round}: {topics}", at)
        _set(s, "interviewer", "waiting", _WAITING_FOR_YOU, at)
        return _commit(s)
    if out.kind == "done" and out.spec is not None:
        s.spec = out.spec.model_copy(
            update={
                "repo": s.repo.name,
                "decisions": out.spec.decisions or list(s.decisions),
            }
        )
        s.pending_questions = []
        _set(s, "interviewer", "done", f"Spec fechada · {len(s.decisions)} decisões", at)
        effects = _advance(s, at, "planner", edge="iv-pl")
        return _commit(s, *effects)
    _fail_job(s, at, "interviewer", f"resultado incompleto (kind={out.kind})", pending)
    return _commit(s)


def _planner_result(s: TaskState, plan: Plan, at: datetime) -> tuple[TaskState | None, list[Effect]]:
    s.plan = plan
    _set(s, "planner", "done", f"Plano pronto · {len(plan.steps)} passos, {len(plan.files)} arquivos", at)
    s.phase = "awaiting_approval"
    _go(s, "pl-ap", "approval", "waiting")
    _log(s, "approval", "Aguardando você — expanda pra revisar o plano", at)
    return _commit(s)


def _developer_result(s: TaskState, dev: DevResult, at: datetime) -> tuple[TaskState | None, list[Effect]]:
    s.dev_rounds.append(dev.model_copy(update={"round": s.dev_round}))
    _set(s, "developer", "done", f"Rodada {s.dev_round} salva no repo local · sem commit", at)
    now = "Escrevendo testes" if not s.test_runs else "Rodando a suíte de novo"
    effects = _advance(s, at, "tester", edge="dv-ts", now=now)
    return _commit(s, *effects)


def _tester_result(s: TaskState, res: TestResult, at: datetime) -> tuple[TaskState | None, list[Effect]]:
    s.test_runs.append(res)
    if res.ok:
        s.test_attempt = 0
        cov = f" · cobertura {round(res.coverage * 100)}%" if res.coverage is not None else ""
        _set(s, "tester", "done", f"PASSOU · {res.passed}/{res.total}{cov}", at)
        effects = _advance(s, at, "reviewer", edge="ts-rv")
        return _commit(s, *effects)

    s.test_attempt += 1
    n, mx = s.test_attempt, s.limits.max_test_attempts
    _set(s, "tester", "error", f"FALHOU · {res.passed}/{res.total} · tentativa {n}/{mx}", at)
    if n >= mx:
        _escalate(
            s,
            at,
            "test_limit",
            "tester",
            f"{n} falhas consecutivas de teste",
            now=f"Limite {mx}/{mx} atingido — expanda pra decidir",
        )
        return _commit(s)
    s.stages["tester"].status = "idle"
    effects = _advance(
        s,
        at,
        "developer",
        edge="ts-dv",
        feedback=Feedback(kind="test_failures", test=res),
        now=_fix_text(res),
    )
    return _commit(s, *effects)


def _reviewer_result(s: TaskState, res: ReviewResult, at: datetime) -> tuple[TaskState | None, list[Effect]]:
    has_major = any(c.severity == "major" and not c.resolved for c in res.comments)
    approved = res.verdict == "approved" and not has_major

    if approved:
        earlier = [c.model_copy(update={"resolved": True}) for r in s.reviews for c in r.comments]
        s.reviews.append(res)
        s.review = res.model_copy(
            update={
                "verdict": "approved",
                "comments": [*earlier, *res.comments],
                "commit_message": res.commit_message or _fallback_commit_message(s),
            }
        )
        _set(s, "reviewer", "done", "APROVADO · comentários resolvidos", at)
        _go(s, "rv-dn", "done")
        _log(s, "done", "Gerando relatório final", at)
        s.boot = "build_report"
        return _commit(s, BuildFinalReport(s.task_id, s.repo.name, s.workspace_path or ""))

    corrected = (
        res if res.verdict == "changes_requested" else res.model_copy(update={"verdict": "changes_requested"})
    )
    s.reviews.append(corrected)
    s.review = corrected
    majors = sum(1 for c in corrected.comments if c.severity == "major")
    minors = sum(1 for c in corrected.comments if c.severity == "minor")
    nits = sum(1 for c in corrected.comments if c.severity == "nit")
    label = f"CHANGES REQUESTED · {majors} major, {minors} minor" + (f", {nits} nit" if nits else "")
    _set(s, "reviewer", "error", label, at)
    n, mx = s.review_round, s.limits.max_review_rounds
    if n >= mx:
        _escalate(
            s,
            at,
            "review_limit",
            "reviewer",
            f"{n} rodadas de review sem aprovação",
            now=f"Limite {mx}/{mx} atingido — expanda pra decidir",
        )
        return _commit(s)
    s.stages["reviewer"].status = "idle"
    effects = _advance(
        s,
        at,
        "developer",
        edge="rv-dv",
        feedback=Feedback(kind="review_comments", review=corrected),
        now=_review_text(corrected),
    )
    return _commit(s, *effects)

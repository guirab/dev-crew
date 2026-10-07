"""The task state machine. PURE: ``decide(state, event) -> (state, effects)``, zero I/O, no clock, no LLM.

Conventions
- ``state`` is never mutated: ``decide`` works on a deep copy and returns it.
- ``state is None`` means "no task yet". A terminal task is replaced by the next ``start_task``.
- Stage/edge bookkeeping mirrors ``mockup/index.html`` (``go``/``finish``/``log``) so the UI is a pure render.
- A command that cannot be applied yields ``[Reject(error)]`` with the *same* state object.

Pipelines
- A single execution runs Developer → Tester → Reviewer on the task itself (``TaskState``).
- A split plan (D53) runs the same pipeline once per epic, on a ``LaneState`` with its own worktree, in
  parallel when the dependency graph allows. An approved epic is committed and merged into the task
  branch, one merge at a time (D54); a conflicting merge gets an integration lane that runs the pipeline
  in the task worktree (D55). The pipeline functions take the pipe (``p``) they act on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

from .. import plan_doc, plan_graph
from ..contracts import (
    AdjustPlan,
    AgentJob,
    AgentName,
    AnswerInterview,
    ApprovePlan,
    CancelTask,
    CreateProject,
    DevResult,
    EdgeKey,
    EpicCommit,
    EscalationAction,
    Feedback,
    FinalReport,
    FinishTask,
    InterviewResult,
    InterviewTurn,
    LogLine,
    Plan,
    ResumeAfterLimit,
    ReviewResult,
    RunEpics,
    StageKey,
    StageStatus,
    StartTask,
    TaskPhase,
    TaskSpec,
    TestResult,
    UsageLimit,
)
from .effects import (
    BuildFinalReport,
    CancelJobs,
    CreateEpicWorkspace,
    CreateWorkspace,
    DispatchJob,
    Effect,
    FinishMerge,
    LogStale,
    MergeEpic,
    Persist,
    PublishView,
    Reject,
    RemoveEpicWorkspace,
    WritePlanDoc,
)
from .events import (
    AgentFailed,
    AgentProgressed,
    AgentResult,
    CommandReceived,
    EpicMerged,
    EpicWorkspaceFailed,
    EpicWorkspaceReady,
    Event,
    ReportBuilt,
    StartParams,
    WorkspaceFailed,
    WorkspaceReady,
)
from .state import MAX_STAGE_LOGS, EscalationKind, EscalationState, LaneState, PendingJob, TaskState

# --- rejection messages (pt-BR, shown to the user) -------------------------------------------------
# Conflicts (state does not allow the command) map to HTTP 409; the rest are validation errors (422).
ERR_ACTIVE_TASK: Final = "já existe tarefa ativa"
ERR_NO_TASK: Final = "nenhuma tarefa ativa"
ERR_WRONG_PHASE: Final = "comando indisponível na fase atual"
CONFLICT_ERRORS: Final = frozenset({ERR_ACTIVE_TASK, ERR_NO_TASK, ERR_WRONG_PHASE})

ERR_UNKNOWN_REPO: Final = "repositório desconhecido"
ERR_TITLE_REQUIRED: Final = "título é obrigatório"
ERR_TEXT_REQUIRED: Final = "texto obrigatório"
ERR_ANSWERS_MISMATCH: Final = "responda todas as perguntas da rodada (uma resposta por pergunta)"
ERR_REPLAN_UNAVAILABLE: Final = "replanejar não se aplica: a spec ainda não foi fechada"
ERR_UNKNOWN_EPIC: Final = "épico desconhecido"
ERR_NO_EPICS: Final = "escolha ao menos um épico"
ERR_EPIC_REQUIRED: Final = "informe qual épico (epic_id): há mais de um escalado"
ERR_REPLAN_LANE: Final = "replanejar não se aplica a um épico: use instruir ou +2 tentativas"
ERR_PROJECT_VIA_SERVICE: Final = "create_project é tratado pelo serviço, não pela máquina"

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
_ACTIVE_LANE: Final = frozenset({"preparing", "running", "merging"})

Pipe = TaskState | LaneState


# ============================================================ public API


def decide(state: TaskState | None, event: Event) -> tuple[TaskState | None, list[Effect]]:
    """Apply ``event``. Returns the new state (same object if nothing changed) and the effects to run."""
    match event:
        case CommandReceived():
            return _on_command(state, event)
        case AgentResult() | AgentFailed() | AgentProgressed():
            return _on_agent_event(state, event)
        case WorkspaceReady() | WorkspaceFailed() | ReportBuilt():
            return _on_io_event(state, event)
        case EpicWorkspaceReady() | EpicWorkspaceFailed() | EpicMerged():
            return _on_epic_event(state, event)


def recovery_effects(state: TaskState) -> list[Effect]:
    """Effects to re-issue after a restart for non-agent steps that were in flight."""
    if state.terminal:
        return []
    effects: list[Effect] = []
    match state.boot:
        case "create_workspace":
            effects.append(CreateWorkspace(state.task_id, state.repo.name))
        case "build_report" if state.workspace_path:
            effects.append(_final_report_effect(state))
    if state.workspace_path:
        for lane in state.lanes.values():
            if lane.status == "preparing":
                effects.append(
                    CreateEpicWorkspace(state.task_id, state.repo.name, lane.id, state.workspace_path)
                )
        if state.merging is not None:
            integration = state.lanes.get(_integration_id(state.merging))
            if integration is None or integration.status == "merged":
                effects.append(_merge_effect(state, state.lanes[state.merging]))
            elif integration.status == "merging":
                effects.append(_finish_merge_effect(state, state.merging))
    return effects


# ============================================================ small mutators (operate on a COPY)


def _log(p: Pipe, key: StageKey, text: str, at: datetime) -> None:
    st = p.stages[key]
    st.now = text
    st.logs = [*st.logs, LogLine(ts=at, text=text)][-MAX_STAGE_LOGS:]


def _set(p: Pipe, key: StageKey, status: StageStatus, text: str | None, at: datetime) -> None:
    p.stages[key].status = status
    if text is not None:
        _log(p, key, text, at)


def _settle_edge(p: Pipe) -> None:
    if p.active_edge is not None:
        p.edges[p.active_edge] = "on"
        p.active_edge = None


def _go(p: Pipe, edge: EdgeKey, key: StageKey, status: StageStatus = "active") -> None:
    if p.active_edge is not None:
        p.edges[p.active_edge] = "on"
    p.edges[edge] = "active"
    p.active_edge = edge
    p.stages[key].status = status


def _commit(s: TaskState, *effects: Effect) -> tuple[TaskState, list[Effect]]:
    return s, [Persist(), *effects, PublishView()]


def _copy(state: TaskState) -> TaskState:
    return state.model_copy(deep=True)


def _reject(state: TaskState | None, error: str) -> tuple[TaskState | None, list[Effect]]:
    return state, [Reject(error)]


def _stale(state: TaskState | None, task_id: str, what: str) -> tuple[TaskState | None, list[Effect]]:
    return state, [LogStale(task_id, what)]


def _lane(p: Pipe) -> LaneState | None:
    return p if isinstance(p, LaneState) else None


# ============================================================ dispatch / escalate


def _make_job(s: TaskState, p: Pipe, agent: AgentName, feedback: Feedback | None) -> AgentJob:
    lane = _lane(p)
    job_id = uuid5(NAMESPACE_URL, f"crew:{s.task_id}:{s.started_at.isoformat()}:{s.job_seq}")
    return AgentJob(
        job_id=job_id,
        task_id=s.task_id,
        agent=agent,
        attempt=p.attempts.get(agent, 0),
        repo=s.repo,
        spec=s.spec,
        plan=None if agent == "interviewer" else s.plan,
        feedback=feedback,
        interview_history=list(s.interview_turns) if agent in ("interviewer", "planner") else [],
        workspace_path=lane.workspace_path if lane else s.workspace_path,
        resume_session_id=p.sessions.get(agent),
        epic_id=lane.id if lane else None,
    )


def _advance(
    s: TaskState,
    at: datetime,
    agent: AgentName,
    *,
    edge: EdgeKey | None,
    feedback: Feedback | None = None,
    now: str | None = None,
    p: Pipe | None = None,
) -> list[Effect]:
    """Hand the pipe (the task, or a lane) to ``agent``. Returns the effects (the dispatch)."""
    pipe: Pipe = p if p is not None else s
    lane = _lane(pipe)
    if edge is not None:
        _go(pipe, edge, agent)
    _set(pipe, agent, "active", now or _DEFAULT_NOW[agent], at)
    pipe.escalation = None
    if agent == "developer":
        pipe.dev_round += 1
    elif agent == "reviewer":
        pipe.review_round += 1
    s.job_seq += 1
    pipe.attempts[agent] = pipe.attempts.get(agent, 0) + 1
    pipe.inflight = PendingJob(agent=agent, feedback=feedback, edge=None, now=now)
    job = _make_job(s, pipe, agent, feedback)
    pipe.current_job_id = job.job_id
    pipe.current_agent = agent
    if lane is not None:
        lane.status = "running"
        s.phase = _split_phase(s)
    else:
        s.phase = _PHASE[agent]
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
    p: Pipe | None = None,
) -> None:
    pipe: Pipe = p if p is not None else s
    _settle_edge(pipe)
    pipe.current_job_id = None
    pipe.current_agent = None
    pipe.inflight = None
    pipe.escalation = EscalationState(kind=kind, stage=stage, reason=reason, pending=pending)
    _set(pipe, stage, "error", now or reason, at)
    lane = _lane(pipe)
    if lane is not None:
        lane.status = "escalated"
        s.phase = _split_phase(s)
    else:
        s.phase = "escalated"


def _fail_job(
    s: TaskState,
    at: datetime,
    agent: AgentName,
    error: str,
    pending: PendingJob | None,
    p: Pipe | None = None,
) -> None:
    """The in-flight job of ``agent`` died: escalate keeping the job so it can be retried."""
    pipe: Pipe = p if p is not None else s
    _undo_round(pipe, agent)
    _escalate(
        s,
        at,
        "agent_failed",
        agent,
        f"{agent} falhou: {error}",
        pending=pending,
        now=f"Falhou: {error}"[:160],
        p=pipe,
    )


def _undo_round(p: Pipe, agent: AgentName) -> None:
    """The round did not happen: give the counter back so a retry reuses the number."""
    if agent == "developer":
        p.dev_round = max(0, p.dev_round - 1)
    elif agent == "reviewer":
        p.review_round = max(0, p.review_round - 1)


# ============================================================ helpers for texts


def _short_test_name(test: str) -> str:
    return test.rsplit("::", 1)[-1]


def _fix_text(result: TestResult) -> str:
    names = [_short_test_name(f.test) for f in result.failures[:3]]
    return "Corrigindo: " + (", ".join(names) if names else "falhas nos testes")


def _review_text(review: ReviewResult) -> str:
    items = [c.text for c in review.comments if not c.resolved][:2]
    return "Aplicando review: " + ("; ".join(items) if items else "comentários do Reviewer")


def _last_failed_test(p: Pipe) -> TestResult | None:
    for t in reversed(p.test_runs):
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


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _fallback_commit_message(s: TaskState) -> str:
    return f"feat: {_lower_first(s.title)}"


def _epic_commit_fallback(lane: LaneState) -> str:
    return f"feat({lane.id}): {_lower_first(lane.title)}"


def _merge_message(s: TaskState, epic_id: str) -> str:
    lane = s.lanes[epic_id]
    return f"merge: {epic_id} · {lane.title} ({s.task_id})"


# ============================================================ commands


def _on_command(state: TaskState | None, ev: CommandReceived) -> tuple[TaskState | None, list[Effect]]:
    cmd = ev.command
    if isinstance(cmd, StartTask):
        return _start(state, cmd, ev.start, ev.at)
    if isinstance(cmd, CreateProject):  # the service turns it into a start_task once the repo exists
        return _reject(state, ERR_PROJECT_VIA_SERVICE)
    if state is None or state.terminal:
        return _reject(state, ERR_NO_TASK)

    s = _copy(state)
    match cmd:
        case AnswerInterview():
            return _answer(state, s, cmd, ev.at)
        case ApprovePlan():
            return _approve(state, s, cmd, ev.at)
        case AdjustPlan():
            return _adjust(state, s, cmd, ev.at)
        case EscalationAction():
            return _escalation_action(state, s, cmd, ev.at)
        case CancelTask():
            return _cancel(s, ev.at)
        case ResumeAfterLimit():
            return _resume_after_limit(state, s, ev.at)
        case RunEpics():
            return _run_epics(state, s, cmd, ev.at)
        case FinishTask():
            return _finish_task(state, s, ev.at)
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


def _plan_doc_effect(s: TaskState, *, commit: bool) -> WritePlanDoc:
    assert s.plan is not None and s.workspace_path is not None
    return WritePlanDoc(
        s.task_id, s.repo.name, s.workspace_path, _render_plan_doc(s, updated=None), commit=commit
    )


def _render_plan_doc(s: TaskState, *, updated: datetime | None) -> str:
    assert s.plan is not None
    return plan_doc.render(
        s.task_id,
        s.title,
        s.plan,
        estimate=s.estimate,
        status={lane.id: lane.status for lane in s.lanes.values() if lane.kind == "epic"},
        commits={lane.id: lane.commit_sha for lane in s.lanes.values() if lane.commit_sha},
        updated=updated,
    )


def _approve(
    state: TaskState, s: TaskState, cmd: ApprovePlan, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    if s.phase != "awaiting_approval" or s.plan is None:
        return _reject(state, ERR_WRONG_PHASE)
    plan = s.plan
    if plan.execution == "epics" and plan.epics:
        return _approve_split(state, s, plan, cmd.epics, at)
    _set(s, "approval", "done", "Plano aprovado", at)
    doc = [_plan_doc_effect(s, commit=False)] if s.workspace_path else []
    effects = _advance(s, at, "developer", edge="ap-dv", now="Implementando o plano")
    return _commit(s, *doc, *effects)


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
    for lane in s.lanes.values():
        if lane.status in _ACTIVE_LANE or lane.status in ("waiting", "escalated", "limited"):
            _settle_edge(lane)
            for key, st in lane.stages.items():
                if st.status in ("active", "waiting"):
                    _set(lane, key, "error", "Cancelada pelo usuário", at)
            lane.status = "failed"
            lane.current_job_id = None
            lane.current_agent = None
            lane.inflight = None
    s.phase = "cancelled"
    s.ended_at = at
    s.boot = None
    s.current_job_id = None
    s.current_agent = None
    s.inflight = None
    # a split plan may have several agents queued: cancel all of them
    return _commit(s, CancelJobs(s.task_id, None if s.split else agent))


# ---------------------------------------------------------------- escalation actions


def _escalated_pipe(s: TaskState, epic_id: str | None) -> Pipe | str:
    """The pipe the escalation action is for, or a rejection message."""
    if not s.split:
        if s.phase != "escalated" or s.escalation is None:
            return ERR_WRONG_PHASE
        return s
    escalated = [lane for lane in s.lanes.values() if lane.status == "escalated"]
    if epic_id is not None:
        lane = s.lanes.get(epic_id)
        if lane is None:
            return ERR_UNKNOWN_EPIC
        return lane if lane.status == "escalated" and lane.escalation is not None else ERR_WRONG_PHASE
    if len(escalated) == 1:
        return escalated[0]
    return ERR_EPIC_REQUIRED if escalated else ERR_WRONG_PHASE


def _escalation_action(
    state: TaskState, s: TaskState, cmd: EscalationAction, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    found = _escalated_pipe(s, cmd.epic_id)
    if isinstance(found, str):
        return _reject(state, found)
    p = found
    esc = p.escalation
    assert esc is not None
    lane = _lane(p)
    text = (cmd.text or "").strip()
    if cmd.action == "instruct" and not text:
        return _reject(state, ERR_TEXT_REQUIRED)
    if cmd.action == "replan" and lane is not None:
        return _reject(state, ERR_REPLAN_LANE)
    if cmd.action == "replan" and esc.stage == "interviewer":
        return _reject(state, ERR_REPLAN_UNAVAILABLE)

    if lane is not None and esc.kind in ("workspace", "merge"):
        return _commit(s, *_retry_lane_io(s, lane, at))
    if cmd.action == "replan":
        return _commit(s, *_replan(s, at))
    if cmd.action == "more_attempts":
        return _commit(s, *_more_attempts(s, p, esc, at))
    return _commit(s, *_instruct(s, p, esc, text, at))


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


def _more_attempts(s: TaskState, p: Pipe, esc: EscalationState, at: datetime) -> list[Effect]:
    match esc.kind:
        case "test_limit":
            p.limits.max_test_attempts += 2
            _log(p, "tester", f"Limite aumentado pra {p.limits.max_test_attempts}", at)
            p.stages["tester"].status = "idle"
            last = _last_failed_test(p)
            fb = Feedback(kind="test_failures", test=last) if last else None
            return _advance(
                s, at, "developer", edge="ts-dv", feedback=fb, now="Nova tentativa com +2 iterações", p=p
            )
        case "review_limit":
            p.limits.max_review_rounds += 2
            _log(p, "reviewer", f"Limite aumentado pra {p.limits.max_review_rounds}", at)
            p.stages["reviewer"].status = "idle"
            fb = Feedback(kind="review_comments", review=p.review) if p.review else None
            return _advance(
                s,
                at,
                "developer",
                edge="rv-dv",
                feedback=fb,
                now="Nova tentativa com +2 rodadas de review",
                p=p,
            )
        case _:
            return _resume(s, p, esc, at)


def _resume(s: TaskState, p: Pipe, esc: EscalationState, at: datetime) -> list[Effect]:
    """Re-run the job that died (agent failure)."""
    pending = esc.pending
    if pending is None:  # defensive: should not happen
        return _replan(s, at) if _lane(p) is None else _advance(s, at, "developer", edge=None, p=p)
    p.stages[esc.stage].status = "idle"
    return _advance(s, at, pending.agent, edge=pending.edge, feedback=pending.feedback, now=pending.now, p=p)


def _instruct(s: TaskState, p: Pipe, esc: EscalationState, text: str, at: datetime) -> list[Effect]:
    quoted = f'Seguindo sua instrução: "{text}"'
    if esc.kind == "agent_failed" and esc.stage in ("planner", "interviewer"):
        # nothing to implement yet: re-run the same agent, planner gets the instruction
        pending = esc.pending
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
            s,
            at,
            "interviewer",
            edge=None,
            feedback=pending.feedback if pending else None,
            now=pending.now if pending else None,
        )

    # developer takes over, for every other escalation
    if esc.kind == "test_limit":
        p.test_attempt = 0  # a human instruction buys a fresh cycle
    elif esc.kind == "review_limit":
        p.review_round = 0
    edge = _INSTRUCT_EDGE.get(esc.stage)
    _log(p, esc.stage, "Instrução enviada pro Developer", at)
    p.stages[esc.stage].status = "idle"
    fb = Feedback(
        kind="human_instruction",
        text=text,
        test=_last_failed_test(p) if esc.stage == "tester" else None,
        review=p.review if esc.stage == "reviewer" and p.review is not None else None,
    )
    return _advance(s, at, "developer", edge=edge, feedback=fb, now=quoted, p=p)


# ---------------------------------------------------------------- usage limit (D50)


def _hit_limit(s: TaskState, p: Pipe, at: datetime, agent: AgentName, limit: UsageLimit) -> None:
    """The subscription quota ran out: park the job and wait for ``resume_after_limit``."""
    _undo_round(p, agent)
    _settle_edge(p)
    p.limited_pending = p.inflight
    p.current_job_id = None
    p.current_agent = None
    p.inflight = None
    _set(p, agent, "error", f"{limit.message} — retome depois do reset", at)
    s.limit = limit
    lane = _lane(p)
    if lane is not None:
        lane.status = "limited"
    s.phase = "limited"


def _resume_after_limit(
    state: TaskState, s: TaskState, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    if s.phase != "limited":
        return _reject(state, ERR_WRONG_PHASE)
    pipes: list[Pipe] = [s, *(lane for lane in s.lanes.values() if lane.status == "limited")]
    parked = [p for p in pipes if p.limited_pending is not None]
    if not parked:
        return _reject(state, ERR_WRONG_PHASE)
    s.limit = None
    effects: list[Effect] = []
    for p in parked:
        pending = p.limited_pending
        assert pending is not None
        p.limited_pending = None
        p.stages[pending.agent].status = "idle"
        _log(p, pending.agent, "Retomando depois do limite de uso", at)
        effects += _advance(
            s, at, pending.agent, edge=pending.edge, feedback=pending.feedback, now=pending.now, p=p
        )
    return _commit(s, *effects)


# ============================================================ split plan (D53-D57)


def _split_phase(s: TaskState) -> TaskPhase:
    """Task phase derived from its lanes: limited > running > waiting for the user."""
    statuses = {lane.status for lane in s.lanes.values()}
    if "limited" in statuses:
        return "limited"
    if statuses & _ACTIVE_LANE:
        return "executing"
    if "escalated" in statuses:
        return "escalated"
    return "awaiting_selection" if s.phase == "awaiting_selection" else "executing"


def _integration_id(epic_id: str) -> str:
    return f"M-{epic_id}"


def _approve_split(
    state: TaskState, s: TaskState, plan: Plan, picked: list[str], at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    ids = [e.id for e in plan.epics]
    if any(epic_id not in ids for epic_id in picked):
        return _reject(state, ERR_UNKNOWN_EPIC)
    chosen = plan_graph.closure(plan.epics, picked or ids)
    if not chosen:
        return _reject(state, ERR_NO_EPICS)
    s.chosen = [i for i in ids if i in chosen]
    s.lanes = {
        e.id: LaneState(
            id=e.id,
            title=e.title,
            status="waiting" if e.id in chosen else "pending",
            limits=s.limits.model_copy(),
        )
        for e in plan.epics
    }
    _set(s, "approval", "done", f"Plano aprovado · {len(chosen)} de {len(ids)} épicos agora", at)
    _settle_edge(s)
    s.phase = "executing"
    return _commit(s, _plan_doc_effect(s, commit=True), *_schedule(s, at))


def _schedule(s: TaskState, at: datetime) -> list[Effect]:
    """Start every chosen epic whose dependencies are merged (they run in parallel)."""
    assert s.plan is not None and s.workspace_path is not None
    merged = {lane.id for lane in s.lanes.values() if lane.status == "merged" and lane.kind == "epic"}
    started = {lane.id for lane in s.lanes.values() if lane.status not in ("pending", "waiting")}
    effects: list[Effect] = []
    for epic_id in plan_graph.ready(s.plan.epics, merged=merged, chosen=set(s.chosen), started=started):
        lane = s.lanes[epic_id]
        lane.status = "preparing"
        _log(lane, "developer", "Preparando o worktree do épico", at)
        effects.append(CreateEpicWorkspace(s.task_id, s.repo.name, epic_id, s.workspace_path))
    s.phase = _split_phase(s)
    return effects


def _run_epics(
    state: TaskState, s: TaskState, cmd: RunEpics, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    if s.phase != "awaiting_selection" or s.plan is None:
        return _reject(state, ERR_WRONG_PHASE)
    pending = {lane.id for lane in s.lanes.values() if lane.status == "pending"}
    if not cmd.epics:
        return _reject(state, ERR_NO_EPICS)
    if any(epic_id not in s.lanes for epic_id in cmd.epics):
        return _reject(state, ERR_UNKNOWN_EPIC)
    batch = plan_graph.closure(s.plan.epics, cmd.epics) & pending
    if not batch:
        return _reject(state, ERR_NO_EPICS)
    for epic_id in batch:
        s.lanes[epic_id].status = "waiting"
    s.chosen = [e.id for e in s.plan.epics if e.id in set(s.chosen) | batch]
    s.phase = "executing"
    _log(s, "approval", f"Próximo lote: {', '.join(sorted(batch))}", at)
    return _commit(s, *_schedule(s, at))


def _finish_task(state: TaskState, s: TaskState, at: datetime) -> tuple[TaskState | None, list[Effect]]:
    if s.phase != "awaiting_selection":
        return _reject(state, ERR_WRONG_PHASE)
    return _commit(s, *_finalize_split(s, at))


def _finalize_split(s: TaskState, at: datetime) -> list[Effect]:
    s.boot = "build_report"
    s.phase = "executing"
    _go(s, "rv-dn", "done")
    _log(s, "done", "Gerando relatório final", at)
    return [_final_report_effect(s, at)]


def _final_report_effect(s: TaskState, at: datetime | None = None) -> BuildFinalReport:
    assert s.workspace_path is not None
    if s.plan is None:
        return BuildFinalReport(s.task_id, s.repo.name, s.workspace_path)
    return BuildFinalReport(
        s.task_id,
        s.repo.name,
        s.workspace_path,
        plan_doc=_render_plan_doc(s, updated=at),
        commit_doc=s.split,
    )


def _merge_effect(s: TaskState, lane: LaneState) -> MergeEpic:
    assert s.workspace_path is not None
    return MergeEpic(
        s.task_id,
        s.repo.name,
        lane.id,
        s.workspace_path,
        commit_message=lane.commit_message or _epic_commit_fallback(lane),
        merge_message=_merge_message(s, lane.id),
    )


def _finish_merge_effect(s: TaskState, epic_id: str) -> FinishMerge:
    assert s.workspace_path is not None
    return FinishMerge(
        s.task_id,
        s.repo.name,
        epic_id,
        s.workspace_path,
        _merge_message(s, epic_id) + " · conflito resolvido",
    )


def _pump_merges(s: TaskState) -> list[Effect]:
    """One merge at a time: the task worktree is shared."""
    if s.merging is not None or not s.merge_queue:
        return []
    epic_id = s.merge_queue.pop(0)
    s.merging = epic_id
    return [_merge_effect(s, s.lanes[epic_id])]


def _lane_approved(s: TaskState, lane: LaneState, at: datetime) -> list[Effect]:
    lane.status = "merging"
    _settle_edge(lane)
    s.phase = _split_phase(s)
    if lane.kind == "integration":
        assert lane.merge_of is not None
        _log(lane, "reviewer", "Conflito resolvido — concluindo o merge", at)
        return [_finish_merge_effect(s, lane.merge_of)]
    lane.commit_message = (lane.review.commit_message if lane.review else None) or _epic_commit_fallback(lane)
    _log(lane, "reviewer", "Aprovado — commitando e juntando na branch da tarefa", at)
    s.merge_queue.append(lane.id)
    return _pump_merges(s)


def _after_merge(s: TaskState, at: datetime) -> list[Effect]:
    """A merge finished: start what it unblocked, the next merge, or close the batch."""
    effects = [*_schedule(s, at), *_pump_merges(s)]
    busy = any(
        lane.status in _ACTIVE_LANE or lane.status in ("escalated", "limited") for lane in s.lanes.values()
    )
    if busy or s.merge_queue:
        s.phase = _split_phase(s)
        return effects
    if any(s.lanes[epic_id].status != "merged" for epic_id in s.chosen):
        s.phase = _split_phase(s)
        return effects
    if any(lane.status == "pending" for lane in s.lanes.values()):
        s.phase = "awaiting_selection"
        _log(s, "approval", "Épicos escolhidos prontos — escolha os próximos ou conclua", at)
        # No merge in flight here, so committing the refreshed plan can't swallow a merge.
        return [*effects, _plan_doc_effect(s, commit=True)]
    return [*effects, *_finalize_split(s, at)]


def _on_epic_event(
    state: TaskState | None, ev: EpicWorkspaceReady | EpicWorkspaceFailed | EpicMerged
) -> tuple[TaskState | None, list[Effect]]:
    if state is None or state.terminal or state.task_id != ev.task_id or ev.epic_id not in state.lanes:
        return _stale(state, ev.task_id, type(ev).__name__)
    s = _copy(state)
    lane = s.lanes[ev.epic_id]
    match ev:
        case EpicWorkspaceReady():
            if lane.status != "preparing":
                return _stale(state, ev.task_id, "EpicWorkspaceReady")
            lane.workspace_path = ev.path
            lane.branch = ev.branch
            return _commit(
                s, *_advance(s, ev.at, "developer", edge=None, now="Implementando o épico", p=lane)
            )
        case EpicWorkspaceFailed():
            if lane.status != "preparing":
                return _stale(state, ev.task_id, "EpicWorkspaceFailed")
            reason = f"Falha ao preparar o worktree do épico: {ev.error}"
            _escalate(s, ev.at, "workspace", "developer", reason, now=reason[:160], p=lane)
            return _commit(s)
        case EpicMerged():
            return _on_merged(state, s, lane, ev)


def _on_merged(
    state: TaskState, s: TaskState, lane: LaneState, ev: EpicMerged
) -> tuple[TaskState | None, list[Effect]]:
    if s.merging != lane.id:
        return _stale(state, ev.task_id, "EpicMerged")
    integration = s.lanes.get(_integration_id(lane.id))
    if ev.error is not None:
        s.merging = None
        if integration is not None and integration.status == "merging":
            # the integrator's resolution did not hold: back to its Developer
            pending = PendingJob(
                agent="developer",
                feedback=Feedback(kind="merge_conflict", text=f"O merge ainda não fecha: {ev.error}"),
            )
            s.merging = lane.id
            _escalate(s, ev.at, "agent_failed", "reviewer", ev.error, pending=pending, p=integration)
            return _commit(s)
        reason = f"Merge na branch da tarefa falhou: {ev.error}"
        _escalate(s, ev.at, "merge", "reviewer", reason, now=reason[:160], p=lane)
        return _commit(s)
    if ev.conflicts:
        return _commit(s, *_start_integration(s, lane, ev.conflicts, ev.at))
    assert ev.sha is not None
    s.merging = None
    lane.status = "merged"
    lane.commit_sha = ev.sha
    _set(lane, "reviewer", "done", f"Juntado em {s.branch or s.task_id} · {ev.sha[:8]}", ev.at)
    if integration is not None:
        integration.status = "merged"
        integration.commit_sha = ev.sha
    effects: list[Effect] = []
    if s.workspace_path is not None:
        effects.append(RemoveEpicWorkspace(s.task_id, s.repo.name, lane.id, s.workspace_path))
    return _commit(s, *effects, *_after_merge(s, ev.at))


def _start_integration(
    s: TaskState, epic_lane: LaneState, conflicts: tuple[str, ...], at: datetime
) -> list[Effect]:
    lane_id = _integration_id(epic_lane.id)
    integration = s.lanes.get(lane_id)
    if integration is None:
        integration = LaneState(
            id=lane_id,
            kind="integration",
            title=f"Integração de {epic_lane.id} · {epic_lane.title}",
            status="running",
            limits=s.limits.model_copy(),
            merge_of=epic_lane.id,
            workspace_path=s.workspace_path,
            branch=s.branch,
        )
        s.lanes[lane_id] = integration
    files = ", ".join(conflicts[:10])
    _log(epic_lane, "reviewer", f"Conflito ao juntar: {files}", at)
    text = (
        f"O merge de {epic_lane.id} ({epic_lane.title}) em {s.branch or s.task_id} conflitou em: {files}. "
        "Os arquivos têm marcadores <<<<<<< ======= >>>>>>>. Resolva mantendo o que cada lado entrega, "
        "remova todos os marcadores e não faça commit (o dev-crew conclui o merge)."
    )
    return _advance(
        s,
        at,
        "developer",
        edge=None,
        feedback=Feedback(kind="merge_conflict", text=text),
        now=f"Resolvendo conflito em {files}"[:160],
        p=integration,
    )


def _retry_lane_io(s: TaskState, lane: LaneState, at: datetime) -> list[Effect]:
    """Escalated worktree setup or merge: try it again."""
    assert lane.escalation is not None
    kind = lane.escalation.kind
    lane.escalation = None
    for st in lane.stages.values():
        if st.status == "error":
            st.status = "idle"
    if kind == "workspace":
        assert s.workspace_path is not None
        lane.status = "preparing"
        _log(lane, "developer", "Tentando preparar o worktree de novo", at)
        s.phase = _split_phase(s)
        return [CreateEpicWorkspace(s.task_id, s.repo.name, lane.id, s.workspace_path)]
    lane.status = "merging"
    _log(lane, "reviewer", "Tentando o merge de novo", at)
    s.merge_queue.insert(0, lane.id)
    s.phase = _split_phase(s)
    return _pump_merges(s)


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
            if s.boot != "build_report" or (s.review is None and not s.split):
                return _stale(state, ev.task_id, "ReportBuilt")
            s.boot = None
            s.edges["rv-dn"] = "on"
            s.active_edge = None
            if ev.error:
                _log(s, "done", f"Relatório de arquivos indisponível: {ev.error}", ev.at)
            s.plan_doc = ev.plan_doc or s.plan_doc
            s.phase = "done"
            s.ended_at = ev.at
            if s.split:
                _set(s, "done", "done", f"Pronto: branch {s.branch} com um commit por épico", ev.at)
                commit_message = _fallback_commit_message(s)
            else:
                _set(s, "done", "done", "Pronto pra você revisar e commitar", ev.at)
                assert s.review is not None
                commit_message = s.review.commit_message or _fallback_commit_message(s)
            s.final = FinalReport(
                branch=s.branch or f"crew/{s.task_id}",
                worktree_path=s.workspace_path or "",
                files=ev.files,
                commit_message=commit_message,
                duration_s=round((ev.at - s.started_at).total_seconds(), 3),
                cost_usd=round(s.cost_usd, 6),
                tokens=s.tokens,
                commits=_epic_commits(s),
                pending_epics=[lane.id for lane in s.lanes.values() if lane.status == "pending"],
                plan_doc=s.plan_doc,
            )
            return _commit(s)


def _epic_commits(s: TaskState) -> list[EpicCommit]:
    if s.plan is None:
        return []
    out: list[EpicCommit] = []
    for e in s.plan.epics:
        lane = s.lanes.get(e.id)
        if lane is not None and lane.commit_sha:
            out.append(EpicCommit(epic_id=e.id, sha=lane.commit_sha, message=lane.commit_message or ""))
    return out


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


def _pipe_of(state: TaskState | None, ev: AgentResult | AgentFailed | AgentProgressed) -> Pipe | None:
    """The task or lane whose in-flight job the event belongs to (``None`` = stale)."""
    if state is None or state.terminal or state.task_id != ev.task_id:
        return None
    job_id: UUID = ev.evt.job_id
    if state.current_job_id is not None and state.current_job_id == job_id:
        return state
    for lane in state.lanes.values():
        if lane.current_job_id is not None and lane.current_job_id == job_id:
            return lane
    return None


def _on_agent_event(
    state: TaskState | None, ev: AgentResult | AgentFailed | AgentProgressed
) -> tuple[TaskState | None, list[Effect]]:
    found = _pipe_of(state, ev)
    if found is None:
        if isinstance(ev, AgentProgressed):
            return state, []  # progress of a dead job: silently dropped
        return state, [LogStale(ev.task_id, type(ev).__name__, ev.evt.job_id)]
    assert state is not None
    s = _copy(state)
    p: Pipe = s if isinstance(found, TaskState) else s.lanes[found.id]
    match ev:
        case AgentProgressed():
            _log(p, ev.evt.agent, ev.evt.text, ev.at)
            return s, []
        case AgentFailed():
            if ev.evt.retryable:  # the bus will redeliver; just surface it
                _log(p, ev.evt.agent, f"Tentando de novo: {ev.evt.error}"[:160], ev.at)
                return s, []
            if ev.evt.limit is not None:
                _hit_limit(s, p, ev.at, ev.evt.agent, ev.evt.limit)
                return _commit(s)
            _fail_job(s, ev.at, ev.evt.agent, ev.evt.error, p.inflight, p)
            return _commit(s)
        case AgentResult():
            return _on_result(s, p, ev)


def _bad_output(
    s: TaskState, p: Pipe, ev: AgentResult, expected: str, pending: PendingJob | None
) -> tuple[TaskState | None, list[Effect]]:
    got = type(ev.evt.output).__name__
    _fail_job(s, ev.at, ev.evt.agent, f"saída inesperada ({got}), esperava {expected}", pending, p)
    return _commit(s)


def _on_result(s: TaskState, p: Pipe, ev: AgentResult) -> tuple[TaskState | None, list[Effect]]:
    evt = ev.evt
    agent = evt.agent
    out = evt.output
    pending = p.inflight
    tokens = sum(u.input_tokens + u.output_tokens for u in evt.usage)
    s.cost_usd += evt.cost_usd  # spent even if the output is unusable (API-price equivalent)
    s.tokens += tokens
    lane = _lane(p)
    if lane is not None:
        lane.cost_usd += evt.cost_usd
        lane.tokens += tokens
    if evt.session_id:
        p.sessions[agent] = evt.session_id
    p.current_job_id = None
    p.current_agent = None
    p.inflight = None

    match agent:
        case "interviewer":
            if not isinstance(out, InterviewResult) or lane is not None:
                return _bad_output(s, p, ev, "InterviewResult", pending)
            return _interviewer_result(s, out, ev.at, pending)
        case "planner":
            if not isinstance(out, Plan) or lane is not None:
                return _bad_output(s, p, ev, "Plan", pending)
            s.estimate = ev.estimate
            return _planner_result(s, out, ev.at)
        case "developer":
            if not isinstance(out, DevResult):
                return _bad_output(s, p, ev, "DevResult", pending)
            return _developer_result(s, p, out, ev.at)
        case "tester":
            if not isinstance(out, TestResult):
                return _bad_output(s, p, ev, "TestResult", pending)
            return _tester_result(s, p, out, ev.at)
        case "reviewer":
            if not isinstance(out, ReviewResult):
                return _bad_output(s, p, ev, "ReviewResult", pending)
            return _reviewer_result(s, p, out, ev.at)


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
    if plan.execution == "epics" and plan.epics:
        summary = f"Plano pronto · {len(plan.epics)} épicos, {len(plan.files)} arquivos"
    else:
        summary = f"Plano pronto · {len(plan.steps)} passos, {len(plan.files)} arquivos"
    _set(s, "planner", "done", summary, at)
    s.phase = "awaiting_approval"
    _go(s, "pl-ap", "approval", "waiting")
    _log(s, "approval", "Aguardando você — expanda pra revisar o plano", at)
    return _commit(s)


def _developer_result(
    s: TaskState, p: Pipe, dev: DevResult, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    p.dev_rounds.append(dev.model_copy(update={"round": p.dev_round}))
    where = "no worktree do épico" if _lane(p) is not None else "no repo local · sem commit"
    _set(p, "developer", "done", f"Rodada {p.dev_round} salva {where}", at)
    now = "Escrevendo testes" if not p.test_runs else "Rodando a suíte de novo"
    effects = _advance(s, at, "tester", edge="dv-ts", now=now, p=p)
    return _commit(s, *effects)


def _tester_result(
    s: TaskState, p: Pipe, res: TestResult, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    p.test_runs.append(res)
    if res.ok:
        p.test_attempt = 0
        cov = f" · cobertura {round(res.coverage * 100)}%" if res.coverage is not None else ""
        _set(p, "tester", "done", f"PASSOU · {res.passed}/{res.total}{cov}", at)
        effects = _advance(s, at, "reviewer", edge="ts-rv", p=p)
        return _commit(s, *effects)

    p.test_attempt += 1
    n, mx = p.test_attempt, p.limits.max_test_attempts
    _set(p, "tester", "error", f"FALHOU · {res.passed}/{res.total} · tentativa {n}/{mx}", at)
    if n >= mx:
        _escalate(
            s,
            at,
            "test_limit",
            "tester",
            f"{n} falhas consecutivas de teste",
            now=f"Limite {mx}/{mx} atingido — expanda pra decidir",
            p=p,
        )
        return _commit(s)
    p.stages["tester"].status = "idle"
    effects = _advance(
        s,
        at,
        "developer",
        edge="ts-dv",
        feedback=Feedback(kind="test_failures", test=res),
        now=_fix_text(res),
        p=p,
    )
    return _commit(s, *effects)


def _reviewer_result(
    s: TaskState, p: Pipe, res: ReviewResult, at: datetime
) -> tuple[TaskState | None, list[Effect]]:
    has_major = any(c.severity == "major" and not c.resolved for c in res.comments)
    approved = res.verdict == "approved" and not has_major
    lane = _lane(p)

    if approved:
        earlier = [c.model_copy(update={"resolved": True}) for r in p.reviews for c in r.comments]
        p.reviews.append(res)
        fallback = _epic_commit_fallback(lane) if lane is not None else _fallback_commit_message(s)
        p.review = res.model_copy(
            update={
                "verdict": "approved",
                "comments": [*earlier, *res.comments],
                "commit_message": res.commit_message or fallback,
            }
        )
        _set(p, "reviewer", "done", "APROVADO · comentários resolvidos", at)
        if lane is not None:
            return _commit(s, *_lane_approved(s, lane, at))
        _go(s, "rv-dn", "done")
        _log(s, "done", "Gerando relatório final", at)
        s.boot = "build_report"
        return _commit(s, _final_report_effect(s, at))

    corrected = (
        res if res.verdict == "changes_requested" else res.model_copy(update={"verdict": "changes_requested"})
    )
    p.reviews.append(corrected)
    p.review = corrected
    majors = sum(1 for c in corrected.comments if c.severity == "major")
    minors = sum(1 for c in corrected.comments if c.severity == "minor")
    nits = sum(1 for c in corrected.comments if c.severity == "nit")
    label = f"CHANGES REQUESTED · {majors} major, {minors} minor" + (f", {nits} nit" if nits else "")
    _set(p, "reviewer", "error", label, at)
    n, mx = p.review_round, p.limits.max_review_rounds
    if n >= mx:
        _escalate(
            s,
            at,
            "review_limit",
            "reviewer",
            f"{n} rodadas de review sem aprovação",
            now=f"Limite {mx}/{mx} atingido — expanda pra decidir",
            p=p,
        )
        return _commit(s)
    p.stages["reviewer"].status = "idle"
    effects = _advance(
        s,
        at,
        "developer",
        edge="rv-dv",
        feedback=Feedback(kind="review_comments", review=corrected),
        now=_review_text(corrected),
        p=p,
    )
    return _commit(s, *effects)

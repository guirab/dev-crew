/**
 * Cenário do modo mock: porta o motor do mockup (`mockup/index.html`) pra um "backend" que emite
 * `TaskView`s válidos e reage aos `Command`s da UI. É a única parte do front com regra de fluxo,
 * e só existe pra desenvolver a UI sem o orquestrador (nunca entra no bundle de produção).
 *
 * Fluxo: manual → (entrevista, 3 perguntas) → plano → aprovação (ou ajuste) → developer →
 * tester (1º run falha) → developer → tester ok → reviewer (1º review pede mudanças) → developer →
 * tester ok → reviewer aprova → concluída. `forceEscalate` faz o Tester falhar sempre (escalada).
 */
import type {
  Command,
  DevResult,
  Escalation,
  FinalReport,
  InterviewQuestion,
  InterviewTurn,
  LogLine,
  Plan,
  ReviewResult,
  StageView,
  StartTask,
  TaskView,
  TestResult,
  WsMessage,
} from '../contracts/generated'
import type { EdgeKey, EdgeStatus, StageKey, StageStatus, TaskPhase } from '../contracts/aliases'
import type { CommandOutcome, MockBackend } from './backend'
import { INTERVIEW_ROUNDS, REPOS } from './data'

export interface ScenarioOptions {
  /** Multiplicador de velocidade (2 = metade do tempo). */
  speed?: number
  /** Faz o Tester falhar sempre, forçando a escalada. */
  forceEscalate?: boolean
  now?: () => Date
}

type Listener = (msg: WsMessage) => void

const STAGE_KEYS: readonly StageKey[] = [
  'manual',
  'interviewer',
  'planner',
  'approval',
  'developer',
  'tester',
  'reviewer',
  'done',
]

const PHASE_OF: Partial<Record<StageKey, TaskPhase>> = {
  interviewer: 'interviewing',
  planner: 'planning',
  approval: 'awaiting_approval',
  developer: 'developing',
  tester: 'testing',
  reviewer: 'reviewing',
  done: 'done',
}

const MAX_LOGS = 50

/** Cancelamento de fluxo assíncrono (nova tarefa/cancelar/dispose). */
class Cancelled extends Error {}

interface InterviewState {
  turns: InterviewTurn[]
  queue: (readonly InterviewQuestion[])[]
  pending: readonly InterviewQuestion[]
  round: number
  decisions: string[]
}

interface TaskState {
  taskId: string
  title: string
  description: string
  repo: string
  phase: TaskPhase
  st: Record<StageKey, StageStatus>
  now: Partial<Record<StageKey, string>>
  logs: Record<StageKey, LogLine[]>
  edges: Record<string, EdgeStatus>
  activeEdge: EdgeKey | null
  testIter: number
  maxTest: number
  reviewIter: number
  maxReview: number
  rounds: DevResult[]
  runs: TestResult[]
  review: ReviewResult | null
  plan: Plan | null
  interview: InterviewState | null
  escalation: Escalation | null
  final: FinalReport | null
  startedAt: Date
  endedAt: Date | null
}

function perStage<T>(make: (key: StageKey) => T): Record<StageKey, T> {
  return {
    manual: make('manual'),
    interviewer: make('interviewer'),
    planner: make('planner'),
    approval: make('approval'),
    developer: make('developer'),
    tester: make('tester'),
    reviewer: make('reviewer'),
    done: make('done'),
  }
}

const isTerminal = (phase: TaskPhase): boolean =>
  phase === 'done' || phase === 'cancelled' || phase === 'failed'

const lowerFirst = (text: string): string => text.charAt(0).toLowerCase() + text.slice(1)

export class ScenarioBackend implements MockBackend {
  readonly repos = REPOS

  private s: TaskState | null = null
  private readonly listeners = new Set<Listener>()
  private readonly timers = new Set<ReturnType<typeof setTimeout>>()
  private generation = 0
  private taskCounter = 106
  private speedFactor: number
  private escalateFlag: boolean
  private readonly clock: () => Date

  constructor(options: ScenarioOptions = {}) {
    this.speedFactor = options.speed ?? 1
    this.escalateFlag = options.forceEscalate ?? false
    this.clock = options.now ?? (() => new Date())
  }

  get speed(): number {
    return this.speedFactor
  }

  setSpeed(value: number): void {
    this.speedFactor = value > 0 ? value : 1
  }

  get forceEscalate(): boolean {
    return this.escalateFlag
  }

  setForceEscalate(value: boolean): void {
    this.escalateFlag = value
  }

  // ---------------------------------------------------------------- MockBackend

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  dispose(): void {
    this.generation += 1
    for (const timer of this.timers) clearTimeout(timer)
    this.timers.clear()
    this.listeners.clear()
  }

  getView(): TaskView | null {
    const s = this.s
    if (!s) return null
    const stage = (key: StageKey): StageView => ({
      status: s.st[key],
      now: s.now[key] ?? null,
      logs: s.logs[key],
    })
    return {
      task_id: s.taskId,
      title: s.title,
      description: s.description,
      repo: s.repo,
      phase: s.phase,
      stages: {
        manual: stage('manual'),
        interviewer: stage('interviewer'),
        planner: stage('planner'),
        approval: stage('approval'),
        developer: stage('developer'),
        tester: stage('tester'),
        reviewer: stage('reviewer'),
        done: stage('done'),
      },
      edges: { ...s.edges },
      active_edge: s.activeEdge,
      counters: {
        dev_round: s.rounds.length,
        test_attempt: s.testIter,
        max_test_attempts: s.maxTest,
        review_round: s.reviewIter,
        max_review_rounds: s.maxReview,
      },
      interview: s.interview
        ? {
            turns: s.interview.turns,
            pending: [...s.interview.pending],
            decisions: s.interview.decisions,
          }
        : null,
      plan: s.plan,
      dev_rounds: s.rounds,
      test_runs: s.runs,
      review: s.review,
      escalation: s.escalation,
      final: s.final,
      started_at: s.startedAt.toISOString(),
      ended_at: s.endedAt?.toISOString() ?? null,
      cost_usd: this.cost(s),
    }
  }

  /** Custo fictício: US$ 0,35 por job (developer + tester + reviewer). */
  private cost(s: TaskState): number {
    return Number((0.35 * (s.rounds.length + s.runs.length + s.reviewIter)).toFixed(2))
  }

  handle(command: Command): CommandOutcome {
    switch (command.type) {
      case 'start_task':
        return this.start(command)
      case 'answer_interview':
        return this.answer(command.answers)
      case 'approve_plan':
        return this.approve()
      case 'adjust_plan':
        return this.adjust(command.text)
      case 'escalation':
        return this.escalate(command.action, command.text ?? null)
      case 'cancel_task':
        return this.cancel()
    }
  }

  // ---------------------------------------------------------------- comandos

  private refuse(status: 409 | 422, error: string): CommandOutcome {
    return { status, reply: { ok: false, error, view: null } }
  }

  private accepted(): CommandOutcome {
    return { status: 200, reply: { ok: true, error: null, view: this.getView() } }
  }

  private start(command: StartTask): CommandOutcome {
    if (this.s && !isTerminal(this.s.phase)) return this.refuse(409, 'Já existe uma tarefa ativa.')
    if (!REPOS.some((r) => r.name === command.repo))
      return this.refuse(422, 'Repositório desconhecido.')

    const manualTitle = command.title.trim()
    if (manualTitle === '') {
      return this.refuse(422, 'Informe um título pra tarefa.')
    }

    const manualDescription = command.description?.trim() ?? ''

    this.generation += 1
    this.taskCounter += 1
    const taskId = `T-${this.taskCounter}`
    const title = manualTitle
    const s: TaskState = {
      taskId,
      title,
      description:
        manualDescription === ''
          ? 'Sem descrição — o Entrevistador vai perguntar o resto.'
          : manualDescription,
      repo: command.repo,
      phase: 'interviewing',
      st: perStage((key) => (key === 'manual' ? 'pick' : 'idle')),
      now: {},
      logs: perStage(() => []),
      edges: {},
      activeEdge: null,
      testIter: 0,
      maxTest: 3,
      reviewIter: 0,
      maxReview: 2,
      rounds: [],
      runs: [],
      review: null,
      plan: null,
      interview: null,
      escalation: null,
      final: null,
      startedAt: this.clock(),
      endedAt: null,
    }
    this.s = s

    this.finish('manual', title)
    s.interview = { turns: [], queue: [...INTERVIEW_ROUNDS], pending: [], round: 0, decisions: [] }
    this.nextQuestion(s.interview)
    s.now.interviewer = 'Aguardando sua resposta — expanda pra responder'
    this.go('ma-iv', 'interviewer', 'waiting')
    return this.accepted()
  }

  private nextQuestion(interview: InterviewState): boolean {
    interview.pending = interview.queue.shift() ?? []
    if (interview.pending.length > 0) interview.round += 1
    return interview.pending.length > 0
  }

  private answer(answers: readonly (string | null)[]): CommandOutcome {
    const s = this.s
    const interview = s?.interview
    if (!s || !interview || interview.pending.length === 0 || s.st.interviewer !== 'waiting') {
      return this.refuse(409, 'Nenhuma pergunta aguardando resposta.')
    }
    if (answers.length !== interview.pending.length) {
      return this.refuse(422, 'Responda todas as perguntas da rodada.')
    }

    interview.pending.forEach((question, i) => {
      const text = answers[i]?.trim() ?? ''
      const accepted = text === '' || text === question.recommendation
      const answer = accepted ? question.recommendation : text
      interview.turns.push({
        question,
        answer,
        accepted_recommendation: accepted,
        round: interview.round,
      })
      interview.decisions.push(`${question.topic}: ${answer}`)
    })
    this.log('interviewer', `Rodada ${String(interview.round)} respondida`)

    if (!this.nextQuestion(interview)) {
      this.run(async () => {
        this.finish('interviewer', `Spec fechada · ${interview.decisions.length} decisões`)
        await this.wait(700)
        this.go('iv-pl', 'planner')
        await this.runPlanner()
      })
    }
    this.emit()
    return this.accepted()
  }

  private approve(): CommandOutcome {
    const s = this.s
    if (s?.st.approval !== 'waiting') return this.refuse(409, 'Nenhum plano aguardando aprovação.')
    this.run(async () => {
      this.finish('approval', 'Plano aprovado')
      this.go('ap-dv', 'developer')
      await this.devRound()
    })
    return this.accepted()
  }

  private adjust(text: string): CommandOutcome {
    const s = this.s
    if (s?.st.approval !== 'waiting') return this.refuse(409, 'Nenhum plano aguardando aprovação.')
    const feedback = text.trim()
    if (feedback === '') return this.refuse(422, 'Descreva o ajuste.')
    s.st.approval = 'idle'
    this.log('approval', `Ajuste pedido: ${feedback}`)
    s.edges['pl-ap'] = 'on'
    s.activeEdge = null
    this.run(() => this.runPlanner(feedback))
    return this.accepted()
  }

  private escalate(
    action: 'instruct' | 'more_attempts' | 'replan',
    text: string | null,
  ): CommandOutcome {
    const s = this.s
    if (!s?.escalation) return this.refuse(409, 'Não há escalada pendente.')
    const instruction = text?.trim() ?? ''
    if (action === 'instruct' && instruction === '') return this.refuse(422, 'Escreva a instrução.')

    this.escalateFlag = false
    s.escalation = null
    if (action === 'replan') {
      s.st.tester = s.st.developer = s.st.approval = 'idle'
      s.testIter = 0
      s.activeEdge = null
      this.run(() => this.runPlanner('3 falhas seguidas no Tester — rever abordagem'))
      return this.accepted()
    }
    if (action === 'more_attempts') {
      s.maxTest += 2
      this.log('tester', `Limite aumentado pra ${s.maxTest}`)
    } else {
      this.log('tester', 'Instrução enviada pro Developer')
    }
    s.st.tester = 'idle'
    this.go('ts-dv', 'developer')
    this.run(() =>
      this.devRound(
        action === 'more_attempts'
          ? 'Nova tentativa com +2 iterações'
          : `Seguindo sua instrução: "${instruction}"`,
      ),
    )
    return this.accepted()
  }

  private cancel(): CommandOutcome {
    const s = this.s
    if (!s || isTerminal(s.phase)) return this.refuse(409, 'Nenhuma tarefa ativa.')
    this.generation += 1
    for (const key of STAGE_KEYS) {
      if (s.st[key] === 'active' || s.st[key] === 'waiting' || s.st[key] === 'error') {
        s.st[key] = 'idle'
        s.now[key] = 'Tarefa cancelada'
      }
    }
    if (s.activeEdge) s.edges[s.activeEdge] = 'on'
    s.activeEdge = null
    s.escalation = null
    s.phase = 'cancelled'
    s.endedAt = this.clock()
    this.emit()
    return this.accepted()
  }

  // ---------------------------------------------------------------- motor (porta do mockup)

  private requireState(): TaskState {
    if (!this.s) throw new Cancelled()
    return this.s
  }

  private emit(): void {
    const view = this.getView()
    for (const listener of this.listeners) listener({ type: 'view', data: view })
  }

  private progress(agent: 'planner' | 'developer' | 'tester' | 'reviewer', text: string): void {
    const s = this.s
    if (!s) return
    for (const listener of this.listeners) {
      listener({
        type: 'progress',
        task_id: s.taskId,
        data: { agent, job_id: crypto.randomUUID(), kind: 'tool', text },
      })
    }
  }

  private wait(ms: number): Promise<void> {
    const generation = this.generation
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.timers.delete(timer)
        if (generation === this.generation) resolve()
        else reject(new Cancelled())
      }, ms / this.speedFactor)
      this.timers.add(timer)
    })
  }

  /** Dispara um fluxo assíncrono, engolindo só o cancelamento. */
  private run(flow: () => Promise<void>): void {
    flow().catch((error: unknown) => {
      if (!(error instanceof Cancelled)) console.error('[mock scenario]', error)
    })
  }

  private log(key: StageKey, text: string): void {
    const s = this.requireState()
    s.logs[key] = [...s.logs[key], { ts: this.clock().toISOString(), text }].slice(-MAX_LOGS)
    s.now[key] = text
    this.emit()
  }

  private async step(
    key: 'planner' | 'developer' | 'tester' | 'reviewer',
    text: string,
    ms: number,
    ticks: readonly string[] = [],
  ): Promise<void> {
    const s = this.requireState()
    s.st[key] = 'active'
    s.phase = PHASE_OF[key] ?? s.phase
    this.log(key, text)
    const slice = ms / (ticks.length + 1)
    for (const tick of ticks) {
      await this.wait(slice)
      this.progress(key, tick)
    }
    await this.wait(slice)
  }

  private finish(key: StageKey, text: string): void {
    this.requireState().st[key] = 'done'
    this.log(key, text)
  }

  private go(edge: EdgeKey, key: StageKey, status: StageStatus = 'active'): void {
    const s = this.requireState()
    if (s.activeEdge) s.edges[s.activeEdge] = 'on'
    s.edges[edge] = 'active'
    s.activeEdge = edge
    s.st[key] = status
    s.phase = PHASE_OF[key] ?? s.phase
    this.emit()
  }

  private async runPlanner(feedback?: string): Promise<void> {
    await this.step(
      'planner',
      feedback ? `Revendo plano: "${feedback}"` : 'Lendo tarefa e critérios de aceite',
      1000,
    )
    await this.step('planner', 'Explorando repo (Grep/Read nos módulos afetados)', 1300, [
      'Grep "service" em src/',
      'Read src/services/service.py',
    ])
    await this.step('planner', 'Montando passos, arquivos e critérios', 1000)

    const s = this.requireState()
    const decisions = s.interview?.decisions ?? []
    s.plan = {
      type: 'plan',
      summary: `Implementar "${s.title}" seguindo os padrões do repo, com testes cobrindo os critérios de aceite.`,
      steps: [
        'Mapear módulo afetado e pontos de extensão',
        'Backend: endpoint/serviço com validação de entrada',
        'Front: componente + estado na query string',
        'Testes: unit no serviço + integração no endpoint',
      ],
      files: [
        { path: 'src/api/routes.py', change: 'M' },
        { path: 'src/services/service.py', change: 'M' },
        { path: 'web/components/Feature.tsx', change: 'A' },
        { path: 'tests/test_feature.py', change: 'A' },
      ],
      acceptance_criteria: [
        ...(s.interview
          ? decisions.filter((d) => d.startsWith('Critérios'))
          : ['Critérios do work item']),
        'Sem regressão na suíte existente',
      ],
      risks: ['Timezone: datas locais vs UTC no banco'],
      test_strategy:
        'Unit no serviço + integração no endpoint, cobrindo bordas e entrada inválida.',
    }
    this.finish(
      'planner',
      `Plano pronto · ${s.plan.steps.length} passos, ${s.plan.files.length} arquivos`,
    )
    s.now.approval = 'Aguardando você — expanda pra revisar o plano'
    this.go('pl-ap', 'approval', 'waiting')
  }

  private async devRound(reason?: string): Promise<void> {
    if (reason) {
      await this.step('developer', reason, 1200)
    } else {
      const s = this.requireState()
      await this.step('developer', `Preparando worktree local crew/${s.taskId}`, 800)
      await this.step('developer', 'Editando src/api/routes.py, src/services/service.py', 1300, [
        'Edit src/api/routes.py',
        'Edit src/services/service.py',
      ])
      await this.step('developer', 'Criando web/components/Feature.tsx', 1000)
    }
    const s = this.requireState()
    s.rounds = [
      ...s.rounds,
      {
        type: 'dev',
        round: s.rounds.length + 1,
        summary: reason ?? 'Implementa o plano',
        files_changed: s.plan?.files ?? [],
        notes: null,
      },
    ]
    this.finish('developer', `Rodada ${s.rounds.length} salva no repo local · sem commit`)
    this.go('dv-ts', 'tester')
    await this.testRound()
  }

  private async testRound(): Promise<void> {
    const s = this.requireState()
    const firstRun = s.runs.length === 0
    await this.step(
      'tester',
      firstRun ? 'Escrevendo testes de integração' : 'Rodando a suíte de novo',
      900,
    )
    await this.step('tester', '$ pytest -q && npm test', 1300, ['$ pytest -q', '$ npm test'])

    const command = 'pytest -q && npm test'
    if (this.escalateFlag || firstRun) {
      s.testIter += 1 // falhas consecutivas
      s.runs = [
        ...s.runs,
        {
          type: 'test',
          ok: false,
          passed: 46,
          total: 48,
          failures: [
            {
              test: 'test_feature.py::test_range_inclusive_end',
              message: 'esperado 12, obtido 9',
            },
            {
              test: 'test_feature.py::test_invalid_input_returns_400',
              message: 'assert 200 == 400',
            },
          ],
          coverage: null,
          command,
          tests_written: ['tests/test_feature.py'],
        },
      ]
      s.st.tester = 'error'
      this.log('tester', `FALHOU · 46/48 · tentativa ${s.testIter}/${s.maxTest}`)
      if (s.testIter >= s.maxTest) {
        s.escalation = { stage: 'tester', reason: `${s.maxTest} falhas consecutivas de teste` }
        s.phase = 'escalated'
        s.now.tester = `Limite ${s.maxTest}/${s.maxTest} atingido — expanda pra decidir`
        this.emit()
        return
      }
      await this.wait(900)
      s.st.tester = 'idle'
      this.go('ts-dv', 'developer')
      await this.devRound('Corrigindo: test_range_inclusive_end, test_invalid_input_returns_400')
      return
    }

    s.runs = [
      ...s.runs,
      {
        type: 'test',
        ok: true,
        passed: 48,
        total: 48,
        failures: [],
        coverage: 0.87,
        command,
        tests_written: ['tests/test_feature.py'],
      },
    ]
    this.finish('tester', 'PASSOU · 48/48 · cobertura 87%')
    s.testIter = 0
    this.go('ts-rv', 'reviewer')
    await this.reviewRound()
  }

  private async reviewRound(): Promise<void> {
    const s = this.requireState()
    s.reviewIter += 1
    await this.step('reviewer', '$ git diff — lendo alterações', 1100)
    await this.step('reviewer', 'Checando segurança, padrões do repo e aderência ao plano', 1300, [
      'Read src/services/service.py',
    ])

    if (s.reviewIter === 1) {
      s.review = {
        type: 'review',
        verdict: 'changes_requested',
        comments: [
          {
            severity: 'major',
            file: 'src/services/service.py',
            line: 42,
            text: 'Query montada com f-string — usar bind params.',
            resolved: false,
          },
          {
            severity: 'minor',
            file: 'web/components/Feature.tsx',
            line: 9,
            text: 'Converter datas pra UTC antes de enviar.',
            resolved: false,
          },
        ],
        commit_message: null,
      }
      s.st.reviewer = 'error'
      this.log('reviewer', 'CHANGES REQUESTED · 1 major, 1 minor')
      await this.wait(900)
      s.st.reviewer = 'idle'
      this.go('rv-dv', 'developer')
      await this.devRound('Aplicando review: bind params na query, datas em UTC')
      return
    }

    const commitMessage = this.commitMessage(s)
    s.review = {
      type: 'review',
      verdict: 'approved',
      comments: (s.review?.comments ?? []).map((c) => ({ ...c, resolved: true })),
      commit_message: commitMessage,
    }
    this.finish('reviewer', 'APROVADO · comentários resolvidos')
    s.endedAt = this.clock()
    if (s.activeEdge) s.edges[s.activeEdge] = 'on'
    s.edges['rv-dn'] = 'on'
    s.activeEdge = null
    s.final = this.finalReport(s, commitMessage)
    s.st.done = 'done'
    s.phase = 'done'
    this.log('done', 'Pronto pra você revisar e commitar')
  }

  private commitMessage(s: TaskState): string {
    const steps = s.plan?.steps.slice(1) ?? []
    const lines = [
      `feat: ${lowerFirst(s.title)}`,
      '',
      ...steps.map((step) => `- ${lowerFirst(step)}`),
    ]
    if (s.reviewIter > 1) lines.push('- bind params na query e datas em UTC (review)')
    return lines.join('\n')
  }

  private finalReport(s: TaskState, commitMessage: string): FinalReport {
    const end = s.endedAt ?? this.clock()
    return {
      branch: `crew/${s.taskId}`,
      worktree_path: `C:/Users/dev/.dev-crew/worktrees/${s.repo}/${s.taskId}`,
      files: (s.plan?.files ?? []).map((file, i) => ({
        path: file.path,
        status: file.change,
        added: file.change === 'A' ? 40 + i * 7 : 12 + i * 5,
        removed: file.change === 'A' ? 0 : 2 + i,
      })),
      commit_message: commitMessage,
      duration_s: Math.max(1, Math.round((end.getTime() - s.startedAt.getTime()) / 1000)),
      cost_usd: this.cost(s),
    }
  }
}

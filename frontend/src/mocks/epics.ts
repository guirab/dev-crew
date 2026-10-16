/**
 * Plano dividido do modo mock (tarefa com "épicos" no título, como no fake do backend): 6 épicos +
 * review final, já rodando em paralelo, com o E2 escalado. Snapshot fixo pra desenhar a tela de épicos.
 */
import type { Counters, Epic, EpicView, StageView, TestResult } from '../contracts/generated'

interface Spec {
  id: string
  title: string
  goal: string
  depends_on?: string[]
}

const SPECS: readonly Spec[] = [
  {
    id: 'E1',
    title: 'Button glass sobre o Button do shadcn',
    goal: 'src/ui/Button.tsx renderiza o Button do shadcn com as variantes glass via cva',
  },
  {
    id: 'E2',
    title: 'Label + Input do shadcn nos formulários e fim do Field',
    goal: 'ManualForm, NewProjectForm, AddRepoForm, ApprovalBody e RepoSelect com Label/Input glass',
  },
  {
    id: 'E3',
    title: 'RepoSelect com o Select do shadcn',
    goal: 'A escolha de repositório no formulário Manual usa o Select (Radix)',
    depends_on: ['E2'],
  },
  {
    id: 'E4',
    title: 'Tooltip no UsageChip e na faixa Agora',
    goal: 'Tokens, custo e uso da conta com Tooltip; TooltipProvider no main.tsx',
  },
  {
    id: 'E5',
    title: 'Dialog no FolderBrowser e no AddRepoForm',
    goal: 'Navegador de pastas abre num Dialog; Esc e botão fecham',
  },
  {
    id: 'E6',
    title: 'Alert no LimitBanner e no ReconnectBanner',
    goal: 'Banners usam Alert com a skin, sem CSS Module próprio',
  },
]

/** Os épicos do plano (o Planner real os escreve; aqui são fixos). */
export function demoEpicPlan(): Epic[] {
  return SPECS.map((spec) => ({
    id: spec.id,
    title: spec.title,
    goal: spec.goal,
    steps: ['Trocar o componente', 'Ajustar os testes'],
    files: [{ path: `frontend/src/${spec.id}.tsx`, change: 'M' }],
    depends_on: spec.depends_on ?? [],
    acceptance_criteria: ['Testes verdes'],
    size: 'S',
  }))
}

const FAILED_RUN: TestResult = {
  type: 'test',
  ok: false,
  passed: 330,
  total: 332,
  failures: [
    {
      test: 'src/bodies/ManualForm.test.tsx > envia a tarefa com título',
      message: 'TestingLibraryElementError: Unable to find a label with the text of: Título',
    },
    {
      test: 'src/bodies/AddRepoForm.test.tsx > valida o nome',
      message: 'expected "Nome" to be associated with an input (htmlFor sem id)',
    },
  ],
  coverage: null,
  command: 'npm test',
  tests_written: [],
}

/** As faixas rodando: E2 escalado, E1/E5 rodando, E6 preparando, E3 esperando o E2, E4 pronto. */
export function demoLanes(taskId: string, repo: string, now: Date): EpicView[] {
  const at = (minutesAgo: number) => new Date(now.getTime() - minutesAgo * 60_000).toISOString()
  const stage = (
    status: StageView['status'],
    logs: [number, string][] = [],
    current: string | null = null,
  ): StageView => ({
    status,
    now: current ?? logs.at(-1)?.[1] ?? null,
    logs: logs.map(([ago, text]) => ({ ts: at(ago), text })),
  })
  const counters = (dev: number, test: number): Counters => ({
    dev_round: dev,
    test_attempt: test,
    max_test_attempts: 3,
    review_round: 0,
    max_review_rounds: 2,
  })
  const base = (spec: Spec | undefined, id: string): EpicView => ({
    id,
    kind: 'epic',
    title: spec?.title ?? id,
    goal: spec?.goal ?? '',
    size: 'S',
    depends_on: spec?.depends_on ?? [],
    status: 'pending',
    stages: { developer: stage('idle'), tester: stage('idle'), reviewer: stage('idle') },
    edges: {},
    active_edge: null,
    counters: counters(0, 0),
    dev_rounds: [],
    test_runs: [],
    review: null,
    escalation: null,
    branch: `crew/${taskId}-${id}`,
    worktree_path: `C:/Users/dev/.dev-crew/worktrees/${repo}/${taskId}-${id}`,
    commit: null,
    commit_message: null,
    cost_usd: 0,
    tokens: 0,
  })
  const lane = (id: string, over: Partial<EpicView>): EpicView => ({
    ...base(
      SPECS.find((spec) => spec.id === id),
      id,
    ),
    ...over,
  })
  // o mesmo instante em vários épicos: o feed junta numa linha
  const prep: [number, string] = [15, 'Preparando o worktree']

  return [
    lane('E1', {
      status: 'running',
      stages: {
        developer: stage('done', [prep, [9, 'Rodada 1 salva · 2 arquivos']]),
        tester: stage('active', [[2, 'Rodando npm test (rodada 1)']]),
        reviewer: stage('idle'),
      },
      counters: counters(1, 0),
      cost_usd: 0.61,
      tokens: 9_100,
    }),
    lane('E2', {
      status: 'escalated',
      stages: {
        developer: stage('done', [prep, [12, 'Rodada 3 salva · 5 arquivos']]),
        tester: stage('error', [
          [11, 'FALHOU · 330/332 · tentativa 1/3'],
          [6, 'FALHOU · 330/332 · tentativa 2/3'],
          [
            1,
            'Tester falhou 3 vezes seguidas: 2 testes do ManualForm e do AddRepoForm procuram o campo pelo texto do Label, e o Label do shadcn não está associado ao Input (htmlFor sem id). Esperando você.',
          ],
        ]),
        reviewer: stage('idle'),
      },
      counters: counters(3, 3),
      test_runs: [FAILED_RUN, FAILED_RUN, FAILED_RUN],
      escalation: {
        stage: 'tester',
        reason: 'Tester falhou 3 vezes seguidas (loop estourou)',
        epic_id: 'E2',
      },
      cost_usd: 0.42,
      tokens: 7_900,
    }),
    lane('E3', { status: 'waiting' }),
    lane('E4', {
      status: 'merged',
      stages: {
        developer: stage('done', [prep]),
        tester: stage('done', [[8, 'PASSOU · 332/332']]),
        reviewer: stage('done', [[3, 'Juntado em crew/' + taskId + ' · 3 arquivos']]),
      },
      counters: counters(1, 0),
      commit: '4e1f9a27c0d2',
      commit_message: 'feat(ui): tooltip on usage chip and now bar',
      cost_usd: 0.33,
      tokens: 5_400,
    }),
    lane('E5', {
      status: 'running',
      stages: {
        developer: stage('active', [prep, [4, 'Editando src/bodies/FolderBrowser.tsx']]),
        tester: stage('idle'),
        reviewer: stage('idle'),
      },
      counters: counters(1, 0),
      cost_usd: 0.38,
      tokens: 6_300,
    }),
    lane('E6', {
      status: 'preparing',
      stages: {
        developer: stage('active', [], 'Preparando o worktree'),
        tester: stage('idle'),
        reviewer: stage('idle'),
      },
    }),
    {
      ...base(undefined, 'REV'),
      kind: 'review',
      title: 'Review final',
      goal: `Reviewer revisa crew/${taskId} inteira depois dos épicos`,
      depends_on: SPECS.map((spec) => spec.id),
      branch: `crew/${taskId}`,
      worktree_path: null,
    },
  ]
}

/** O usuário decidiu a escalada do épico: ele volta pro Developer. */
export function resumeLane(lane: EpicView, text: string, now: Date): EpicView {
  return {
    ...lane,
    status: 'running',
    escalation: null,
    stages: {
      developer: {
        status: 'active',
        now: text,
        logs: [...lane.stages.developer.logs, { ts: now.toISOString(), text }],
      },
      tester: { ...lane.stages.tester, status: 'idle' },
      reviewer: lane.stages.reviewer,
    },
    counters: { ...lane.counters, test_attempt: 0 },
  }
}

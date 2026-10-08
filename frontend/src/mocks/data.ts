import type { InterviewQuestion, RepoInfo, TaskSummary, TaskView } from '../contracts/generated'

export const REPOS: readonly RepoInfo[] = [
  { name: 'portal-vendas', base_branch: 'main' },
  { name: 'api-pedidos', base_branch: 'main' },
]

/** Tarefas antigas fictícias (mais recente primeiro) que o `GET /api/tasks` do mock devolve. */
export const HISTORY: readonly TaskSummary[] = [
  {
    task_id: 'T-106',
    title: 'Validar CPF no cadastro de clientes',
    repo: 'api-pedidos',
    phase: 'failed',
    running: false,
    started_at: '2026-10-06T14:02:10Z',
    ended_at: '2026-10-06T14:09:40Z',
    duration_s: 450,
    cost_usd: 0.7,
    tokens: 80_000,
    commit_message: null,
    files_changed: null,
    summary: 'Rejeitar CPF inválido no cadastro, com mensagem clara pro usuário.',
  },
  {
    task_id: 'T-105',
    title: 'Dashboard de metas',
    repo: 'portal-vendas',
    phase: 'cancelled',
    running: false,
    started_at: '2026-10-06T09:30:00Z',
    ended_at: '2026-10-06T09:31:20Z',
    duration_s: 80,
    cost_usd: 0.05,
    tokens: 6_000,
    commit_message: null,
    files_changed: null,
    summary: 'Painel com as metas de vendas do mês por vendedor.',
  },
  {
    task_id: 'T-104',
    title: 'Exportar pedidos em CSV',
    repo: 'api-pedidos',
    phase: 'done',
    running: false,
    started_at: '2026-10-05T16:20:00Z',
    ended_at: '2026-10-05T16:41:35Z',
    duration_s: 1295,
    cost_usd: 2.45,
    tokens: 280_000,
    commit_message:
      'feat: exportar pedidos em CSV\n\n- endpoint GET /pedidos.csv\n- testes de borda',
    files_changed: 4,
    summary: 'feat: exportar pedidos em CSV',
  },
  {
    task_id: 'T-103',
    title: 'Filtro por intervalo de datas no relatório de vendas',
    repo: 'portal-vendas',
    phase: 'done',
    running: false,
    started_at: '2026-10-04T11:00:00Z',
    ended_at: '2026-10-04T11:12:05Z',
    duration_s: 725,
    cost_usd: 1.4,
    tokens: 160_000,
    commit_message: 'feat: filtro por intervalo de datas no relatório de vendas',
    files_changed: 3,
    summary: 'feat: filtro por intervalo de datas no relatório de vendas',
  },
]

/** Resumo da tarefa atual do mock, no formato que o backend devolveria em `GET /api/tasks`. */
export function summaryOf(view: TaskView, now: Date = new Date()): TaskSummary {
  const running = view.phase !== 'done' && view.phase !== 'cancelled' && view.phase !== 'failed'
  const end = view.ended_at ? new Date(view.ended_at) : now
  const commit = view.final?.commit_message ?? null
  const firstLine = commit?.split('\n')[0] ?? ''
  return {
    task_id: view.task_id,
    title: view.title,
    repo: view.repo,
    phase: view.phase,
    running,
    started_at: view.started_at,
    ended_at: view.ended_at,
    duration_s: Math.max(
      0,
      Math.round((end.getTime() - new Date(view.started_at).getTime()) / 1000),
    ),
    cost_usd: view.cost_usd,
    tokens: view.tokens,
    commit_message: commit,
    files_changed: view.final ? view.final.files.length : null,
    summary: firstLine === '' ? view.description : firstLine,
  }
}

/** A tarefa atual (se houver) à frente das antigas. */
export function historyOf(view: TaskView | null): TaskSummary[] {
  return view ? [summaryOf(view), ...HISTORY] : [...HISTORY]
}

/** Pasta do disco fictício. `git` ausente = pasta comum; `dirs` = subpastas por nome. */
export interface FakeFolder {
  git?: 'empty' | 'ready'
  branch?: string
  dirs?: Readonly<Record<string, FakeFolder>>
}

/** Unidades do disco fictício do navegador de pastas. */
export const FAKE_DRIVES: Readonly<Record<string, FakeFolder>> = {
  'C:': {
    dirs: {
      Users: {
        dirs: {
          voce: {
            dirs: {
              Documents: {
                dirs: {
                  'api-pedidos': { git: 'ready', branch: 'main' },
                  'blog-pessoal': { git: 'ready', branch: 'develop', dirs: { src: {} } },
                  notas: {},
                  'portal-vendas': { git: 'ready', branch: 'main' },
                  rascunho: { git: 'empty' },
                },
              },
              Downloads: {},
            },
          },
        },
      },
    },
  },
  'D:': { dirs: { Backup: {} } },
}

/** Pasta onde o navegador começa (equivale a `workspace.projects_dir`). */
export const FAKE_PROJECTS_DIR = 'C:\\Users\\voce\\Documents'

/** Caminhos dos repos de `REPOS` no disco fictício. */
export const REPO_PATHS: Readonly<Record<string, string>> = {
  'portal-vendas': 'C:\\Users\\voce\\Documents\\portal-vendas',
  'api-pedidos': 'C:\\Users\\voce\\Documents\\api-pedidos',
}

const QUESTIONS: readonly InterviewQuestion[] = [
  {
    topic: 'Fora de escopo',
    question: 'O que fica explicitamente fora do escopo desta entrega?',
    recommendation: 'Listar 1–3 coisas que ficam pra depois — evita o Developer expandir escopo.',
    options: [],
    rationale: null,
  },
  {
    topic: 'Critérios de aceite',
    question: 'Como a gente sabe que está pronto? Quais critérios o Tester deve validar?',
    recommendation: '3 critérios verificáveis por teste automatizado (entrada → saída esperada).',
    options: [
      '3 critérios verificáveis por teste automatizado (entrada → saída esperada).',
      'Só o caminho feliz; bordas ficam pra depois.',
    ],
    rationale: 'Critério verificável vira teste; o Tester sabe quando parar.',
  },
  {
    topic: 'Restrições',
    question: 'Alguma restrição técnica? (lib proibida, padrão do repo, performance)',
    recommendation: 'Seguir padrões existentes do repo; nenhuma dependência nova sem aprovação.',
    options: [
      'Seguir padrões existentes do repo; nenhuma dependência nova sem aprovação.',
      'Pode adicionar dependências se justificar no plano.',
    ],
    rationale: null,
  },
]

/** Rodadas do Entrevistador mock: as 2 perguntas independentes primeiro, depois a que depende delas. */
export const INTERVIEW_ROUNDS: readonly (readonly InterviewQuestion[])[] = [
  QUESTIONS.slice(0, 2),
  QUESTIONS.slice(2),
]

import type { InterviewQuestion, RepoInfo } from '../contracts/generated'

export const REPOS: readonly RepoInfo[] = [
  { name: 'portal-vendas', base_branch: 'main' },
  { name: 'api-pedidos', base_branch: 'main' },
]

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

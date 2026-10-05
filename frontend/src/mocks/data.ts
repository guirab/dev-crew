import type { InterviewQuestion, RepoInfo } from '../contracts/generated'

export const REPOS: readonly RepoInfo[] = [
  { name: 'portal-vendas', base_branch: 'main' },
  { name: 'api-pedidos', base_branch: 'main' },
]

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

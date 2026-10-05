import type { InterviewQuestion, RepoInfo } from '../contracts/generated'

export const REPOS: readonly RepoInfo[] = [
  { name: 'portal-vendas', base_branch: 'main' },
  { name: 'api-pedidos', base_branch: 'main' },
]

export const INTERVIEW_QUESTIONS: readonly InterviewQuestion[] = [
  {
    topic: 'Fora de escopo',
    question: 'O que fica explicitamente fora do escopo desta entrega?',
    recommendation: 'Listar 1–3 coisas que ficam pra depois — evita o Developer expandir escopo.',
    rationale: null,
  },
  {
    topic: 'Critérios de aceite',
    question: 'Como a gente sabe que está pronto? Quais critérios o Tester deve validar?',
    recommendation: '3 critérios verificáveis por teste automatizado (entrada → saída esperada).',
    rationale: null,
  },
  {
    topic: 'Restrições',
    question: 'Alguma restrição técnica? (lib proibida, padrão do repo, performance)',
    recommendation: 'Seguir padrões existentes do repo; nenhuma dependência nova sem aprovação.',
    rationale: null,
  },
]

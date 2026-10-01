import type { InterviewQuestion, RepoInfo, WorkItemSummary } from '../contracts/generated'

export const REPOS: readonly RepoInfo[] = [
  { name: 'portal-vendas', base_branch: 'main' },
  { name: 'api-pedidos', base_branch: 'main' },
]

export const WORK_ITEMS: readonly WorkItemSummary[] = [
  { id: 4830, type: 'Bug', title: 'Erro 500 ao salvar cliente sem CPF', state: 'Active' },
  { id: 4827, type: 'User Story', title: 'Dashboard de metas por vendedor', state: 'Active' },
  {
    id: 4821,
    type: 'User Story',
    title: 'Filtro por intervalo de datas no relatório de vendas',
    state: 'Active',
  },
  { id: 4819, type: 'Task', title: 'Atualizar SDK de pagamentos pra v5', state: 'New' },
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

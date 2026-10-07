import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Epic, Estimate, Plan, TaskView } from '../contracts/generated'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { ApprovalBody } from './ApprovalBody'
import { EstimateBox } from './EstimateBox'
import { selectedShare } from './PlanView'

const epic = (id: string, deps: string[] = []): Epic => ({
  id,
  title: `Épico ${id}`,
  goal: `Entrega ${id}`,
  steps: [`passo de ${id}`],
  files: [{ path: `src/${id}.ts`, change: 'A' }],
  depends_on: deps,
  acceptance_criteria: [`critério ${id}`],
  size: 'M',
})

const estimate: Estimate = {
  tokens: 300_000,
  usd: 3,
  session_pct: 60,
  weekly_pct: 6,
  sessions_needed: 1,
  usage_now: {
    plan: 'pro',
    session_pct: 10,
    session_resets_at: null,
    weekly_pct: 14,
    weekly_resets_at: null,
    fetched_at: null,
  },
  calibrated: true,
  basis: 'Execução: média de 9 jobs reais.',
  epics: [
    { epic_id: 'E1', tokens: 100_000, usd: 1 },
    { epic_id: 'E2', tokens: 100_000, usd: 1 },
    { epic_id: 'E3', tokens: 100_000, usd: 1 },
  ],
}

function splitView(): TaskView {
  const base = fixture('awaiting_approval')
  if (!base.plan) throw new Error('fixture sem plano')
  const plan: Plan = {
    ...base.plan,
    execution: 'epics',
    split_rationale: 'E1 e E2 não compartilham arquivos; E3 integra os dois.',
    epics: [epic('E1'), epic('E2'), epic('E3', ['E1', 'E2'])],
  }
  return { ...base, plan, estimate }
}

describe('plano dividido em épicos', () => {
  it('mostra a justificativa, os épicos e a estimativa', () => {
    const view = splitView()
    renderWithClient(<ApprovalBody view={view} stage={view.stages.approval} />)
    expect(screen.getByText(/E1 e E2 não compartilham arquivos/)).toBeInTheDocument()
    expect(screen.getByText('Épico E3')).toBeInTheDocument()
    expect(screen.getByText(/depende de E1, E2/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Estimativa' })).toBeInTheDocument()
    expect(screen.getByText('~$3.00')).toBeInTheDocument()
  })

  it('aprova só os épicos marcados e a estimativa acompanha', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    const view = splitView()
    renderWithClient(<ApprovalBody view={view} stage={view.stages.approval} />)

    await user.click(screen.getByRole('checkbox', { name: 'rodar E3 agora' }))
    expect(
      screen.getByRole('heading', { name: 'Estimativa dos épicos marcados' }),
    ).toBeInTheDocument()
    expect(screen.getByText('~$2.00')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Aprovar e rodar 2 épicos' }))
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'approve_plan', epics: ['E1', 'E2'] }])
    })
  })

  it('sem nenhum épico marcado não dá pra aprovar', async () => {
    const user = userEvent.setup()
    const view = splitView()
    renderWithClient(<ApprovalBody view={view} stage={view.stages.approval} />)
    for (const id of ['E1', 'E2', 'E3']) {
      await user.click(screen.getByRole('checkbox', { name: `rodar ${id} agora` }))
    }
    expect(screen.getByRole('button', { name: 'Aprovar e rodar 0 épicos' })).toBeDisabled()
  })
})

describe('EstimateBox', () => {
  it('mostra % e diz quando ainda não há calibração', () => {
    renderWithClient(
      <EstimateBox
        estimate={{
          ...estimate,
          session_pct: null,
          weekly_pct: null,
          calibrated: false,
          basis: 'sem calibração',
        }}
      />,
    )
    expect(screen.getAllByText('—')).toHaveLength(2)
    expect(screen.getByText('sem calibração')).toBeInTheDocument()
    expect(screen.getByText(/Uso agora \(plano pro\): sessão 10% · semana 14%/)).toBeInTheDocument()
  })

  it('avisa quando o plano atravessa mais de uma sessão de 5 h', () => {
    renderWithClient(<EstimateBox estimate={{ ...estimate, sessions_needed: 3 }} />)
    expect(screen.getByText(/~3 sessões de 5 h/)).toBeInTheDocument()
  })
})

describe('selectedShare', () => {
  it('fração do custo dos épicos marcados', () => {
    expect(selectedShare(estimate, new Set(['E1']))).toBeCloseTo(1 / 3)
    expect(selectedShare({ ...estimate, epics: [] }, new Set())).toBe(1)
  })
})

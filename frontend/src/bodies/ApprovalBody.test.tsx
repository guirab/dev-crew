import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Plan } from '../contracts/generated'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { ApprovalBody } from './ApprovalBody'

const view = fixture('awaiting_approval')

function withPlan(extra: Partial<Plan>): Plan {
  if (!view.plan) throw new Error('fixture sem plano')
  return { ...view.plan, ...extra }
}

const setup = () => renderWithClient(<ApprovalBody view={view} stage={view.stages.approval} />)

describe('ApprovalBody', () => {
  it('mostra o plano completo (resumo, passos, arquivos, critérios)', () => {
    setup()
    expect(screen.getByText(view.plan?.summary ?? '')).toBeInTheDocument()
    for (const step of view.plan?.steps ?? []) expect(screen.getByText(step)).toBeInTheDocument()
    for (const file of view.plan?.files ?? []) {
      expect(screen.getByText(file.path)).toBeInTheDocument()
    }
    expect(screen.getByText('Critérios de aceite', { selector: 'summary' })).toBeInTheDocument()
  })

  it('"Aprovar plano" envia approve_plan', async () => {
    const commands = captureCommands()
    setup()
    await userEvent.click(screen.getByRole('button', { name: 'Aprovar plano' }))
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'approve_plan' }])
    })
  })

  it('"Pedir ajuste" exige texto e envia adjust_plan com o texto; limpa o campo', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    setup()
    const adjust = screen.getByRole('button', { name: 'Pedir ajuste' })
    expect(adjust).toBeDisabled()

    const field = screen.getByLabelText('ajuste pro Planner (opcional)')
    await user.type(field, '  não mexer no módulo de auth ')
    await user.click(adjust)

    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'adjust_plan', text: 'não mexer no módulo de auth' },
      ])
    })
    await waitFor(() => {
      expect(field).toHaveValue('')
    })
  })

  it('fora de "waiting" só mostra o plano (sem ações)', () => {
    renderWithClient(
      <ApprovalBody view={view} stage={{ ...view.stages.approval, status: 'done' }} />,
    )
    expect(screen.queryByRole('button', { name: 'Aprovar plano' })).not.toBeInTheDocument()
    expect(screen.getByText(view.plan?.summary ?? '')).toBeInTheDocument()
  })

  it('sem plano ainda, explica quando aparece', () => {
    renderWithClient(<ApprovalBody view={fixture('planning')} stage={view.stages.approval} />)
    expect(screen.getByText('Aparece quando o Planner terminar.')).toBeInTheDocument()
  })

  it('resumo, passos e riscos à vista; o resto recolhido e abre por clique', async () => {
    const user = userEvent.setup()
    const { container } = setup()
    const plan = view.plan
    expect(screen.getByText(plan?.summary ?? '')).toBeVisible()
    for (const step of plan?.steps ?? []) expect(screen.getByText(step)).toBeVisible()
    for (const risk of plan?.risks ?? []) expect(screen.getByText(risk)).toBeVisible()

    for (const title of ['Arquivos', 'Critérios de aceite', 'Estratégia de testes']) {
      const summary = screen.getByText(title, { selector: 'summary' })
      const details = summary.closest('details')
      expect(details).not.toHaveAttribute('open')
      await user.click(summary)
      expect(details).toHaveAttribute('open')
    }
    expect(container.querySelector('pre')).toBeNull()
  })

  it('"Por que assim" fica recolhido', () => {
    const plan = withPlan({ split_rationale: 'porque sim' })
    renderWithClient(<ApprovalBody view={{ ...view, plan }} stage={view.stages.approval} />)
    const details = screen.getByText('Por que assim', { selector: 'summary' }).closest('details')
    expect(details).not.toHaveAttribute('open')
  })

  it('essential_code aparece num <pre> quando existe', () => {
    const plan = withPlan({ essential_code: 'def f() -> int: ...' })
    const { container } = renderWithClient(
      <ApprovalBody view={{ ...view, plan }} stage={view.stages.approval} />,
    )
    expect(container.querySelector('pre')).toHaveTextContent('def f() -> int: ...')
  })
})

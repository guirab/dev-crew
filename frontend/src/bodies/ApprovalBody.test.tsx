import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { ApprovalBody } from './ApprovalBody'

const view = fixture('awaiting_approval')

const setup = () => renderWithClient(<ApprovalBody view={view} stage={view.stages.approval} />)

describe('ApprovalBody', () => {
  it('mostra o plano completo (resumo, passos, arquivos, critérios)', () => {
    setup()
    expect(screen.getByText(view.plan?.summary ?? '')).toBeInTheDocument()
    for (const step of view.plan?.steps ?? []) expect(screen.getByText(step)).toBeInTheDocument()
    for (const file of view.plan?.files ?? []) {
      expect(screen.getByText(file.path)).toBeInTheDocument()
    }
    expect(screen.getByRole('heading', { name: 'Critérios de aceite' })).toBeInTheDocument()
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
})

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { UsageLimit } from '../contracts/generated'
import { captureCommands } from '../test/commands'
import { renderWithClient } from '../test/render'
import { LimitBanner } from './LimitBanner'

const limit: UsageLimit = {
  kind: 'session',
  resets_at: null,
  message: 'Limite de uso da assinatura atingido (sessão de 5 h)',
}

describe('LimitBanner', () => {
  it('diz que bateu o limite e que o trabalho parou', () => {
    renderWithClient(<LimitBanner limit={limit} />)
    expect(screen.getByRole('alert', { name: 'Limite de uso atingido' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: limit.message })).toBeInTheDocument()
    expect(screen.getByText(/Retome quando a cota da assinatura voltar/)).toBeInTheDocument()
  })

  it('mostra quando a cota volta', () => {
    const resets = new Date(Date.now() + 60 * 60 * 1000)
    renderWithClient(<LimitBanner limit={{ ...limit, resets_at: resets.toISOString() }} />)
    const hhmm = resets.toTimeString().slice(0, 5)
    expect(screen.getByText(new RegExp(`A cota volta .*${hhmm}`))).toBeInTheDocument()
  })

  it('"Retomar" envia resume_after_limit', async () => {
    const commands = captureCommands()
    renderWithClient(<LimitBanner limit={limit} />)
    await userEvent.click(screen.getByRole('button', { name: 'Retomar' }))
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'resume_after_limit' }])
    })
  })
})

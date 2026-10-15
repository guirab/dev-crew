import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { UsageChip } from './UsageChip'

function usage(fetchedAgoMs: number | null) {
  server.use(
    http.get('*/api/usage', () =>
      HttpResponse.json({
        plan: 'pro',
        session_pct: 40,
        weekly_pct: 55,
        fetched_at: fetchedAgoMs == null ? null : new Date(Date.now() - fetchedAgoMs).toISOString(),
      }),
    ),
  )
}

describe('UsageChip', () => {
  it('medição recente: só os percentuais', async () => {
    usage(30_000)
    renderWithClient(<UsageChip />)
    expect(await screen.findByText('sessão 40% · semana 55%')).toBeInTheDocument()
  })

  it('medição velha (login do CLI expirado): avisa há quanto tempo', async () => {
    usage(5 * 24 * 3_600_000)
    renderWithClient(<UsageChip />)
    const user = userEvent.setup()
    const chip = await screen.findByText(/desatualizado há 5 d/)
    expect(chip).not.toHaveAttribute('title')
    await user.hover(chip)
    expect(await screen.findByRole('tooltip')).toHaveTextContent('claude auth login')
  })

  it('sem data de medição: também é desatualizado', async () => {
    usage(null)
    renderWithClient(<UsageChip />)
    expect(await screen.findByText('sessão 40% · semana 55% · desatualizado')).toBeInTheDocument()
  })
})

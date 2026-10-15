import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { formatDuration } from '../lib/format'
import { useCrewStore } from '../store/crew'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { NowBar } from './NowBar'

function bar() {
  return screen.getByRole('region', { name: 'Agora' })
}

describe('NowBar', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('agente trabalhando: estado, linha atual e "cancelar tarefa", sem CTA', () => {
    renderWithClient(<NowBar view={fixture('developing')} />)
    expect(within(bar()).getByText('Developer trabalhando')).toBeInTheDocument()
    expect(within(bar()).getByText('Editando shop/report.py')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'cancelar tarefa' })).toBeInTheDocument()
    expect(screen.getAllByRole('button')).toHaveLength(1)
  })

  it('CTA pede foco no card que espera o usuário', async () => {
    const user = userEvent.setup()
    renderWithClient(<NowBar view={fixture('awaiting_approval')} />)
    await user.click(screen.getByRole('button', { name: 'Revisar plano ↓' }))
    expect(useCrewStore.getState().focus).toEqual({ target: 'approval', seq: 1 })
    await user.click(screen.getByRole('button', { name: 'Revisar plano ↓' }))
    expect(useCrewStore.getState().focus?.seq).toBe(2) // mesmo alvo, pedido novo
  })

  it('concluída: duração fixa, custo, sem cancelar', () => {
    const view = fixture('done')
    renderWithClient(<NowBar view={view} />)
    const seconds = (Date.parse(view.ended_at ?? '') - Date.parse(view.started_at)) / 1000
    expect(within(bar()).getByText(formatDuration(seconds))).toBeInTheDocument()
    expect(within(bar()).getByText('$1.84')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'cancelar tarefa' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ver resultado ↓' })).toBeInTheDocument()
  })

  it('com estimativa mostra custo / estimativa', () => {
    const view = fixture('developing')
    const estimate = {
      tokens: 100_000,
      usd: 4,
      session_pct: null,
      weekly_pct: null,
      sessions_needed: null,
      usage_now: null,
      calibrated: false,
      basis: '',
      epics: [],
    }
    renderWithClient(<NowBar view={{ ...view, cost_usd: 1, estimate }} />)
    expect(within(bar()).getByText('custo / estimativa')).toBeInTheDocument()
    expect(within(bar()).getByText('/ ~$4.00')).toBeInTheDocument()
  })

  it('cancelar confirma e envia cancel_task', async () => {
    const sent: unknown[] = []
    server.use(
      http.post('*/api/commands', async ({ request }) => {
        sent.push(await request.json())
        return HttpResponse.json({ ok: true })
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderWithClient(<NowBar view={fixture('developing')} />)
    await user.click(screen.getByRole('button', { name: 'cancelar tarefa' }))
    await waitFor(() => {
      expect(sent).toEqual([{ type: 'cancel_task' }])
    })
  })
})

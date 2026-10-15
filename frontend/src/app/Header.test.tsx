import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCrewStore } from '../store/crew'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { Header } from './Header'

describe('Header', () => {
  beforeEach(() => {
    server.use(
      http.get('*/api/usage', () => HttpResponse.json({ session_pct: null, weekly_pct: null })),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('mostra as duas abas sempre; "Nova tarefa" ativa por padrão', () => {
    renderWithClient(<Header view={null} />)
    expect(screen.getByRole('tab', { name: 'Nova tarefa' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: 'Histórico' })).toHaveAttribute('aria-selected', 'false')
  })

  it('clicar nas abas troca a tela e o destaque', async () => {
    const user = userEvent.setup()
    renderWithClient(<Header view={null} />)

    await user.click(screen.getByRole('tab', { name: 'Histórico' }))
    expect(useCrewStore.getState().screen).toBe('history')
    expect(screen.getByRole('tab', { name: 'Histórico' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Nova tarefa' })).toHaveAttribute(
      'aria-selected',
      'false',
    )

    await user.click(screen.getByRole('tab', { name: 'Nova tarefa' }))
    expect(useCrewStore.getState().screen).toBe('new')
    expect(screen.getByRole('tab', { name: 'Nova tarefa' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('"Nova tarefa" fica ativa também na tela da tarefa', () => {
    useCrewStore.getState().setScreen('task')
    renderWithClient(<Header view={fixture('developing')} />)
    expect(screen.getByRole('tab', { name: 'Nova tarefa' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('título da tarefa só aparece na tela da tarefa; "cancelar" mora na faixa Agora', () => {
    const view = fixture('developing')
    const { rerender } = renderWithClient(<Header view={view} />)
    expect(screen.queryByText(view.task_id)).not.toBeInTheDocument()

    useCrewStore.getState().setScreen('task')
    rerender(<Header view={view} />)
    expect(screen.getByText(view.task_id)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'cancelar tarefa' })).not.toBeInTheDocument()
  })
})

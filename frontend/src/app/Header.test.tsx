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

  it('mostra as duas abas sempre; "Tarefa" ativa por padrão', () => {
    renderWithClient(<Header />)
    expect(screen.getByRole('tab', { name: 'Tarefa' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Histórico' })).toHaveAttribute('aria-selected', 'false')
  })

  it('clicar nas abas troca a tela e o destaque; sem tarefa, "Tarefa" abre a nova', async () => {
    const user = userEvent.setup()
    renderWithClient(<Header />)

    await user.click(screen.getByRole('tab', { name: 'Histórico' }))
    expect(useCrewStore.getState().screen).toBe('history')
    expect(screen.getByRole('tab', { name: 'Histórico' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Tarefa' })).toHaveAttribute('aria-selected', 'false')

    await user.click(screen.getByRole('tab', { name: 'Tarefa' }))
    expect(useCrewStore.getState().screen).toBe('new')
  })

  it('com tarefa, "Tarefa" abre a linha do tempo e "+ Nova" abre a nova tarefa', async () => {
    const user = userEvent.setup()
    useCrewStore.getState().applyView(fixture('developing'))
    useCrewStore.getState().setScreen('history')
    renderWithClient(<Header />)

    await user.click(screen.getByRole('tab', { name: 'Tarefa' }))
    expect(useCrewStore.getState().screen).toBe('task')
    await user.click(screen.getByRole('button', { name: '+ Nova' }))
    expect(useCrewStore.getState().screen).toBe('new')
  })
})

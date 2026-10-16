import { renderHook, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { Header } from './Header'
import { useAttentionNotification } from './notify'

class FakeNotification {
  static permission: NotificationPermission = 'granted'
  static requestPermission = vi.fn(() => Promise.resolve<NotificationPermission>('granted'))
  onclick: (() => void) | null = null
  close = vi.fn()
  title: string
  options: NotificationOptions
  constructor(title: string, options: NotificationOptions) {
    this.title = title
    this.options = options
    created.push(this)
  }
}

const created: FakeNotification[] = []

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
}

const developing = fixture('developing')
const approval: TaskView = { ...fixture('awaiting_approval'), task_id: developing.task_id }

describe('useAttentionNotification', () => {
  beforeEach(() => {
    created.length = 0
    FakeNotification.permission = 'granted'
    vi.stubGlobal('Notification', FakeNotification)
    setHidden(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    setHidden(false)
  })

  it('avisa quando a tarefa passa a esperar você com a janela em segundo plano', () => {
    const { rerender } = renderHook(
      ({ view }) => {
        useAttentionNotification(view)
      },
      { initialProps: { view: developing } },
    )
    expect(created).toHaveLength(0) // 1º snapshot não avisa

    rerender({ view: approval })
    expect(created).toHaveLength(1)
    expect(created[0]?.title).toBe(`${developing.task_id} · Precisa de você: aprove o plano`)
    expect(created[0]?.options.tag).toBe(developing.task_id)

    rerender({ view: { ...approval } }) // mesmo estado: não repete
    expect(created).toHaveLength(1)
  })

  it('não avisa com a janela em primeiro plano, sem permissão ou ao trocar de tarefa', () => {
    const { rerender } = renderHook(
      ({ view }) => {
        useAttentionNotification(view)
      },
      { initialProps: { view: developing } },
    )

    setHidden(false)
    rerender({ view: approval })
    setHidden(true)
    FakeNotification.permission = 'denied'
    rerender({ view: { ...developing } })
    rerender({ view: { ...approval } })
    FakeNotification.permission = 'granted'
    rerender({ view: { ...fixture('done'), task_id: 'T-999' } })
    expect(created).toHaveLength(0)
  })

  it('clicar no aviso traz a janela e abre a tela da tarefa', () => {
    const focus = vi.spyOn(window, 'focus').mockImplementation(() => undefined)
    const { rerender } = renderHook(
      ({ view }) => {
        useAttentionNotification(view)
      },
      { initialProps: { view: developing } },
    )
    rerender({ view: approval })
    created[0]?.onclick?.()
    expect(focus).toHaveBeenCalled()
    expect(useCrewStore.getState().screen).toBe('task')
  })
})

describe('Header: ativar avisos', () => {
  beforeEach(() => {
    server.use(
      http.get('*/api/usage', () => HttpResponse.json({ session_pct: null, weekly_pct: null })),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('pede permissão uma vez e some depois de responder', async () => {
    FakeNotification.permission = 'default'
    vi.stubGlobal('Notification', FakeNotification)
    const user = userEvent.setup()
    renderWithClient(<Header />)
    await user.click(screen.getByRole('button', { name: 'ativar avisos' }))
    expect(FakeNotification.requestPermission).toHaveBeenCalled()
    expect(await screen.findByRole('tab', { name: 'Tarefa' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ativar avisos' })).not.toBeInTheDocument()
  })

  it('sem suporte a Notification não mostra o botão', () => {
    vi.stubGlobal('Notification', undefined)
    renderWithClient(<Header />)
    expect(screen.queryByRole('button', { name: 'ativar avisos' })).not.toBeInTheDocument()
  })
})

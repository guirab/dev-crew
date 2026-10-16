import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'
import { HISTORY } from '../mocks/data'
import { createRestHandlers } from '../mocks/handlers'
import { ScenarioBackend } from '../mocks/scenario'
import { useCrewStore } from '../store/crew'
import { isNodeOpen, node, nodeBody, nodeButton } from '../test/dom'
import { fixture } from '../test/fixtures'
import { server } from '../test/server'
import { renderWithClient } from '../test/render'
import { App } from './App'

/** Liga um cenário vivo ao store (faz o papel do WS) e ao REST (faz o papel do gateway). */
function wire(backend: ScenarioBackend): void {
  server.use(...createRestHandlers(backend))
  backend.subscribe((msg) => {
    const store = useCrewStore.getState()
    if (msg.type === 'view') store.applyView(msg.data)
    else store.applyProgress(msg)
  })
  useCrewStore.getState().applyView(backend.getView())
}

const SLOW = { timeout: 8000 }

type User = ReturnType<typeof userEvent.setup>

/** Começa uma tarefa pela tela "Nova tarefa" (o repo padrão é o primeiro da lista). */
async function startTask(user: User, title: string): Promise<void> {
  await screen.findByRole('combobox', { name: 'repositório' })
  await user.type(screen.getByLabelText('título'), title)
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Começar' })).toBeEnabled()
  })
  await user.click(screen.getByRole('button', { name: 'Começar' }))
}

/** Começa e aceita todas as recomendações da entrevista (2 rodadas no mock). */
async function startAndAcceptInterview(user: User, title: string): Promise<void> {
  await startTask(user, title)
  await waitFor(() => {
    expect(node('interview')).toHaveAttribute('data-tone', 'you')
  })
  for (let i = 0; i < 2; i += 1) {
    await user.click(await screen.findByRole('button', { name: 'Aceitar todas as recomendações' }))
  }
}

describe('App (UI + cenário mock, sem WS)', () => {
  let backend: ScenarioBackend
  let confirm: MockInstance<typeof window.confirm>

  beforeEach(() => {
    backend = new ScenarioBackend({ speed: 5000 })
    confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    backend.dispose()
    vi.restoreAllMocks()
  })

  it('mostra "conectando…" até o primeiro snapshot', () => {
    renderWithClient(<App />)
    expect(screen.getByText('conectando…')).toBeInTheDocument()
    expect(screen.queryByLabelText('título')).not.toBeInTheDocument()
  })

  it('título da aba e favicon acompanham a tarefa em andamento e a tela da tarefa', () => {
    const icon = () => document.querySelector('link[rel="icon"]')?.getAttribute('href')
    renderWithClient(<App />)
    expect(document.title).toBe('Dev Crew')
    expect(icon()).toBe('/favicon.svg')

    const base = fixture('interviewing')
    act(() => {
      useCrewStore.getState().applyView({
        ...base,
        phase: 'interviewing',
        stages: { ...base.stages, interviewer: { ...base.stages.interviewer, status: 'waiting' } },
      })
    })
    expect(document.title).toBe(
      `● Precisa de você: responda a entrevista · ${base.title.trim()} · Dev Crew`,
    )
    expect(icon()).toBe('/favicon-attention.svg')

    act(() => {
      useCrewStore.getState().applyView({ ...base, phase: 'done' })
    })
    expect(document.title).toBe('Dev Crew') // terminal e fora da tela da tarefa: base
    expect(icon()).toBe('/favicon.svg')

    act(() => {
      useCrewStore.getState().setScreen('task')
    })
    expect(document.title).toBe(`✓ Concluída · ${base.title.trim()} · Dev Crew`)
    expect(icon()).toBe('/favicon-done.svg')

    act(() => {
      useCrewStore.getState().setScreen('new')
    })
    expect(document.title).toBe('Dev Crew')
    expect(icon()).toBe('/favicon.svg')
  })

  it.each(['done', 'cancelled', 'failed'] as const)(
    'ao abrir ou recarregar com a última tarefa %s, a tela é a nova tarefa',
    (phase) => {
      useCrewStore.getState().applyView({ ...fixture('done'), phase })
      renderWithClient(<App />)
      expect(screen.getByRole('tab', { name: 'Tarefa' })).toHaveAttribute('aria-selected', 'true')
      expect(screen.getByRole('heading', { name: 'O que a equipe vai fazer?' })).toBeInTheDocument()
    },
  )

  it.each(['developing', 'awaiting_approval', 'escalated', 'limited'] as const)(
    'com tarefa em %s, a nova tarefa avisa e o link abre a linha do tempo',
    async (phase) => {
      const view = { ...fixture('developing'), phase }
      useCrewStore.getState().applyView(view)
      const user = userEvent.setup()
      renderWithClient(<App />)

      expect(screen.getByText(/Tarefa em andamento:/)).toHaveTextContent(view.task_id)
      await user.click(screen.getByRole('button', { name: 'ver tarefa' }))

      expect(screen.getByRole('heading', { name: view.title })).toBeInTheDocument()
      expect(node('interview')).toHaveAttribute('data-tone', 'done')
      expect(screen.queryByText(/Tarefa em andamento:/)).not.toBeInTheDocument()
    },
  )

  it('sem tarefa em andamento não há aviso', () => {
    useCrewStore.getState().applyView(fixture('done'))
    renderWithClient(<App />)
    expect(screen.queryByText(/Tarefa em andamento:/)).not.toBeInTheDocument()
  })

  it('a aba "Histórico" lista as tarefas do gateway e "+ Nova" volta à nova tarefa', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await user.click(screen.getByRole('tab', { name: 'Histórico' }))
    expect(screen.getByRole('tab', { name: 'Histórico' })).toHaveAttribute('aria-selected', 'true')
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(HISTORY.length)
    expect(screen.getByText('T-104')).toBeInTheDocument()
    expect(screen.queryByLabelText('título')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '+ Nova' }))
    expect(screen.getByLabelText('título')).toBeInTheDocument()
  })

  it('começar uma tarefa mostra a linha do tempo dela', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await startTask(user, 'Algo novo')

    expect(await screen.findByText('T-107')).toBeInTheDocument()
    expect(useCrewStore.getState().screen).toBe('task')
    expect(node('task')).toHaveAttribute('data-tone', 'done')
  })

  it('mostra a faixa "reconectando…" quando o WS cai, e a nova tarefa mesmo sem snapshot', () => {
    useCrewStore.getState().setConnection('closed')
    renderWithClient(<App />)
    expect(screen.getByRole('status')).toHaveTextContent('reconectando…')
    expect(screen.getByLabelText('título')).toBeInTheDocument()
  })

  it('fluxo completo até a conclusão, com 1º teste falhando e 1º review pedindo mudanças', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await startAndAcceptInterview(user, 'Filtro por intervalo de datas no relatório de vendas')

    expect(await screen.findByText('T-107')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'cancelar tarefa' })).toBeInTheDocument()

    // aprovação: o nó do Planner abre sozinho na sua vez
    await waitFor(() => {
      expect(node('plan')).toHaveAttribute('data-tone', 'you')
    }, SLOW)
    expect(isNodeOpen('plan')).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Aprovar plano' }))
    // aprovado: o nó vira uma linha
    await waitFor(() => {
      expect(isNodeOpen('plan')).toBe(false)
    })

    await waitFor(() => {
      expect(node('result')).toHaveAttribute('data-tone', 'done')
    }, SLOW)
    expect(isNodeOpen('result')).toBe(true)
    // concluída: commit sugerido
    expect(screen.getByText(/^feat: filtro por intervalo/)).not.toHaveTextContent('Refs:')

    // a Execução guarda a 1ª execução que falhou; o Reviewer, o veredito
    await user.click(nodeButton('execution'))
    expect(within(nodeBody('execution')).getAllByText(/48\/48/).length).toBeGreaterThan(0)
    expect(within(nodeBody('execution')).getByText('FALHOU')).toBeInTheDocument()
    await user.click(nodeButton('review'))
    expect(within(nodeBody('review')).getAllByText(/APROVADO/).length).toBeGreaterThan(0)

    // Alterações: abre pelo botão ao lado do título e volta pela linha de cima
    await user.click(screen.getByRole('button', { name: /^Alterações/ }))
    expect(screen.getByRole('heading', { name: 'Alterações' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /← T-107/ }))
    expect(node('result')).toBeInTheDocument()

    // "+ Nova" volta à nova tarefa
    await user.click(screen.getByRole('button', { name: '+ Nova' }))
    expect(screen.getByLabelText('título')).toBeInTheDocument()
    expect(screen.queryByText('T-107')).not.toBeInTheDocument()
  })

  it('entrevista (aceitar + responder), plano e aprovação', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await startTask(user, 'Exportar pedidos em CSV')
    await waitFor(() => {
      expect(node('interview')).toHaveAttribute('data-tone', 'you')
    })
    // rodada 1: aceita "Fora de escopo", responde "Critérios de aceite" com texto próprio
    const criteria = screen.getByRole('group', { name: /Critérios de aceite/ })
    await user.click(within(criteria).getByRole('radio', { name: 'Outra resposta' }))
    await user.type(within(criteria).getByRole('textbox'), 'Intervalo inclusivo')
    await user.click(screen.getByRole('button', { name: 'Enviar respostas' }))
    // rodada 2: aceita tudo
    await user.click(await screen.findByRole('button', { name: 'Aceitar todas as recomendações' }))

    await waitFor(() => {
      expect(node('plan')).toHaveAttribute('data-tone', 'you')
    }, SLOW)
    expect(isNodeOpen('interview')).toBe(false) // virou uma linha
    expect(useCrewStore.getState().view?.interview?.decisions).toHaveLength(3)
  })

  it('escalada: a Execução abre na sua vez, instrui o Developer e o fluxo segue até concluir', async () => {
    backend.setForceEscalate(true)
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await startAndAcceptInterview(user, 'Filtro por intervalo de datas')
    await waitFor(() => {
      expect(node('plan')).toHaveAttribute('data-tone', 'you')
    }, SLOW)
    await user.click(screen.getByRole('button', { name: 'Aprovar plano' }))

    await waitFor(() => {
      expect(useCrewStore.getState().view?.phase).toBe('escalated') // 3 falhas seguidas
    }, SLOW)
    expect(node('execution')).toHaveAttribute('data-tone', 'you')
    expect(isNodeOpen('execution')).toBe(true)

    await user.type(
      screen.getByLabelText('Instrução pro Developer'),
      'usar fake timers no teste de concorrência',
    )
    await user.click(screen.getByRole('button', { name: 'Enviar instrução' }))

    await waitFor(() => {
      expect(node('result')).toHaveAttribute('data-tone', 'done')
    }, SLOW)
    expect(isNodeOpen('execution')).toBe(false)
  })

  it('cancelar tarefa (com confirmação) para a linha do tempo e tira o botão de cancelar', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)
    await startTask(user, 'Dashboard de metas')
    await user.click(await screen.findByRole('button', { name: 'cancelar tarefa' }))

    expect(confirm).toHaveBeenCalledTimes(1)
    await waitFor(() => {
      expect(useCrewStore.getState().view?.phase).toBe('cancelled')
    })
    expect(document.title).toMatch(/^⊘ Cancelada/)
    expect(screen.queryByRole('button', { name: 'cancelar tarefa' })).not.toBeInTheDocument()
  })

  it('cancelar tarefa sem confirmar não envia nada', async () => {
    wire(backend)
    confirm.mockReturnValue(false)
    const user = userEvent.setup()
    renderWithClient(<App />)
    await startTask(user, 'Algo')
    await user.click(await screen.findByRole('button', { name: 'cancelar tarefa' }))
    expect(useCrewStore.getState().view?.phase).toBe('interviewing')
  })
})

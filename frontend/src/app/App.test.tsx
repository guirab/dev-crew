import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'
import { HISTORY } from '../mocks/data'
import { createRestHandlers } from '../mocks/handlers'
import { ScenarioBackend } from '../mocks/scenario'
import { useCrewStore } from '../store/crew'
import { focusPanel, isStageOpen, stageButton, stageCard } from '../test/dom'
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

/** Inicia uma tarefa manual e aceita todas as recomendações da entrevista (2 rodadas no mock). */
async function startAndAcceptInterview(user: User, title: string): Promise<void> {
  await user.click(stageButton('manual'))
  await user.type(screen.getByLabelText('título'), title)
  await user.click(screen.getByRole('button', { name: 'Iniciar' }))
  await waitFor(() => {
    expect(stageCard('interviewer')).toHaveAttribute('data-status', 'waiting')
  })
  await user.click(stageButton('interviewer'))
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
    expect(screen.queryByRole('button', { name: /Manual/ })).not.toBeInTheDocument()
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
    'ao abrir ou recarregar com a última tarefa %s, a tela é o menu de origem',
    (phase) => {
      useCrewStore.getState().applyView({ ...fixture('done'), phase })
      renderWithClient(<App />)
      expect(screen.getByRole('tab', { name: 'Nova tarefa' })).toHaveAttribute(
        'aria-selected',
        'true',
      )
      expect(screen.getByRole('button', { name: /Manual/ })).toBeInTheDocument()
      expect(stageCard('manual')).toHaveAttribute('data-status', 'pick')
    },
  )

  it.each(['developing', 'awaiting_approval', 'escalated', 'limited'] as const)(
    'com tarefa em %s, a aba "Nova tarefa" avisa e o link abre o fluxo dela',
    async (phase) => {
      const view = { ...fixture('developing'), phase }
      useCrewStore.getState().applyView(view)
      const user = userEvent.setup()
      renderWithClient(<App />)

      expect(stageCard('manual')).toHaveAttribute('data-status', 'pick')
      expect(screen.getByText(/Tarefa em andamento:/)).toHaveTextContent(view.task_id)
      await user.click(screen.getByRole('button', { name: 'ver tarefa' }))

      expect(stageCard('manual')).toHaveAttribute('data-status', 'done')
      expect(screen.getByRole('banner')).toHaveTextContent(view.title)
      expect(screen.queryByText(/Tarefa em andamento:/)).not.toBeInTheDocument()
    },
  )

  it('sem tarefa em andamento não há aviso', () => {
    useCrewStore.getState().applyView(fixture('done'))
    renderWithClient(<App />)
    expect(screen.queryByText(/Tarefa em andamento:/)).not.toBeInTheDocument()
  })

  it('a aba "Histórico" lista as tarefas do gateway e "Nova tarefa" volta ao menu', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await user.click(screen.getByRole('tab', { name: 'Histórico' }))
    expect(screen.getByRole('tab', { name: 'Histórico' })).toHaveAttribute('aria-selected', 'true')
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(HISTORY.length)
    expect(screen.getByText('T-104')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Manual/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Nova tarefa' }))
    expect(stageCard('manual')).toHaveAttribute('data-status', 'pick')
  })

  it('iniciar uma tarefa pelo Manual mostra o fluxo dela', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await user.click(stageButton('manual'))
    await user.type(screen.getByLabelText('título'), 'Algo novo')
    await user.click(screen.getByRole('button', { name: 'Iniciar' }))

    expect(await screen.findByText('T-107')).toBeInTheDocument()
    expect(useCrewStore.getState().screen).toBe('task')
    expect(stageCard('manual')).toHaveAttribute('data-status', 'done')
  })

  it('mostra a faixa "reconectando…" quando o WS cai, e mostra os cards mesmo sem snapshot', () => {
    useCrewStore.getState().setConnection('closed')
    renderWithClient(<App />)
    expect(screen.getByRole('status')).toHaveTextContent('reconectando…')
    expect(stageCard('manual')).toHaveAttribute('data-status', 'pick')
  })

  it('fluxo completo até a conclusão, com 1º teste falhando e 1º review pedindo mudanças', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await startAndAcceptInterview(user, 'Filtro por intervalo de datas no relatório de vendas')

    expect(await screen.findByText('T-107')).toBeInTheDocument() // header
    expect(stageCard('manual')).toHaveAttribute('data-status', 'done')
    expect(screen.getByRole('button', { name: 'cancelar tarefa' })).toBeInTheDocument()

    // aprovação: waiting, o foco vai sozinho pra ela
    await waitFor(() => {
      expect(stageCard('approval')).toHaveAttribute('data-status', 'waiting')
    }, SLOW)
    expect(isStageOpen('approval')).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Aprovar plano' }))
    // ao aprovar, o foco segue a ação (o usuário já agiu)
    await waitFor(() => {
      expect(isStageOpen('approval')).toBe(false)
    })

    await waitFor(() => {
      expect(stageCard('done')).toHaveAttribute('data-status', 'done')
    }, SLOW)
    expect(isStageOpen('done')).toBe(true)
    // concluída: relatório + commit
    expect(screen.getByText(/^feat: filtro por intervalo/)).not.toHaveTextContent('Refs:')

    // tester: resultado e a 1ª execução que falhou
    await user.click(stageButton('tester'))
    expect(within(focusPanel()).getAllByText(/PASSOU · 48\/48/).length).toBeGreaterThan(0)
    expect(within(focusPanel()).getByText('FALHOU')).toBeInTheDocument()
    await user.click(stageButton('reviewer'))
    expect(within(focusPanel()).getAllByText(/APROVADO/).length).toBeGreaterThan(0)

    // "Nova tarefa" volta ao menu de origem
    await user.click(screen.getByRole('tab', { name: 'Nova tarefa' }))
    expect(stageCard('manual')).toHaveAttribute('data-status', 'pick')
    expect(screen.queryByText('T-107')).not.toBeInTheDocument()
  })

  it('fluxo Manual: entrevista (aceitar + responder), plano e aprovação', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await user.click(stageButton('manual'))
    const start = screen.getByRole('button', { name: 'Iniciar' })
    expect(start).toBeDisabled() // título obrigatório
    await user.type(screen.getByLabelText('título'), 'Exportar pedidos em CSV')
    await user.type(screen.getByLabelText(/descrição · pode ser vaga/), 'Mandar pro financeiro')
    await user.click(await screen.findByRole('combobox', { name: 'repositório' }))
    await user.click(await screen.findByRole('option', { name: 'api-pedidos' }))
    await user.click(start)

    await waitFor(() => {
      expect(stageCard('interviewer')).toHaveAttribute('data-status', 'waiting')
    })
    expect(useCrewStore.getState().view?.repo).toBe('api-pedidos')

    await user.click(stageButton('interviewer'))
    // rodada 1: aceita "Fora de escopo", responde "Critérios de aceite" com texto próprio
    const criteria = screen.getByRole('group', { name: /Critérios de aceite/ })
    await user.click(within(criteria).getByRole('radio', { name: 'Outra resposta' }))
    await user.type(within(criteria).getByRole('textbox'), 'Intervalo inclusivo')
    await user.click(screen.getByRole('button', { name: 'Enviar respostas' }))
    // rodada 2: aceita tudo
    await user.click(await screen.findByRole('button', { name: 'Aceitar todas as recomendações' }))

    await waitFor(() => {
      expect(stageCard('approval')).toHaveAttribute('data-status', 'waiting')
    }, SLOW)
    expect(isStageOpen('interviewer')).toBe(false) // o foco saiu sozinho
    expect(useCrewStore.getState().view?.interview?.decisions).toHaveLength(3)
  })

  it('escalada: abre o Tester, instrui o Developer e o fluxo segue até concluir', async () => {
    backend.setForceEscalate(true)
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    await startAndAcceptInterview(user, 'Filtro por intervalo de datas')
    await waitFor(() => {
      expect(stageCard('approval')).toHaveAttribute('data-status', 'waiting')
    }, SLOW)
    await user.click(stageButton('approval'))
    await user.click(screen.getByRole('button', { name: 'Aprovar plano' }))

    await waitFor(() => {
      expect(useCrewStore.getState().view?.phase).toBe('escalated') // 3 falhas seguidas
    }, SLOW)
    expect(stageCard('tester')).toHaveAttribute('data-status', 'error')
    expect(isStageOpen('tester')).toBe(true) // o foco vai pro que precisa de você
    expect(within(focusPanel()).getAllByText(/Limite 3\/3 atingido/).length).toBeGreaterThan(0)

    await user.type(
      screen.getByLabelText('Instrução pro Developer'),
      'usar fake timers no teste de concorrência',
    )
    await user.click(screen.getByRole('button', { name: 'Enviar instrução' }))

    await waitFor(() => {
      expect(stageCard('done')).toHaveAttribute('data-status', 'done')
    }, SLOW)
    expect(isStageOpen('tester')).toBe(false)
  })

  it('cancelar tarefa (com confirmação) mostra "cancelada" e tira o botão de cancelar', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)
    await user.click(stageButton('manual'))
    await user.type(screen.getByLabelText('título'), 'Dashboard de metas')
    await user.click(screen.getByRole('button', { name: 'Iniciar' }))
    await user.click(await screen.findByRole('button', { name: 'cancelar tarefa' }))

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('⊘ Cancelada')).toBeInTheDocument() // faixa Agora
    expect(screen.queryByRole('button', { name: 'cancelar tarefa' })).not.toBeInTheDocument()
  })

  it('cancelar tarefa sem confirmar não envia nada', async () => {
    wire(backend)
    confirm.mockReturnValue(false)
    const user = userEvent.setup()
    renderWithClient(<App />)
    await user.click(stageButton('manual'))
    await user.type(screen.getByLabelText('título'), 'Algo')
    await user.click(screen.getByRole('button', { name: 'Iniciar' }))
    await user.click(await screen.findByRole('button', { name: 'cancelar tarefa' }))
    expect(useCrewStore.getState().view?.phase).toBe('interviewing')
  })

  it('erro do gateway ao iniciar aparece inline e não trava o formulário', async () => {
    wire(backend)
    server.use(
      http.post('*/api/commands', () =>
        HttpResponse.json(
          { ok: false, error: 'Já existe uma tarefa ativa.', view: null },
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWithClient(<App />)
    await user.click(stageButton('manual'))
    await user.type(screen.getByLabelText('título'), 'Algo')
    await user.click(screen.getByRole('button', { name: 'Iniciar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Já existe uma tarefa ativa.')
    expect(screen.getByRole('button', { name: 'Iniciar' })).toBeEnabled()
    expect(screen.getByLabelText('título')).toHaveValue('Algo')
  })
})

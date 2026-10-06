import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'
import { createRestHandlers } from '../mocks/handlers'
import { ScenarioBackend } from '../mocks/scenario'
import { useCrewStore } from '../store/crew'
import { stageButton, stageCard } from '../test/dom'
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

  it('título da aba e favicon acompanham o snapshot e voltam ao base ao dispensar', () => {
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
    expect(document.title).toBe(`✓ Concluída · ${base.title.trim()} · Dev Crew`)
    expect(icon()).toBe('/favicon-done.svg')

    act(() => {
      useCrewStore.getState().dismissTask()
    })
    expect(document.title).toBe('Dev Crew')
    expect(icon()).toBe('/favicon.svg')
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

    // aprovação: waiting, fechada por padrão
    await waitFor(() => {
      expect(stageCard('approval')).toHaveAttribute('data-status', 'waiting')
    }, SLOW)
    expect(stageButton('approval')).toHaveAttribute('aria-expanded', 'false')

    await user.click(stageButton('approval'))
    await user.click(screen.getByRole('button', { name: 'Aprovar plano' }))
    // ao aprovar, o card fecha sozinho (o usuário já agiu)
    await waitFor(() => {
      expect(stageButton('approval')).toHaveAttribute('aria-expanded', 'false')
    })

    await waitFor(() => {
      expect(stageCard('done')).toHaveAttribute('data-status', 'done')
    }, SLOW)
    expect(screen.getByRole('button', { name: 'Nova tarefa' })).toBeInTheDocument()
    expect(within(stageCard('tester')).getByText(/PASSOU · 48\/48/)).toBeInTheDocument()
    expect(within(stageCard('reviewer')).getByText(/APROVADO/)).toBeInTheDocument()

    // concluída: relatório + commit
    await user.click(stageButton('done'))
    expect(screen.getByText(/^feat: filtro por intervalo/)).not.toHaveTextContent('Refs:')

    // tester mostra a 1ª execução que falhou
    await user.click(stageButton('tester'))
    expect(within(stageCard('tester')).getByText('FALHOU')).toBeInTheDocument()

    // "Nova tarefa" volta ao estado inicial (só origem em pick)
    await user.click(screen.getByRole('button', { name: 'Nova tarefa' }))
    expect(stageCard('manual')).toHaveAttribute('data-status', 'pick')
    expect(stageCard('done')).toHaveAttribute('data-status', 'idle')
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
    await user.selectOptions(screen.getByLabelText('repositório'), 'api-pedidos')
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
    expect(stageButton('interviewer')).toHaveAttribute('aria-expanded', 'false') // fechou sozinho
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
    expect(within(stageCard('tester')).getByText(/Limite 3\/3 atingido/)).toBeInTheDocument()
    expect(stageButton('tester')).toHaveAttribute('aria-expanded', 'false')

    await user.click(stageButton('tester'))
    await user.type(
      screen.getByLabelText('Instrução pro Developer'),
      'usar fake timers no teste de concorrência',
    )
    await user.click(screen.getByRole('button', { name: 'Enviar instrução' }))

    await waitFor(() => {
      expect(stageCard('done')).toHaveAttribute('data-status', 'done')
    }, SLOW)
    expect(stageButton('tester')).toHaveAttribute('aria-expanded', 'false')
  })

  it('cancelar tarefa (com confirmação) mostra "cancelada" e libera "Nova tarefa"', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)
    await user.click(stageButton('manual'))
    await user.type(screen.getByLabelText('título'), 'Dashboard de metas')
    await user.click(screen.getByRole('button', { name: 'Iniciar' }))
    await user.click(await screen.findByRole('button', { name: 'cancelar tarefa' }))

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('cancelada')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Nova tarefa' })).toBeInTheDocument()
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

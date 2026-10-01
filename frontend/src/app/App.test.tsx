import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'
import { createRestHandlers } from '../mocks/handlers'
import { ScenarioBackend } from '../mocks/scenario'
import { useCrewStore } from '../store/crew'
import { stageButton, stageCard } from '../test/dom'
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
    expect(screen.queryByRole('button', { name: /Azure DevOps/ })).not.toBeInTheDocument()
  })

  it('mostra a faixa "reconectando…" quando o WS cai, e mostra os cards mesmo sem snapshot', () => {
    useCrewStore.getState().setConnection('closed')
    renderWithClient(<App />)
    expect(screen.getByRole('status')).toHaveTextContent('reconectando…')
    expect(stageCard('azure')).toHaveAttribute('data-status', 'pick')
  })

  it('fluxo Azure completo até a conclusão, com 1º teste falhando e 1º review pedindo mudanças', async () => {
    wire(backend)
    const user = userEvent.setup()
    renderWithClient(<App />)

    // origem Azure: lista work items e inicia
    await user.click(stageButton('azure'))
    await user.click(await screen.findByRole('radio', { name: /Filtro por intervalo de datas/ }))
    await user.click(screen.getByRole('button', { name: 'Iniciar' }))

    expect(await screen.findByText('T-107')).toBeInTheDocument() // header
    expect(stageCard('azure')).toHaveAttribute('data-status', 'done')
    expect(stageCard('manual')).toHaveAttribute('data-status', 'skipped')
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
    expect(screen.getByText(/^feat: filtro por intervalo/)).toHaveTextContent('Refs: AB#4821')

    // tester mostra a 1ª execução que falhou
    await user.click(stageButton('tester'))
    expect(within(stageCard('tester')).getByText('FALHOU')).toBeInTheDocument()

    // "Nova tarefa" volta ao estado inicial (só origem em pick)
    await user.click(screen.getByRole('button', { name: 'Nova tarefa' }))
    expect(stageCard('azure')).toHaveAttribute('data-status', 'pick')
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
    expect(stageCard('azure')).toHaveAttribute('data-status', 'skipped')
    expect(useCrewStore.getState().view?.repo).toBe('api-pedidos')

    await user.click(stageButton('interviewer'))
    await user.click(screen.getByRole('button', { name: 'Aceitar recomendação' }))
    await user.type(
      screen.getByRole('textbox', { name: 'Responder diferente' }),
      'Intervalo inclusivo',
    )
    await user.click(screen.getByRole('button', { name: 'Enviar' }))
    await user.click(await screen.findByRole('button', { name: 'Aceitar recomendação' }))

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

    await user.click(stageButton('azure'))
    await user.click(await screen.findByRole('radio', { name: /Filtro por intervalo/ }))
    await user.click(screen.getByRole('button', { name: 'Iniciar' }))
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
    await user.click(stageButton('azure'))
    await user.click(await screen.findByRole('radio', { name: /Dashboard de metas/ }))
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

  it('work items com erro mostram aviso e permitem tentar de novo', async () => {
    wire(backend)
    let calls = 0
    server.use(
      http.get('*/api/azure/work-items', () => {
        calls += 1
        return calls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json([{ id: 1, type: 'Bug', title: 'Item único', state: 'Active' }])
      }),
    )
    const user = userEvent.setup()
    renderWithClient(<App />)
    await user.click(stageButton('azure'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Não foi possível listar')
    await user.click(screen.getByRole('button', { name: 'Tentar de novo' }))
    expect(await screen.findByRole('radio', { name: /Item único/ })).toBeInTheDocument()
  })
})

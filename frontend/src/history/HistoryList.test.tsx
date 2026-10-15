import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { HISTORY, taskOf } from '../mocks/data'
import { resetCrewStore, useCrewStore } from '../store/crew'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { HistoryList } from './HistoryList'

describe('HistoryList', () => {
  afterEach(() => {
    resetCrewStore()
  })

  it('mostra "carregando…" e depois o estado vazio', async () => {
    renderWithClient(<HistoryList />)
    expect(screen.getByText('carregando…')).toBeInTheDocument()
    expect(await screen.findByText('Nenhuma tarefa executada ainda.')).toBeInTheDocument()
  })

  it('renderiza cada tarefa com id, título, status, repo, duração, custo, tokens e resumo', async () => {
    server.use(http.get('*/api/tasks', () => HttpResponse.json(HISTORY)))
    renderWithClient(<HistoryList />)

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(HISTORY.length)

    const [failed, cancelled, done] = items
    if (!failed || !cancelled || !done) throw new Error('itens ausentes')
    expect(within(failed).getByText('T-106')).toBeInTheDocument()
    expect(within(failed).getByText('falhou')).toBeInTheDocument()
    expect(
      within(failed).getByText(
        'Rejeitar CPF inválido no cadastro, com mensagem clara pro usuário.',
      ),
    ).toBeInTheDocument()
    expect(within(failed).getByText('7m 30s')).toBeInTheDocument()
    expect(within(failed).getByText('$0.70')).toBeInTheDocument()
    expect(within(failed).getByText('80,0 mil tokens')).toBeInTheDocument()
    expect(within(failed).queryByText(/arquivos? alterados?/)).not.toBeInTheDocument()

    expect(within(cancelled).getByText('cancelada')).toBeInTheDocument()
    expect(within(done).getByText('concluída')).toBeInTheDocument()
    expect(within(done).getByText(/feat: exportar pedidos em CSV/)).toBeInTheDocument()
    expect(within(done).getByText(/4 arquivos alterados/)).toBeInTheDocument()
    expect(within(done).getByText('api-pedidos')).toBeInTheDocument()
  })

  it('tarefa em andamento aparece como "em andamento"', async () => {
    const [first] = HISTORY
    if (!first) throw new Error('sem dados')
    server.use(
      http.get('*/api/tasks', () =>
        HttpResponse.json([{ ...first, phase: 'developing', running: true, ended_at: null }]),
      ),
    )
    renderWithClient(<HistoryList />)
    expect(await screen.findByText('em andamento')).toBeInTheDocument()
  })

  it('clicar numa tarefa antiga abre o resultado dela, só leitura, e volta pra lista', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/api/tasks', () => HttpResponse.json(HISTORY)),
      http.get('*/api/tasks/:id', ({ params }) =>
        HttpResponse.json(taskOf(null, String(params.id))),
      ),
    )
    renderWithClient(<HistoryList />)

    await user.click(await screen.findByRole('button', { name: 'Exportar pedidos em CSV' }))

    const past = await screen.findByRole('region', { name: 'Tarefa T-104' })
    expect(await within(past).findByTitle('src/export/csv.ts')).toBeInTheDocument()
    expect(within(past).getByText('concluída')).toBeInTheDocument()
    expect(within(past).getByText(/^feat: exportar pedidos em CSV/)).toBeInTheDocument()

    await user.click(within(past).getByRole('button', { name: '← Histórico' }))
    expect(await screen.findAllByRole('listitem')).toHaveLength(HISTORY.length)
  })

  it('tarefa sem resultado (falhou) avisa que não há alterações', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/api/tasks', () => HttpResponse.json(HISTORY)),
      http.get('*/api/tasks/:id', ({ params }) =>
        HttpResponse.json(taskOf(null, String(params.id))),
      ),
    )
    renderWithClient(<HistoryList />)
    await user.click(
      await screen.findByRole('button', { name: 'Validar CPF no cadastro de clientes' }),
    )
    expect(await screen.findByText(/Sem resultado/)).toBeInTheDocument()
  })

  it('a tarefa atual abre o fluxo em vez da tela de leitura', async () => {
    const user = userEvent.setup()
    const [first] = HISTORY
    if (!first) throw new Error('sem dados')
    const current = fixture('done')
    useCrewStore.setState({ view: current, screen: 'history' })
    server.use(
      http.get('*/api/tasks', () =>
        HttpResponse.json([{ ...first, task_id: current.task_id, title: current.title }]),
      ),
    )
    renderWithClient(<HistoryList />)
    await user.click(await screen.findByRole('button', { name: current.title }))
    expect(useCrewStore.getState().screen).toBe('task')
  })

  it('erro do servidor aparece como alerta', async () => {
    server.use(
      http.get('*/api/tasks', () => HttpResponse.json({ detail: 'banco fora' }, { status: 503 })),
    )
    renderWithClient(<HistoryList />)
    expect(await screen.findByRole('alert')).toHaveTextContent('banco fora')
  })
})

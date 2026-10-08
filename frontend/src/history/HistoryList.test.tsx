import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { HISTORY } from '../mocks/data'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { HistoryList } from './HistoryList'

describe('HistoryList', () => {
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

  it('itens são só informativos: sem botões nem links', async () => {
    server.use(http.get('*/api/tasks', () => HttpResponse.json(HISTORY)))
    renderWithClient(<HistoryList />)
    await screen.findAllByRole('listitem')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('erro do servidor aparece como alerta', async () => {
    server.use(
      http.get('*/api/tasks', () => HttpResponse.json({ detail: 'banco fora' }, { status: 503 })),
    )
    renderWithClient(<HistoryList />)
    expect(await screen.findByRole('alert')).toHaveTextContent('banco fora')
  })
})

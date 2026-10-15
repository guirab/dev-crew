import { act, render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { DoneBody } from './DoneBody'

const view = fixture('done')
const stage = view.stages.done

describe('DoneBody', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('mostra KPIs, arquivos alterados e a mensagem de commit sugerida', () => {
    render(<DoneBody view={view} stage={stage} />)
    const final = view.final
    expect(final).not.toBeNull()

    const kpi = (label: string) => screen.getByText(label).previousElementSibling
    expect(kpi('arquivos alterados')).toHaveTextContent('3')
    expect(kpi('execuções de teste')).toHaveTextContent(String(view.test_runs.length))
    expect(kpi('rodadas de review')).toHaveTextContent(String(view.counters.review_round))
    expect(kpi('duração')).toHaveTextContent('6m 52s') // 412s
    expect(kpi('equivalente API')).toHaveTextContent('$1.84')

    // arquivos agrupados por pasta: o caminho inteiro fica no title da linha
    expect(screen.getByTitle('shop/report.py')).toHaveTextContent('report.py')
    expect(screen.getByTitle('tests/test_report_dates.py')).toBeInTheDocument()
    expect(screen.getByText('shop/')).toBeInTheDocument()
    expect(screen.getByText(/Alterações · sample-repo · não commitado/)).toBeInTheDocument()
    expect(screen.getByText(/branch crew\/T-107/)).toBeInTheDocument()

    expect(screen.getByRole('region', { name: 'Próximo passo' })).toHaveTextContent(
      'Próximo passo: revisar e commitar',
    )
    const message = screen.getByText(/^feat: filtro por intervalo/)
    expect(message.tagName).toBe('PRE')
    expect(message).not.toHaveTextContent('Refs:')
  })

  it('copia a mensagem de commit pra área de transferência e confirma', async () => {
    const user = userEvent.setup()
    render(<DoneBody view={view} stage={stage} />)

    await user.click(screen.getByRole('button', { name: 'Copiar mensagem' }))

    expect(await navigator.clipboard.readText()).toBe(view.final?.commit_message)
    expect(screen.getByRole('button', { name: 'Copiado' })).toBeInTheDocument()
  })

  it('sem permissão de clipboard, orienta a copiar à mão', async () => {
    const user = userEvent.setup()
    render(<DoneBody view={view} stage={stage} />)
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'))

    await user.click(screen.getByRole('button', { name: 'Copiar mensagem' }))

    expect(await screen.findByRole('button', { name: 'Selecione e copie' })).toBeInTheDocument()
  })

  it('o texto do botão volta ao normal depois de um tempo', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    render(<DoneBody view={view} stage={stage} />)
    await user.click(screen.getByRole('button', { name: 'Copiar mensagem' }))
    expect(await screen.findByRole('button', { name: 'Copiado' })).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(screen.getByRole('button', { name: 'Copiar mensagem' })).toBeInTheDocument()
    vi.useRealTimers()
  })

  it('sem relatório final (ainda não concluída) mostra o texto explicativo', () => {
    const running = fixture('reviewing')
    render(<DoneBody view={running} stage={running.stages.done} />)
    expect(screen.getByText(/nada é commitado/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Copiar/ })).not.toBeInTheDocument()
  })

  it('clicar num arquivo abre o patch dele; clicar de novo fecha', async () => {
    const user = userEvent.setup()
    let asked = ''
    server.use(
      http.get('*/api/tasks/:id/diff', ({ params, request }) => {
        asked = `${String(params.id)} ${new URL(request.url).searchParams.get('path') ?? ''}`
        return HttpResponse.json({
          path: 'shop/report.py',
          status: 'M',
          patch: 'diff --git a/x b/x\r\n--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n ctx\n-old\n+new\n',
          binary: false,
          truncated: true,
        })
      }),
    )
    renderWithClient(<DoneBody view={view} stage={stage} />)

    const row = screen.getByTitle('shop/report.py')
    expect(row).toHaveAttribute('aria-expanded', 'false')
    await user.click(row)

    const patch = await screen.findByLabelText('Diff de shop/report.py')
    expect(asked).toBe('T-107 shop/report.py')
    expect(row).toHaveAttribute('aria-expanded', 'true')
    // o cabeçalho do git fica de fora: começa no hunk
    expect(patch.textContent).toBe('@@ -1,2 +1,2 @@ ctx-old+new')
    expect(screen.getByText(/Diff cortado/)).toBeInTheDocument()

    await user.click(row)
    expect(screen.queryByLabelText('Diff de shop/report.py')).not.toBeInTheDocument()
  })

  it('worktree removido: mostra o motivo no lugar do patch', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/api/tasks/:id/diff', () =>
        HttpResponse.json({ detail: 'worktree removido: diff indisponível' }, { status: 404 }),
      ),
    )
    renderWithClient(<DoneBody view={view} stage={stage} />)
    await user.click(screen.getByTitle('shop/api.py'))
    expect(await screen.findByRole('alert')).toHaveTextContent('worktree removido')
  })

  it('arquivo binário não mostra patch', async () => {
    const user = userEvent.setup()
    server.use(
      http.get('*/api/tasks/:id/diff', () =>
        HttpResponse.json({
          path: 'shop/api.py',
          status: 'M',
          patch: '',
          binary: true,
          truncated: false,
        }),
      ),
    )
    renderWithClient(<DoneBody view={view} stage={stage} />)
    await user.click(screen.getByTitle('shop/api.py'))
    expect(await screen.findByText(/Arquivo binário/)).toBeInTheDocument()
  })
})

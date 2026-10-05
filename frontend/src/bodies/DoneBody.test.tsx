import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fixture } from '../test/fixtures'
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
    expect(kpi('custo')).toHaveTextContent('$1.84')

    expect(screen.getByText('shop/report.py')).toBeInTheDocument()
    expect(screen.getByText('tests/test_report_dates.py')).toBeInTheDocument()
    expect(screen.getByText(/Alterações · sample-repo · não commitado/)).toBeInTheDocument()
    expect(screen.getByText(/branch crew\/T-107/)).toBeInTheDocument()

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
})

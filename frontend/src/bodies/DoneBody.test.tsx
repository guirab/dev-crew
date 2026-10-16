import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TaskView } from '../contracts/generated'
import { epicLane, fixture } from '../test/fixtures'
import { DoneBody } from './DoneBody'

const view = fixture('done')
const stage = view.stages.done

describe('DoneBody', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('mostra a mensagem de commit sugerida e onde ficou (sem a lista de arquivos)', () => {
    render(<DoneBody view={view} stage={stage} />)
    expect(screen.getByText('Mensagem de commit sugerida')).toBeInTheDocument()
    expect(screen.getByText(/branch crew\/T-107 .* não commitado/)).toBeInTheDocument()
    expect(screen.queryByTitle('shop/report.py')).not.toBeInTheDocument()
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

  it('lista os commits por épico e o que ficou pendente', () => {
    if (!view.final) throw new Error('fixture sem final')
    const split: TaskView = {
      ...view,
      epics: [epicLane('E1', 'merged')],
      final: {
        ...view.final,
        commits: [{ epic_id: 'E1', sha: 'abcdef123456', message: 'feat(E1): núcleo\n\ncorpo' }],
        pending_epics: ['E3'],
        plan_doc: 'docs/plano/T-7.md',
      },
    }
    render(<DoneBody view={split} stage={split.stages.done} />)
    expect(screen.getByText(/feat\(E1\): núcleo/)).toBeInTheDocument()
    expect(screen.getByText('Ficaram pendentes no plano: E3')).toBeInTheDocument()
    expect(screen.getByText('docs/plano/T-7.md')).toBeInTheDocument()
    expect(screen.getByText(/commitado na branch, sem push/)).toBeInTheDocument()
  })
})

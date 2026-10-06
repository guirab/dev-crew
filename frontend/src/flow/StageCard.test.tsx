import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { StageStatus } from '../contracts/aliases'
import { Connector } from './Connector'
import { LoopRail } from './LoopRail'
import { StageCard } from './StageCard'

const STATUSES: StageStatus[] = ['idle', 'pick', 'active', 'waiting', 'done', 'error', 'skipped']

function Harness({ status = 'idle' }: { status?: StageStatus }) {
  const [open, setOpen] = useState(false)
  return (
    <StageCard
      stageKey="tester"
      status={status}
      description="Rodando a suíte"
      open={open}
      onToggle={() => {
        setOpen((o) => !o)
      }}
    >
      <p>corpo do tester</p>
    </StageCard>
  )
}

describe('StageCard', () => {
  it.each(STATUSES)('expõe o status "%s" e a classe visual correspondente', (status) => {
    const { container } = render(<Harness status={status} />)
    const card = container.querySelector('[data-stage="tester"]')
    expect(card).toHaveAttribute('data-status', status)
    expect(card).toHaveClass(status)
  })

  it('nasce fechado: só título + descrição, sem corpo', () => {
    render(<Harness />)
    const header = screen.getByRole('button', { name: /Tester/ })
    expect(header).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('Rodando a suíte')).toBeInTheDocument()
    expect(screen.queryByText('corpo do tester')).not.toBeInTheDocument()
  })

  it('o header é um <button aria-expanded> que abre e fecha o corpo por clique', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const header = screen.getByRole('button', { name: /Tester/ })

    await user.click(header)
    expect(header).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('corpo do tester')).toBeInTheDocument()
    expect(header).toHaveAttribute('aria-controls', screen.getByRole('region').id)

    await user.click(header)
    expect(header).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('corpo do tester')).not.toBeInTheDocument()
  })

  it('abre com teclado (Enter e espaço) por ser um button nativo', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.tab()
    expect(screen.getByRole('button', { name: /Tester/ })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(screen.getByText('corpo do tester')).toBeInTheDocument()
    await user.keyboard(' ')
    expect(screen.queryByText('corpo do tester')).not.toBeInTheDocument()
  })

  it('mostra rótulo do status e contador à direita', () => {
    render(
      <StageCard
        stageKey="tester"
        status="error"
        description="Limite 3/3"
        counters={{
          dev_round: 3,
          test_attempt: 3,
          max_test_attempts: 3,
          review_round: 0,
          max_review_rounds: 2,
        }}
        open={false}
        onToggle={vi.fn()}
      />,
    )
    expect(screen.getByText('precisa de você · 3/3')).toBeInTheDocument()
    expect(screen.getByText('!')).toBeInTheDocument()
  })

  it('card de origem (sem children) não renderiza painel mesmo aberto', () => {
    render(
      <StageCard
        stageKey="manual"
        status="pick"
        description="Você descreve a tarefa"
        open
        onToggle={vi.fn()}
      />,
    )
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
  })
})

describe('Connector', () => {
  it('deriva o estado de view.edges', () => {
    const { container, rerender } = render(<Connector id="source" edges={{}} />)
    expect(container.firstElementChild).toHaveAttribute('data-state', 'idle')
    rerender(<Connector id="source" edges={{ 'ma-iv': 'on' }} />)
    expect(container.firstElementChild).toHaveAttribute('data-state', 'on')
    rerender(<Connector id="source" edges={{ 'ma-iv': 'active' }} />)
    expect(container.firstElementChild).toHaveAttribute('data-state', 'active')
  })
})

describe('LoopRail', () => {
  function Rail({ edges }: { edges: Record<string, 'on' | 'active'> }) {
    return (
      <LoopRail edges={edges}>
        <div data-stage="developer" />
        <div data-stage="tester" />
        <div data-stage="reviewer" />
      </LoopRail>
    )
  }

  it('renderiza os dois loops com o estado de ts-dv e rv-dv', () => {
    const { container } = render(<Rail edges={{ 'ts-dv': 'active', 'rv-dv': 'on' }} />)
    expect(container.querySelector('[data-loop="fail"]')).toHaveAttribute('data-state', 'active')
    expect(container.querySelector('[data-loop="adjust"]')).toHaveAttribute('data-state', 'on')
    expect(screen.getByText('↺ falhou')).toBeInTheDocument()
    expect(screen.getByText('↺ ajustes')).toBeInTheDocument()
  })

  it('posiciona os loops medindo os cards (centro do header = offsetTop + 38)', () => {
    const offsets: Record<string, number> = { developer: 100, tester: 300, reviewer: 500 }
    const spy = vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockImplementation(function (
      this: HTMLElement,
    ) {
      return offsets[this.dataset.stage ?? ''] ?? 0
    })
    const { container } = render(<Rail edges={{}} />)
    const fail = container.querySelector<HTMLElement>('[data-loop="fail"]')
    const adjust = container.querySelector<HTMLElement>('[data-loop="adjust"]')
    expect(fail?.style.top).toBe('138px')
    expect(fail?.style.height).toBe('200px')
    expect(adjust?.style.top).toBe('138px')
    expect(adjust?.style.height).toBe('400px')
    spy.mockRestore()
  })

  it('re-mede quando o ResizeObserver dispara', () => {
    let notify: () => void = () => undefined
    class CapturingObserver implements ResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        notify = () => {
          callback([], this)
        }
      }
      observe(): void {
        // sem layout
      }
      unobserve(): void {
        // sem layout
      }
      disconnect(): void {
        // sem layout
      }
    }
    const PreviousObserver = globalThis.ResizeObserver
    vi.stubGlobal('ResizeObserver', CapturingObserver)

    let tester = 300
    const spy = vi.spyOn(HTMLElement.prototype, 'offsetTop', 'get').mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.dataset.stage === 'tester' ? tester : 0
    })
    const { container } = render(<Rail edges={{}} />)
    const fail = container.querySelector<HTMLElement>('[data-loop="fail"]')
    expect(fail?.style.height).toBe('300px')

    tester = 600 // card expandiu acima do tester
    notify()
    expect(fail?.style.height).toBe('600px')
    spy.mockRestore()
    vi.stubGlobal('ResizeObserver', PreviousObserver)
  })
})

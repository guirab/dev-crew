import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Epic, EpicView, Plan, TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { captureCommands } from '../test/commands'
import { isNodeOpen, node, nodeBody, nodeButton } from '../test/dom'
import { epicLane as lane, fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { TaskTimeline } from './TaskTimeline'

const epic = (id: string, deps: string[] = []): Epic => ({
  id,
  title: `Épico ${id}`,
  goal: `objetivo ${id}`,
  steps: ['s'],
  files: [{ path: `${id}.py`, change: 'A' }],
  depends_on: deps,
  acceptance_criteria: ['ok'],
  size: 'M',
})

function splitView(lanes: EpicView[], phase: TaskView['phase'] = 'executing'): TaskView {
  const base = fixture('developing')
  if (!base.plan) throw new Error('fixture sem plano')
  const plan: Plan = {
    ...base.plan,
    execution: 'epics',
    split_rationale: 'porque',
    epics: [epic('E1'), epic('E2'), epic('E3', ['E1', 'E2'])],
  }
  const idle = { status: 'idle' as const, now: null, logs: [] }
  return {
    ...base,
    phase,
    plan,
    stages: { ...base.stages, developer: idle, tester: idle },
    epics: lanes,
  }
}

const escalatedE2 = lane('E2', 'escalated', {
  escalation: { stage: 'tester', reason: 'Tester falhou 3 vezes seguidas', epic_id: 'E2' },
  test_runs: [
    {
      type: 'test',
      ok: false,
      passed: 41,
      total: 43,
      failures: [{ test: 'csv.test.ts › escapa aspas', message: 'expected "a"' }],
      coverage: null,
      command: 'npm test',
      tests_written: [],
    },
  ],
})

const groups = () =>
  [...nodeBody('execution').querySelectorAll('section[aria-label]')].map((section) =>
    section.getAttribute('aria-label'),
  )

describe('TaskTimeline', () => {
  it('épicos agrupados por quem age; o escalado abre com a saída do Tester e as ações', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    renderWithClient(
      <TaskTimeline
        view={splitView([
          lane('E1', 'merged'),
          escalatedE2,
          lane('E3', 'waiting', { depends_on: ['E1', 'E2'] }),
          lane('E4', 'running'),
          lane('REV', 'pending', { kind: 'review', title: 'Review final' }),
        ])}
      />,
    )

    expect(node('execution')).toHaveAttribute('data-tone', 'you')
    expect(groups()).toEqual(['precisa de você', 'rodando', 'na fila', 'prontos'])
    // review final tem nó próprio, fora da lista
    expect(within(nodeBody('execution')).queryByText('Review final')).not.toBeInTheDocument()
    expect(within(node('review')).getByText('Review final')).toBeInTheDocument()
    // estado em uma palavra: quem trabalha e quem espera quem
    expect(within(nodeBody('execution')).getByText('trabalhando')).toBeInTheDocument()
    expect(within(nodeBody('execution')).getByText('espera E2')).toBeInTheDocument()

    const e2 = screen.getByRole('region', { name: 'E2 · Épico E2' })
    expect(within(e2).getByLabelText('Última saída do Tester')).toHaveTextContent(
      'csv.test.ts › escapa aspas',
    )
    expect(within(e2).queryByRole('button', { name: 'Voltar pro Planner' })).not.toBeInTheDocument()
    await user.click(within(e2).getByRole('button', { name: '+2 tentativas' }))
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'escalation', action: 'more_attempts', epic_id: 'E2' },
      ])
    })

    // abrir outro épico fecha o escalado
    await user.click(screen.getByRole('button', { name: /E4/ }))
    expect(screen.queryByRole('region', { name: 'E2 · Épico E2' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'E4 · Épico E4' })).toHaveTextContent('objetivo E4')
  })

  it('próximo lote: escolhe os pendentes e roda, ou termina aqui', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    renderWithClient(
      <TaskTimeline
        view={splitView(
          [lane('E1', 'merged'), lane('E2', 'merged'), lane('E3', 'pending')],
          'awaiting_selection',
        )}
      />,
    )
    expect(node('execution')).toHaveAttribute('data-tone', 'done')
    expect(isNodeOpen('next')).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Rodar E3' }))
    await user.click(screen.getByRole('button', { name: 'Terminar aqui' }))
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'run_epics', epics: ['E3'] },
        { type: 'finish_task' },
      ])
    })
  })

  it('execução única escalada: a decisão abre no nó Execução, sem épico', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    renderWithClient(<TaskTimeline view={fixture('escalated')} />)

    expect(node('execution')).toHaveAttribute('data-tone', 'you')
    const body = nodeBody('execution')
    expect(within(body).getByText('Loop estourou — o que fazer?')).toBeInTheDocument()
    expect(within(body).getAllByText('Loop estourou — o que fazer?')).toHaveLength(1)
    await user.type(within(body).getByLabelText('Instrução pro Developer'), 'usar fake timers')
    await user.click(within(body).getByRole('button', { name: 'Enviar instrução' }))
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'escalation', action: 'instruct', text: 'usar fake timers' },
      ])
    })
  })

  it('limite: o nó atual pausa com Retomar dentro dele', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    const view: TaskView = {
      ...fixture('developing'),
      phase: 'limited',
      limit: { kind: 'session', resets_at: null, message: 'Limite da sessão' },
    }
    renderWithClient(<TaskTimeline view={view} />)
    expect(node('execution')).toHaveAttribute('data-tone', 'pause')
    await user.click(within(nodeBody('execution')).getByRole('button', { name: 'Retomar' }))
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'resume_after_limit' }])
    })
  })

  it('nó concluído abre e fecha no clique; futuro não é clicável', async () => {
    const user = userEvent.setup()
    renderWithClient(<TaskTimeline view={fixture('developing')} />)
    expect(isNodeOpen('plan')).toBe(false)
    await user.click(nodeButton('plan'))
    expect(isNodeOpen('plan')).toBe(true)
    await user.click(nodeButton('plan'))
    expect(isNodeOpen('plan')).toBe(false)
    expect(within(node('result')).queryByRole('button')).not.toBeInTheDocument()
  })

  it('a escolha manual solta quando o nó muda de estado', async () => {
    const user = userEvent.setup()
    const base = fixture('interviewing')
    const waiting: TaskView = {
      ...base,
      stages: { ...base.stages, interviewer: { ...base.stages.interviewer, status: 'waiting' } },
    }
    const { rerender } = renderWithClient(<TaskTimeline view={waiting} />)
    expect(isNodeOpen('interview')).toBe(true)
    await user.click(nodeButton('interview'))
    expect(isNodeOpen('interview')).toBe(false)

    const answered: TaskView = {
      ...waiting,
      stages: { ...waiting.stages, interviewer: { ...waiting.stages.interviewer, status: 'done' } },
    }
    rerender(<TaskTimeline view={answered} />)
    rerender(<TaskTimeline view={waiting} />)
    expect(isNodeOpen('interview')).toBe(true)
  })

  it('concluída: "Ver alterações" abre a tela Alterações', async () => {
    const user = userEvent.setup()
    renderWithClient(<TaskTimeline view={fixture('done')} />)
    expect(isNodeOpen('result')).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Ver alterações' }))
    expect(useCrewStore.getState().screen).toBe('changes')
  })
})

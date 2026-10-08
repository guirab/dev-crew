import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { useCrewStore } from '../store/crew'
import { fixture } from '../test/fixtures'
import { RunningTaskNotice } from './RunningTaskNotice'

describe('RunningTaskNotice', () => {
  it.each(['developing', 'awaiting_approval', 'escalated', 'limited'] as const)(
    'aparece com a tarefa em %s e o link leva ao fluxo',
    async (phase) => {
      const view = { ...fixture('developing'), phase }
      useCrewStore.getState().applyView(view)
      render(<RunningTaskNotice />)

      expect(screen.getByRole('status')).toHaveTextContent(
        `Tarefa em andamento: ${view.task_id} · ${view.title}`,
      )
      await userEvent.click(screen.getByRole('button', { name: 'ver tarefa' }))
      expect(useCrewStore.getState().screen).toBe('task')
    },
  )

  it.each(['done', 'cancelled', 'failed'] as const)('some com a tarefa em %s', (phase) => {
    useCrewStore.getState().applyView({ ...fixture('done'), phase })
    render(<RunningTaskNotice />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('some sem tarefa', () => {
    render(<RunningTaskNotice />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

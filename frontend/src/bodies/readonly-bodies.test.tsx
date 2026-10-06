import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { ActivityLog } from './ActivityLog'
import { DeveloperBody } from './DeveloperBody'
import { PlannerBody } from './PlannerBody'
import { ReviewerBody } from './ReviewerBody'

describe('ReviewerBody', () => {
  it('comentários resolvidos viram RESOLVIDO; abertos mostram a severidade e file:line', () => {
    const open = {
      ...fixture('done'),
      review: {
        type: 'review' as const,
        verdict: 'changes_requested' as const,
        commit_message: null,
        comments: [
          {
            severity: 'major' as const,
            file: 'a.py',
            line: 42,
            text: 'Usar bind params',
            resolved: false,
          },
          { severity: 'minor' as const, file: 'b.ts', line: null, text: 'UTC', resolved: false },
          { severity: 'nit' as const, file: 'c.ts', line: 1, text: 'nome', resolved: true },
        ],
      },
    }
    renderWithClient(<ReviewerBody view={open} stage={open.stages.reviewer} />)
    expect(screen.getByText('MAJOR')).toBeInTheDocument()
    expect(screen.getByText('MINOR')).toBeInTheDocument()
    expect(screen.getByText('RESOLVIDO')).toBeInTheDocument()
    expect(screen.getByText('a.py:42')).toBeInTheDocument()
    expect(screen.getByText('b.ts')).toBeInTheDocument()
  })

  it('sem comentários mostra o estado vazio', () => {
    const view = fixture('reviewing')
    renderWithClient(<ReviewerBody view={view} stage={view.stages.reviewer} />)
    expect(screen.getByText('Nenhum comentário ainda.')).toBeInTheDocument()
  })
})

describe('DeveloperBody', () => {
  it('lista as rodadas com resumo e arquivos', () => {
    const view = fixture('escalated')
    renderWithClient(<DeveloperBody view={view} stage={view.stages.developer} />)
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText('#3')).toBeInTheDocument()
    expect(screen.getByText('Implementa o plano')).toBeInTheDocument()
  })

  it('sem plano aprovado, mostra o estado vazio', () => {
    const view = fixture('planning')
    renderWithClient(<DeveloperBody view={view} stage={view.stages.developer} />)
    expect(screen.getByText('Aguardando plano aprovado.')).toBeInTheDocument()
  })
})

describe('PlannerBody', () => {
  it('mostra o plano e o log de atividade', () => {
    const view = fixture('awaiting_approval')
    renderWithClient(<PlannerBody view={view} stage={view.stages.planner} />)
    expect(screen.getByText(view.plan?.summary ?? '')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Atividade' })).toBeInTheDocument()
    expect(screen.getByText('Lendo tarefa')).toBeInTheDocument()
  })
})

describe('ActivityLog', () => {
  it('não renderiza nada sem logs', () => {
    const { container } = render(<ActivityLog logs={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('mostra hora (HH:MM:SS) e texto de cada linha', () => {
    render(<ActivityLog logs={[{ ts: '2026-10-01T12:00:05Z', text: 'Plano pronto' }]} />)
    expect(screen.getByText('Plano pronto')).toBeInTheDocument()
    expect(document.querySelector('time')?.textContent).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })
})

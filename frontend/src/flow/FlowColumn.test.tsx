import { act, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import type { StageKey } from '../contracts/aliases'
import type { StageView, TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import {
  ALL_STAGES,
  isStageOpen as isOpen,
  scrollIntoViewMock,
  stageButton as header,
  stageCard as card,
} from '../test/dom'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { FlowColumn } from './FlowColumn'
import { STAGE_META } from './stages'

const withStage = (view: TaskView, key: StageKey, patch: Partial<StageView>): TaskView => ({
  ...view,
  stages: { ...view.stages, [key]: { ...view.stages[key], ...patch } },
})

describe('FlowColumn', () => {
  const scrollIntoView = scrollIntoViewMock

  beforeEach(() => {
    scrollIntoView.mockClear()
  })

  describe('sem tarefa (view null)', () => {
    it('só o card Manual fica em pick; o resto idle, com as descrições fixas', () => {
      renderWithClient(<FlowColumn view={null} />)
      expect(card('manual')).toHaveAttribute('data-status', 'pick')
      for (const key of [
        'interviewer',
        'planner',
        'approval',
        'developer',
        'tester',
        'reviewer',
        'done',
      ] as const) {
        expect(card(key)).toHaveAttribute('data-status', 'idle')
        expect(within(card(key)).getByText(STAGE_META[key].desc)).toBeInTheDocument()
      }
      expect(screen.getByText('escolha a origem da tarefa ↑')).toBeInTheDocument()
    })

    it('renderiza os 8 cards na ordem do fluxo vertical', () => {
      renderWithClient(<FlowColumn view={null} />)
      const order = Array.from(document.querySelectorAll('[data-stage]')).map((el) =>
        el.getAttribute('data-stage'),
      )
      expect(order).toEqual([
        'manual',
        'interviewer',
        'planner',
        'approval',
        'developer',
        'tester',
        'reviewer',
        'done',
      ])
    })
  })

  describe('com tarefa', () => {
    it('todos os cards nascem fechados (nada auto-expande), inclusive o que precisa de você', () => {
      renderWithClient(<FlowColumn view={fixture('escalated')} />)
      for (const key of ALL_STAGES) expect(isOpen(key)).toBe(false)
      expect(screen.queryByText('Loop estourou — o que fazer?')).not.toBeInTheDocument()
    })

    it('descrição = stage.now quando ativo/waiting/error/done; fixa quando idle ou skipped', () => {
      renderWithClient(<FlowColumn view={fixture('escalated')} />)
      expect(
        within(card('tester')).getByText('Limite 3/3 atingido — expanda pra decidir'),
      ).toBeInTheDocument()
      expect(
        within(card('planner')).getByText('Plano pronto · 4 passos, 3 arquivos'),
      ).toBeInTheDocument()
      expect(within(card('reviewer')).getByText(STAGE_META.reviewer.desc)).toBeInTheDocument()
      expect(
        within(card('manual')).getByText('Filtro por intervalo de datas no relatório de vendas'),
      ).toBeInTheDocument()
    })

    it('estados visuais e conectores vêm de view.stages/edges', () => {
      renderWithClient(<FlowColumn view={fixture('reviewing')} />)
      expect(card('reviewer')).toHaveAttribute('data-status', 'active')
      expect(card('interviewer')).toHaveAttribute('data-status', 'done')
      expect(document.querySelector('[data-connector="test"]')).toHaveAttribute(
        'data-state',
        'active',
      )
      expect(document.querySelector('[data-connector="finish"]')).toHaveAttribute(
        'data-state',
        'idle',
      )
    })

    it('tags mostram contadores (tester 3/3, developer rodada 3)', () => {
      renderWithClient(<FlowColumn view={fixture('escalated')} />)
      expect(within(card('tester')).getByText('precisa de você · 3/3')).toBeInTheDocument()
      expect(within(card('developer')).getByText('ok · rodada 3')).toBeInTheDocument()
    })
  })

  describe('expansão por clique', () => {
    it('abre e fecha só por clique do usuário', async () => {
      const user = userEvent.setup()
      renderWithClient(<FlowColumn view={fixture('escalated')} />)
      await user.click(header('tester'))
      expect(isOpen('tester')).toBe(true)
      expect(screen.getByText('Loop estourou — o que fazer?')).toBeInTheDocument()
      await user.click(header('tester'))
      expect(isOpen('tester')).toBe(false)
    })

    it('vários cards podem ficar abertos ao mesmo tempo', async () => {
      const user = userEvent.setup()
      renderWithClient(<FlowColumn view={fixture('escalated')} />)
      await user.click(header('planner'))
      await user.click(header('tester'))
      expect(isOpen('planner')).toBe(true)
      expect(isOpen('tester')).toBe(true)
    })

    it('a expansão sobrevive a novos snapshots, e o que foi digitado também', async () => {
      const user = userEvent.setup()
      const view = fixture('escalated')
      const { rerender } = renderWithClient(<FlowColumn view={view} />)
      await user.click(header('tester'))
      await user.type(screen.getByLabelText('Instrução pro Developer'), 'rascunho')

      rerender(<FlowColumn view={{ ...view, cost_usd: 2.5 }} />)
      rerender(<FlowColumn view={withStage(view, 'tester', { now: 'outra coisa' })} />)

      expect(isOpen('tester')).toBe(true)
      expect(screen.getByLabelText('Instrução pro Developer')).toHaveValue('rascunho')
    })

    it('um snapshot novo nunca abre um card sozinho', () => {
      const awaiting = fixture('awaiting_approval')
      const { rerender } = renderWithClient(<FlowColumn view={awaiting} />)
      rerender(<FlowColumn view={fixture('escalated')} />)
      for (const key of ALL_STAGES) expect(isOpen(key)).toBe(false)
    })

    it('fecha o card em que o usuário já agiu (waiting → done) e a escalada resolvida', async () => {
      const user = userEvent.setup()
      const awaiting = fixture('awaiting_approval')
      const { rerender } = renderWithClient(<FlowColumn view={awaiting} />)
      await user.click(header('approval'))
      await user.click(header('planner'))
      rerender(<FlowColumn view={withStage(awaiting, 'approval', { status: 'done' })} />)
      expect(isOpen('approval')).toBe(false)
      expect(isOpen('planner')).toBe(true) // card que o usuário abriu por conta própria fica

      const escalated = fixture('escalated')
      rerender(<FlowColumn view={escalated} />)
      await user.click(header('tester'))
      rerender(<FlowColumn view={{ ...escalated, escalation: null }} />)
      expect(isOpen('tester')).toBe(false)
    })
  })

  describe('auto-scroll pro card ativo', () => {
    it('rola pro destino da aresta ativa quando nenhum card está aberto', () => {
      const developing = fixture('developing') // active_edge ap-dv → developer
      const { rerender } = renderWithClient(<FlowColumn view={developing} />)
      expect(scrollIntoView).toHaveBeenCalledTimes(1)
      expect(scrollIntoView.mock.contexts[0]).toBe(card('developer'))

      scrollIntoView.mockClear()
      rerender(<FlowColumn view={{ ...fixture('reviewing') }} />) // ts-rv → reviewer
      expect(scrollIntoView).toHaveBeenCalledTimes(1)
      expect(scrollIntoView.mock.contexts[0]).toBe(card('reviewer'))
    })

    it('não rola enquanto houver card expandido', async () => {
      const user = userEvent.setup()
      const { rerender } = renderWithClient(<FlowColumn view={fixture('planning')} />)
      scrollIntoView.mockClear()
      await user.click(header('planner'))
      rerender(<FlowColumn view={fixture('awaiting_approval')} />)
      expect(scrollIntoView).not.toHaveBeenCalled()
    })

    it('não repete a rolagem enquanto a aresta ativa não muda', () => {
      const developing = fixture('developing')
      const { rerender } = renderWithClient(<FlowColumn view={developing} />)
      scrollIntoView.mockClear()
      rerender(<FlowColumn view={{ ...developing, cost_usd: 1 }} />)
      expect(scrollIntoView).not.toHaveBeenCalled()
    })
  })

  describe('progresso ao vivo (WS)', () => {
    it('a linha de progresso sobrepõe a descrição do estágio ativo até o próximo snapshot', () => {
      const view = fixture('developing')
      useCrewStore.getState().applyView(view)
      renderWithClient(<FlowColumn view={view} />)
      expect(
        within(card('developer')).getByText(view.stages.developer.now ?? ''),
      ).toBeInTheDocument()

      act(() => {
        useCrewStore.getState().applyProgress({
          type: 'progress',
          task_id: view.task_id,
          data: { agent: 'developer', job_id: 'j1', kind: 'tool', text: 'Editando src/novo.py' },
        })
      })
      expect(within(card('developer')).getByText('Editando src/novo.py')).toBeInTheDocument()
    })
  })

  describe('origem (SourcePicker) em modo leitura com tarefa ativa', () => {
    it('mostra título, descrição e repo, sem formulário', async () => {
      const user = userEvent.setup()
      const view = fixture('interviewing')
      renderWithClient(<FlowColumn view={view} />)
      await user.click(header('manual'))
      const panel = screen.getByRole('region', { name: /Origem/ })
      expect(within(panel).getByText(view.title)).toBeInTheDocument()
      expect(within(panel).getByText(view.description)).toBeInTheDocument()
      expect(within(panel).getByText(/Repo: sample-repo/)).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Iniciar' })).not.toBeInTheDocument()
    })
  })
})

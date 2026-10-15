import { within } from '@testing-library/react'
import { vi } from 'vitest'
import type { StageKey } from '../contracts/aliases'

export const ALL_STAGES: readonly StageKey[] = [
  'manual',
  'interviewer',
  'planner',
  'approval',
  'developer',
  'tester',
  'reviewer',
  'done',
]

/** Mock de `scrollIntoView` (jsdom não implementa). Instalado no setup global. */
export const scrollIntoViewMock = vi.fn()

/** O card de origem (tela "Nova tarefa") ou a etapa do trilho (tela da tarefa); `epics` só no trilho. */
export function stageCard(key: StageKey | 'epics'): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-stage="${key}"]`)
  if (!el) throw new Error(`card ${key} não encontrado`)
  return el
}

/** O que se clica: o header `<button aria-expanded>` do card, ou a própria aba do trilho. */
export function stageButton(key: StageKey | 'epics'): HTMLElement {
  const el = stageCard(key)
  if (el.getAttribute('role') === 'tab') return el
  const [button] = within(el).getAllByRole('button')
  if (!button) throw new Error(`header do card ${key} não encontrado`)
  return button
}

/** Card expandido ou etapa em foco no trilho. */
export const isStageOpen = (key: StageKey | 'epics'): boolean => {
  const el = stageButton(key)
  return el.getAttribute('aria-expanded') === 'true' || el.getAttribute('aria-selected') === 'true'
}

/** O painel de foco da tela da tarefa (detalhes da etapa escolhida no trilho). */
export function focusPanel(): HTMLElement {
  const el = document.getElementById('focus-panel')
  if (!el) throw new Error('painel de foco não encontrado')
  return el
}

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

export function stageCard(key: StageKey): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-stage="${key}"]`)
  if (!el) throw new Error(`card ${key} não encontrado`)
  return el
}

/** O `<button aria-expanded>` do header do card. */
export function stageButton(key: StageKey): HTMLElement {
  const [button] = within(stageCard(key)).getAllByRole('button')
  if (!button) throw new Error(`header do card ${key} não encontrado`)
  return button
}

export const isStageOpen = (key: StageKey): boolean =>
  stageButton(key).getAttribute('aria-expanded') === 'true'

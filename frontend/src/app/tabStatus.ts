import { useEffect } from 'react'
import type { StageKey, TaskPhase } from '../contracts/aliases'
import type { TaskView } from '../contracts/generated'
import { EPIC_TONE, lanesNeedingYou } from '../flow/lanes'
import { STAGE_META } from '../flow/stages'
import { reviewLane } from '../flow/timeline'

export const BASE_TITLE = 'Dev Crew'
export const TITLE_MAX = 40

export type FaviconKind = 'base' | 'attention' | 'working' | 'done' | 'error'

export const FAVICON_HREF: Record<FaviconKind, string> = {
  base: '/favicon.svg',
  attention: '/favicon-attention.svg',
  working: '/favicon-working.svg',
  done: '/favicon-done.svg',
  error: '/favicon-error.svg',
}

export interface TabStatus {
  title: string
  favicon: FaviconKind
}

const NEEDS_YOU = '● Precisa de você'

const WORKING_STAGE: Record<'planning' | 'developing' | 'testing' | 'reviewing', StageKey> = {
  planning: 'planner',
  developing: 'developer',
  testing: 'tester',
  reviewing: 'reviewer',
}

export function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function working(key: StageKey): { state: string; favicon: FaviconKind } {
  return { state: `${STAGE_META[key].title} trabalhando`, favicon: 'working' }
}

/** Estado da tarefa em uma frase + o ícone que o representa (também usado pela faixa Agora). */
export function describe(view: TaskView): { state: string; favicon: FaviconKind } {
  const phase: TaskPhase = view.phase
  switch (phase) {
    case 'interviewing':
      return view.stages.interviewer.status === 'waiting'
        ? { state: `${NEEDS_YOU}: responda a entrevista`, favicon: 'attention' }
        : working('interviewer')
    case 'awaiting_approval':
      return { state: `${NEEDS_YOU}: aprove o plano`, favicon: 'attention' }
    case 'escalated':
      return {
        state: view.escalation
          ? `${NEEDS_YOU}: escalada: ${STAGE_META[view.escalation.stage].title}`
          : `${NEEDS_YOU}: escalada`,
        favicon: 'attention',
      }
    case 'awaiting_selection':
      return { state: `${NEEDS_YOU}: escolha os próximos épicos`, favicon: 'attention' }
    case 'executing': {
      // um épico escalado não tira a tarefa de `executing` enquanto outros rodam
      const stuck = lanesNeedingYou(view.epics)
      if (stuck.length > 0) {
        return {
          state: `${NEEDS_YOU}: escalada em ${stuck.map((lane) => lane.id).join(', ')}`,
          favicon: 'attention',
        }
      }
      // o review final roda como faixa REV com a fase ainda em `executing`
      const review = reviewLane(view)
      return review && EPIC_TONE[review.status] === 'running'
        ? { state: 'Review final em andamento', favicon: 'working' }
        : { state: 'Épicos em execução', favicon: 'working' }
    }
    case 'limited':
      return { state: `${NEEDS_YOU}: limite de uso atingido`, favicon: 'error' }
    case 'planning':
    case 'developing':
    case 'testing':
    case 'reviewing':
      return working(WORKING_STAGE[phase])
    case 'done':
      return { state: '✓ Concluída', favicon: 'done' }
    case 'failed':
      return { state: '✗ Falhou', favicon: 'error' }
    case 'cancelled':
      return { state: '⊘ Cancelada', favicon: 'error' }
    default: {
      const unreachable: never = phase
      return unreachable
    }
  }
}

/** Título da aba e ícone pra tarefa ativa; `null` volta ao estado base. */
export function tabStatus(view: TaskView | null): TabStatus {
  if (!view) return { title: BASE_TITLE, favicon: 'base' }
  const { state, favicon } = describe(view)
  return {
    title: `${state} · ${truncate(view.title.trim(), TITLE_MAX)} · ${BASE_TITLE}`,
    favicon,
  }
}

/** Aplica `tabStatus(view)` a `document.title` e ao `<link rel="icon">`. */
export function useTabStatus(view: TaskView | null): void {
  const { title, favicon } = tabStatus(view)
  useEffect(() => {
    document.title = title
    let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
    if (!link) {
      link = document.createElement('link')
      link.rel = 'icon'
      link.type = 'image/svg+xml'
      document.head.appendChild(link)
    }
    link.href = FAVICON_HREF[favicon]
  }, [title, favicon])
}

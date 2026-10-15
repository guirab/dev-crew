import { useEffect, useRef, useState } from 'react'
import type { TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { ActivityFeed } from './ActivityFeed'
import { FocusPanel } from './FocusPanel'
import { LimitBanner } from './LimitBanner'
import { autoFocus, railSteps } from './rail'
import type { RailKey } from './rail'
import { FOCUS_PANEL_ID, StageRail } from './StageRail'
import styles from './TaskFlow.module.css'

const NEEDS_YOU: readonly string[] = ['waiting', 'error']

/** A etapa esperava o usuário (waiting/error) e deixou de esperar: ele agiu, ou a escalada se resolveu. */
function acted(before: TaskView, after: TaskView, key: RailKey): boolean {
  const status = (view: TaskView) => railSteps(view).find((step) => step.key === key)?.status
  const was = status(before)
  const now = status(after)
  return (
    was !== undefined && NEEDS_YOU.includes(was) && (now === undefined || !NEEDS_YOU.includes(now))
  )
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Tela da tarefa: trilho + painel de foco. Sem escolha do usuário o foco segue a ação (o que precisa
 * de você, senão o que está rodando). Clique no trilho ou CTA da faixa Agora fixa a etapa; ela solta
 * sozinha quando o usuário age nela. Monte com `key={task_id}`.
 */
export function TaskFlow({ view }: { view: TaskView }) {
  const progress = useCrewStore((s) => s.progress)
  const focus = useCrewStore((s) => s.focus)
  const steps = railSteps(view)
  const [pinned, setPinned] = useState<RailKey | null>(null)

  // Padrão "estado derivado do render anterior" (sem useEffect), como os cards antigos.
  const [previousView, setPreviousView] = useState(view)
  const [previousFocus, setPreviousFocus] = useState(focus)
  let nextPinned = pinned
  if (view !== previousView) {
    setPreviousView(view)
    if (nextPinned && acted(previousView, view, nextPinned)) nextPinned = null
  }
  if (focus !== previousFocus) {
    setPreviousFocus(focus)
    if (focus) nextPinned = focus.target
  }
  if (nextPinned !== pinned) setPinned(nextPinned)

  // CTA da faixa Agora: rola até o painel. O ref ignora um pedido feito antes de montar.
  const lastFocus = useRef(focus)
  useEffect(() => {
    if (!focus || focus === lastFocus.current) return
    lastFocus.current = focus
    document.getElementById(FOCUS_PANEL_ID)?.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'start',
    })
  }, [focus])

  const shown = steps.find((step) => step.key === nextPinned) ?? autoFocus(steps)

  return (
    <div>
      {view.phase === 'limited' && view.limit && <LimitBanner limit={view.limit} />}
      <StageRail steps={steps} edges={view.edges} selected={shown.key} onSelect={setPinned} />
      <div className={styles.grid}>
        <FocusPanel view={view} step={shown} progress={progress} />
        <ActivityFeed view={view} />
      </div>
    </div>
  )
}

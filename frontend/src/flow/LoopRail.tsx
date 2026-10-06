import { useLayoutEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import type { TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { CONNECTOR_EDGES, connectorState } from './stages'
import type { ConnectorState } from './stages'
import styles from './LoopRail.module.css'

/** Metade da altura mínima do header do card (76px): centro do ícone. */
const HEADER_CENTER = 38

function centerOf(group: HTMLElement, stage: string): number | null {
  const card = group.querySelector<HTMLElement>(`[data-stage="${stage}"]`)
  return card ? card.offsetTop + HEADER_CENTER : null
}

function place(el: HTMLElement | null, top: number, bottom: number): void {
  if (!el) return
  el.style.top = `${top}px`
  el.style.height = `${bottom - top}px`
  el.style.visibility = 'visible'
}

function stateClass(state: ConnectorState): string | undefined {
  if (state === 'on') return styles.on
  if (state === 'active') return styles.active
  return undefined
}

interface LoopRailProps {
  edges: TaskView['edges'] | null
  /** Developer, Tester e Reviewer (+ conectores): o trilho se posiciona em volta deles. */
  children: ReactNode
}

/**
 * Loops laterais "↺ falhou" (Tester → Developer) e "↺ ajustes" (Reviewer → Developer).
 * A posição vem da medição dos cards, aplicada direto no DOM (sem estado React, sem re-render);
 * ResizeObserver cobre expandir/recolher cards e resize da janela.
 */
export function LoopRail({ edges, children }: LoopRailProps) {
  const groupRef = useRef<HTMLDivElement>(null)
  const failRef = useRef<HTMLDivElement>(null)
  const adjustRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const group = groupRef.current
    if (!group) return

    const update = () => {
      const dev = centerOf(group, 'developer')
      const tester = centerOf(group, 'tester')
      const reviewer = centerOf(group, 'reviewer')
      if (dev === null || tester === null || reviewer === null) return
      place(failRef.current, dev, tester)
      place(adjustRef.current, dev, reviewer)
    }

    update()
    const observer = new ResizeObserver(update)
    observer.observe(group)
    for (const card of group.querySelectorAll('[data-stage]')) observer.observe(card)
    window.addEventListener('resize', update)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [])

  const fail = connectorState(edges, CONNECTOR_EDGES.loopFail)
  const adjust = connectorState(edges, CONNECTOR_EDGES.loopAdjust)

  return (
    <div className={styles.group} ref={groupRef}>
      <div
        ref={failRef}
        className={cx(styles.loop, stateClass(fail))}
        data-loop="fail"
        data-state={fail}
        aria-hidden="true"
        style={{ left: -20, width: 20, visibility: 'hidden' }}
      >
        <span>↺ falhou</span>
      </div>
      <div
        ref={adjustRef}
        className={cx(styles.loop, stateClass(adjust))}
        data-loop="adjust"
        data-state={adjust}
        aria-hidden="true"
        style={{ left: -40, width: 40, visibility: 'hidden' }}
      >
        <span>↺ ajustes</span>
      </div>
      {children}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import type { StageKey } from '../contracts/aliases'
import type { TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { Connector } from './Connector'
import { EpicsSection } from './EpicsSection'
import { LimitBanner } from './LimitBanner'
import { LoopRail } from './LoopRail'
import { SourcePicker } from './SourcePicker'
import type { SourceKey } from './SourcePicker'
import { StageBody } from './StageBody'
import { StageCard } from './StageCard'
import { EDGE_TARGET, emptyStage, stageDescription, stagesToCollapse, withProgress } from './stages'
import type { FlowStageKey } from './stages'
import styles from './FlowColumn.module.css'

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Fluxo vertical: render puro de `TaskView`. O único estado local é "quais cards o usuário
 * abriu" (sobrevive a snapshots; só muda por clique ou ao fechar um card em que ele já agiu).
 * Monte com `key={task_id}` pra cada tarefa começar com tudo fechado.
 */
export function FlowColumn({ view }: { view: TaskView | null }) {
  const progress = useCrewStore((s) => s.progress)
  const [open, setOpen] = useState<ReadonlySet<StageKey>>(new Set())
  const [sourceOpen, setSourceOpen] = useState<SourceKey | null>(null)

  // Padrão "estado derivado do render anterior" (sem useEffect): fecha cards em que o usuário acabou
  // de agir e abre o card que o CTA da faixa Agora pediu.
  const focus = useCrewStore((s) => s.focus)
  const [previousView, setPreviousView] = useState(view)
  const [previousFocus, setPreviousFocus] = useState(focus)
  let nextOpen = open
  if (view !== previousView) {
    setPreviousView(view)
    const toClose = stagesToCollapse(previousView, view).filter((key) => open.has(key))
    if (toClose.length > 0) nextOpen = new Set([...open].filter((key) => !toClose.includes(key)))
  }
  if (focus !== previousFocus) {
    setPreviousFocus(focus)
    if (focus && focus.target !== 'epics') nextOpen = new Set([...nextOpen, focus.target])
  }
  if (nextOpen !== open) setOpen(nextOpen)

  // Rola até o alvo do CTA; o ref ignora um pedido feito antes deste fluxo montar.
  const lastFocus = useRef(focus)
  useEffect(() => {
    if (!focus || focus === lastFocus.current) return
    lastFocus.current = focus
    document
      .getElementById(focus.target === 'epics' ? 'epics' : `stage-${focus.target}`)
      ?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }, [focus])

  // Auto-scroll pro card de destino da aresta ativa, só se nenhum card estiver aberto.
  const activeEdge = view?.active_edge ?? null
  const openCount = open.size
  const lastScrolledEdge = useRef<typeof activeEdge>(null)
  useEffect(() => {
    if (activeEdge === lastScrolledEdge.current) return
    lastScrolledEdge.current = activeEdge
    if (!activeEdge || openCount > 0) return
    document.getElementById(`stage-${EDGE_TARGET[activeEdge]}`)?.scrollIntoView({
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
      block: 'center',
    })
  }, [activeEdge, openCount])

  const toggle = (key: StageKey) => {
    setOpen((current) => {
      const next = new Set(current)
      if (!next.delete(key)) next.add(key)
      return next
    })
  }

  const edges = view?.edges ?? null

  const card = (key: FlowStageKey) => {
    const stage = view ? withProgress(view.stages[key], progress[key]) : emptyStage(key)
    return (
      <StageCard
        stageKey={key}
        status={stage.status}
        description={stageDescription(key, stage)}
        counters={view?.counters}
        open={open.has(key)}
        onToggle={() => {
          toggle(key)
        }}
      >
        <StageBody stageKey={key} view={view} stage={stage} />
      </StageCard>
    )
  }

  return (
    <div>
      {view?.phase === 'limited' && view.limit && <LimitBanner limit={view.limit} />}
      <SourcePicker view={view} open={sourceOpen} onOpenChange={setSourceOpen} />
      <Connector id="source" edges={edges} />
      {card('interviewer')}
      <Connector id="interview" edges={edges} />
      {card('planner')}
      <Connector id="plan" edges={edges} />
      {card('approval')}
      <Connector id="approval" edges={edges} />
      {view && view.epics.length > 0 ? (
        <EpicsSection view={view} />
      ) : (
        <LoopRail edges={edges}>
          {card('developer')}
          <Connector id="develop" edges={edges} />
          {card('tester')}
          <Connector id="test" edges={edges} />
          {card('reviewer')}
        </LoopRail>
      )}
      <Connector id="finish" edges={edges} />
      {card('done')}
      {!view && !sourceOpen && <p className={styles.hint}>escolha a origem da tarefa ↑</p>}
    </div>
  )
}

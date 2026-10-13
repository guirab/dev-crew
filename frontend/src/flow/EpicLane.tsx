import { useId, useState } from 'react'
import type { EpicView, TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { formatTokens } from '../lib/format'
import { Connector } from './Connector'
import {
  EPIC_CARD_STATUS,
  EPIC_STATUS_LABEL,
  laneSummary,
  laneView,
  mergeDescription,
  mergeMeta,
} from './lanes'
import { LoopRail } from './LoopRail'
import { StageBody } from './StageBody'
import { StageCard } from './StageCard'
import { stageDescription } from './stages'
import card from './StageCard.module.css'
import styles from './EpicLane.module.css'

type LaneStage = 'developer' | 'tester' | 'reviewer'

/**
 * Uma faixa de um plano dividido: o épico (ticket), a integração de um merge que conflitou ou o review
 * final. Fechada mostra status e o que está acontecendo; aberta mostra Developer → Tester → Merge (no
 * review final, Developer → Tester → Reviewer).
 */
export function EpicLane({ view, lane }: { view: TaskView; lane: EpicView }) {
  const [open, setOpen] = useState(false)
  const [openStages, setOpenStages] = useState<ReadonlySet<LaneStage>>(new Set())
  const bodyId = useId()
  const status = EPIC_CARD_STATUS[lane.status]
  const pseudo = laneView(view, lane)
  const edges = lane.edges

  const toggleStage = (key: LaneStage) => {
    setOpenStages((current) => {
      const next = new Set(current)
      if (!next.delete(key)) next.add(key)
      return next
    })
  }

  const stageCard = (key: LaneStage) => {
    const merge = key === 'reviewer' && lane.kind !== 'review'
    const stage = lane.stages[key]
    return (
      <StageCard
        stageKey={key}
        domId={`lane-${lane.id}-${key}`}
        status={stage.status}
        description={merge ? mergeDescription(stage) : stageDescription(key, stage)}
        meta={merge ? mergeMeta(stage.status) : undefined}
        counters={lane.counters}
        open={openStages.has(key)}
        onToggle={() => {
          toggleStage(key)
        }}
      >
        <StageBody stageKey={key} view={pseudo} stage={stage} />
      </StageCard>
    )
  }

  return (
    <div
      className={cx(card.card, card[status], open && card.open, styles.lane)}
      id={`lane-${lane.id}`}
      data-lane={lane.id}
      data-status={lane.status}
    >
      <button
        type="button"
        className={card.hd}
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        onClick={() => {
          setOpen((v) => !v)
        }}
      >
        <span className={card.ic} aria-hidden="true">
          {lane.kind === 'integration' ? '⇄' : lane.id}
        </span>
        <span className={card.txt}>
          <span className={card.tt}>{lane.title}</span>
          <span className={card.ds}>{laneSummary(lane)}</span>
        </span>
        <span className={card.tag}>
          {EPIC_STATUS_LABEL[lane.status]}
          {lane.tokens > 0 && ` · ${formatTokens(lane.tokens)} tok`}
        </span>
        <span className={card.chev} aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <div id={bodyId} className={cx(card.bd, styles.body)} role="region" aria-label={lane.title}>
          {lane.depends_on.length > 0 && (
            <p className={styles.meta}>depende de {lane.depends_on.join(', ')}</p>
          )}
          {lane.branch && (
            <p className={styles.meta}>
              branch {lane.branch}
              {lane.worktree_path ? ` · ${lane.worktree_path}` : ''}
            </p>
          )}
          <LoopRail edges={edges}>
            {stageCard('developer')}
            <Connector id="develop" edges={edges} />
            {stageCard('tester')}
            <Connector id="test" edges={edges} />
            {stageCard('reviewer')}
          </LoopRail>
        </div>
      )}
    </div>
  )
}

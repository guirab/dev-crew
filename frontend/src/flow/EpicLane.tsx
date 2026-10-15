import { useState } from 'react'
import type { EpicView, TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { Connector } from './Connector'
import { laneView, mergeDescription, mergeMeta } from './lanes'
import { LoopRail } from './LoopRail'
import { StageBody } from './StageBody'
import { StageCard } from './StageCard'
import { stageDescription } from './stages'
import card from './StageCard.module.css'
import styles from './EpicLane.module.css'

type LaneStage = 'developer' | 'tester' | 'reviewer'

/** O corpo aberto de uma faixa: dependências, branch e Developer → Tester → Merge/Reviewer. */
export function LaneBody({
  view,
  lane,
  id,
  className,
}: {
  view: TaskView
  lane: EpicView
  id?: string
  className?: string
}) {
  const [openStages, setOpenStages] = useState<ReadonlySet<LaneStage>>(new Set())
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
    <div id={id} className={cx(card.bd, className)} role="region" aria-label={lane.title}>
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
  )
}

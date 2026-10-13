import { useId, useState } from 'react'
import type { EpicView, TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { formatTokens } from '../lib/format'
import { LaneBody } from './EpicLane'
import { BOARD_COLUMNS, EPIC_BOARD_COLUMN, EPIC_CARD_STATUS, laneStage, laneSummary } from './lanes'
import card from './StageCard.module.css'
import styles from './EpicBoard.module.css'

/** Board kanban das faixas de um plano dividido: cada card muda de coluna sozinho com o status. */
export function EpicBoard({ view }: { view: TaskView }) {
  return (
    <div className={styles.board}>
      {BOARD_COLUMNS.map((column) => {
        const lanes = view.epics.filter((lane) => EPIC_BOARD_COLUMN[lane.status] === column.id)
        return (
          <div
            key={column.id}
            className={styles.column}
            role="group"
            aria-label={column.label}
            data-column={column.id}
          >
            <h4 className={styles.heading}>
              {column.label}
              <span className={styles.count}>{lanes.length}</span>
            </h4>
            {lanes.length === 0 && <p className={styles.empty}>nada aqui</p>}
            {lanes.map((lane) => (
              <BoardCard key={lane.id} view={view} lane={lane} />
            ))}
          </div>
        )
      })}
    </div>
  )
}

function BoardCard({ view, lane }: { view: TaskView; lane: EpicView }) {
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  const stage = laneStage(lane)

  return (
    <div
      className={cx(card.card, card[EPIC_CARD_STATUS[lane.status]], open && card.open, styles.card)}
      data-lane={lane.id}
      data-status={lane.status}
    >
      <button
        type="button"
        className={cx(card.hd, styles.hd)}
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        onClick={() => {
          setOpen((v) => !v)
        }}
      >
        <span className={styles.top}>
          <span className={cx(card.ic, styles.ic)} aria-hidden="true">
            {lane.kind === 'integration' ? '⇄' : lane.id}
          </span>
          <span className={cx(card.txt, card.tt)}>{lane.title}</span>
          <span className={card.chev} aria-hidden="true">
            ▾
          </span>
        </span>
        <span className={card.ds}>{laneSummary(lane)}</span>
        {stage && <span className={styles.stage}>etapa: {stage}</span>}
        {(lane.depends_on.length > 0 || lane.tokens > 0) && (
          <span className={card.tag}>
            {lane.depends_on.length > 0 && `depende de ${lane.depends_on.join(', ')}`}
            {lane.depends_on.length > 0 && lane.tokens > 0 && ' · '}
            {lane.tokens > 0 && `${formatTokens(lane.tokens)} tok`}
          </span>
        )}
      </button>
      {open && <LaneBody view={view} lane={lane} id={bodyId} className={styles.body} />}
    </div>
  )
}

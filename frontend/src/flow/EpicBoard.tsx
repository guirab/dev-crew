import { Fragment, useId, useState } from 'react'
import type { EpicView, TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { formatTokens } from '../lib/format'
import { LaneBody } from './EpicLane'
import {
  BOARD_COLUMNS,
  EPIC_BOARD_COLUMN,
  EPIC_CARD_STATUS,
  EPIC_STATUS_LABEL,
  laneStage,
  laneSummary,
} from './lanes'
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

/**
 * Níveis de dependência: quem não depende de ninguém fica no 1º, quem depende de algo do nível n
 * fica no n+1. O review final vem por último. Ordem de `view.epics` dentro de cada nível.
 */
export function laneLevels(lanes: readonly EpicView[]): EpicView[][] {
  const byId = new Map(lanes.map((lane) => [lane.id, lane]))
  const memo = new Map<string, number>()
  const depth = (lane: EpicView, seen: ReadonlySet<string>): number => {
    const known = memo.get(lane.id)
    if (known !== undefined) return known
    const deps = lane.depends_on.flatMap((id) => {
      const dep = byId.get(id)
      // o plano é um DAG validado no backend; o `seen` só impede loop se vier algo torto
      return dep && !seen.has(id) ? [depth(dep, new Set([...seen, id]))] : []
    })
    const value = deps.length > 0 ? Math.max(...deps) + 1 : 0
    memo.set(lane.id, value)
    return value
  }
  const others = lanes.filter((lane) => lane.kind !== 'review')
  const levels: EpicView[][] = []
  for (const lane of others) (levels[depth(lane, new Set([lane.id]))] ??= []).push(lane)
  const reviews = lanes.filter((lane) => lane.kind === 'review')
  return [...levels.filter(Boolean), ...(reviews.length > 0 ? [reviews] : [])]
}

/** As faixas em níveis de dependência, da esquerda pra direita. */
export function EpicGraph({ view }: { view: TaskView }) {
  return (
    <div className={styles.graph}>
      {laneLevels(view.epics).map((level, i) => (
        <Fragment key={level.map((lane) => lane.id).join()}>
          {i > 0 && (
            <span className={styles.arrow} aria-hidden="true">
              →
            </span>
          )}
          <div className={styles.level} role="group" aria-label={`Nível ${String(i + 1)}`}>
            {level.map((lane) => (
              <BoardCard key={lane.id} view={view} lane={lane} />
            ))}
          </div>
        </Fragment>
      ))}
    </div>
  )
}

const PIPE = ['developer', 'tester', 'reviewer'] as const

/** Dev · Test · Merge (Reviewer no review final), pintados pelo status de cada estágio. */
function MiniPipeline({ lane }: { lane: EpicView }) {
  const retries = lane.counters.dev_round - 1
  return (
    <span className={styles.pipe} aria-hidden="true">
      {PIPE.map((key) => (
        <i key={key} data-status={lane.stages[key].status}>
          {key === 'developer'
            ? 'Dev'
            : key === 'tester'
              ? 'Test'
              : lane.kind === 'review'
                ? 'Rev'
                : 'Merge'}
        </i>
      ))}
      {retries > 0 && <b title="voltas do Tester/Reviewer pro Developer">↺{retries}</b>}
    </span>
  )
}

function BoardCard({ view, lane }: { view: TaskView; lane: EpicView }) {
  const [open, setOpen] = useState(false)
  const bodyId = useId()
  const stage = laneStage(lane)
  const started = EPIC_BOARD_COLUMN[lane.status] !== 'todo'

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
          <span className={cx(card.txt, card.tt, styles.title)}>{lane.title}</span>
          <span className={card.chev} aria-hidden="true">
            ▾
          </span>
        </span>
        <span className={card.ds}>{laneSummary(lane)}</span>
        {stage && <span className={styles.stage}>etapa: {stage}</span>}
        {started && <MiniPipeline lane={lane} />}
        <span className={cx(card.tag, styles.meta)}>
          {EPIC_STATUS_LABEL[lane.status]}
          {lane.depends_on.length > 0 && ` · depende de ${lane.depends_on.join(', ')}`}
          {lane.tokens > 0 && ` · ${formatTokens(lane.tokens)} tok`}
        </span>
      </button>
      {open && <LaneBody view={view} lane={lane} id={bodyId} className={styles.body} />}
    </div>
  )
}

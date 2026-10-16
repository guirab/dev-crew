import { Fragment } from 'react'
import type { EpicView } from '../contracts/generated'
import { formatTokens } from '../lib/format'
import { EpicId, MiniPipeline } from './EpicParts'
import { BOARD_COLUMNS, EPIC_TONE, TONE_COLUMN } from './lanes'
import styles from './EpicBoard.module.css'

interface LanesProps {
  lanes: readonly EpicView[]
  /** Abre o épico no painel lateral. */
  onOpen: (id: string) => void
}

/** Board das faixas (vista alternativa): só as colunas que têm épico, cards compactos. */
export function EpicBoard({ lanes, onOpen }: LanesProps) {
  return (
    <div className={styles.board}>
      {BOARD_COLUMNS.map((column) => {
        const inColumn = lanes.filter((lane) => TONE_COLUMN[EPIC_TONE[lane.status]] === column.id)
        if (inColumn.length === 0) return null
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
              <span>{inColumn.length}</span>
            </h4>
            {inColumn.map((lane) => (
              <BoardCard key={lane.id} lane={lane} onOpen={onOpen} />
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
export function EpicGraph({ lanes, onOpen }: LanesProps) {
  return (
    <div className={styles.graph}>
      {laneLevels(lanes).map((level, i) => (
        <Fragment key={level.map((lane) => lane.id).join()}>
          {i > 0 && (
            <span className={styles.arrow} aria-hidden="true">
              →
            </span>
          )}
          <div className={styles.level} role="group" aria-label={`Nível ${String(i + 1)}`}>
            {level.map((lane) => (
              <BoardCard key={lane.id} lane={lane} onOpen={onOpen} />
            ))}
          </div>
        </Fragment>
      ))}
    </div>
  )
}

/** Card compacto: id, título em até 2 linhas, mini-pipeline e tokens. Clicar abre o painel lateral. */
function BoardCard({ lane, onOpen }: { lane: EpicView; onOpen: (id: string) => void }) {
  const started = EPIC_TONE[lane.status] !== 'queued'
  return (
    <button
      type="button"
      className={styles.card}
      data-lane={lane.id}
      data-tone={EPIC_TONE[lane.status]}
      onClick={() => {
        onOpen(lane.id)
      }}
    >
      <span className={styles.top}>
        <EpicId lane={lane} />
        <b className={styles.title}>{lane.title}</b>
      </span>
      <span className={styles.foot}>
        {started ? <MiniPipeline lane={lane} /> : <span className={styles.dim}>na fila</span>}
        {lane.tokens > 0 && <span className={styles.num}>{formatTokens(lane.tokens)} tok</span>}
      </span>
    </button>
  )
}

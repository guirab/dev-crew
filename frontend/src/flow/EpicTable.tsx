import type { KeyboardEvent } from 'react'
import { Skeleton } from '../components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '../components/ui/tooltip'
import type { EpicView } from '../contracts/generated'
import { formatTokens, formatUsd } from '../lib/format'
import { EpicBadge, EpicId, MiniPipeline } from './EpicParts'
import { EPIC_TONE, laneStage } from './lanes'
import styles from './EpicTable.module.css'

/** Texto de uma linha só, cortado com reticências; o inteiro aparece no Tooltip. */
function Truncated({
  text,
  label,
  className,
}: {
  text: string
  label?: string
  className?: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={className}>{label ?? text}</span>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  )
}

/** "E1, E2"; com muitas (o review final depende de todos) vira "6 épicos" com a lista no Tooltip. */
function deps(lane: EpicView) {
  const ids = lane.depends_on
  if (ids.length === 0) return '—'
  if (ids.length <= 3) return ids.join(', ')
  return <Truncated text={ids.join(', ')} label={`${String(ids.length)} épicos`} />
}

interface EpicTableProps {
  /** Já na ordem de exibição (`sortLanes`). */
  lanes: readonly EpicView[]
  selected: string | null
  onOpen: (id: string) => void
}

/**
 * Vista padrão dos épicos: tabela densa, uma linha por faixa, a linha inteira abre o painel lateral.
 * No celular a tabela dá lugar a uma lista de cards (troca por CSS, as duas ficam no DOM).
 */
export function EpicTable({ lanes, selected, onOpen }: EpicTableProps) {
  const onKey = (event: KeyboardEvent, id: string) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    onOpen(id)
  }

  return (
    <div className={styles.wrap}>
      <Table className={styles.table}>
        <TableHeader>
          <TableRow className={styles.head}>
            <TableHead>
              <span className="sr-only">ID</span>
            </TableHead>
            <TableHead>Épico</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className={styles.colPipe}>Pipeline</TableHead>
            <TableHead className={styles.colTok}>Tokens</TableHead>
            <TableHead className={styles.colCost}>Custo</TableHead>
            <TableHead className={styles.colDeps}>Depende</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {lanes.map((lane) => {
            const tone = EPIC_TONE[lane.status]
            const stage = laneStage(lane)
            return (
              <TableRow
                key={lane.id}
                className={styles.row}
                data-lane={lane.id}
                data-tone={tone}
                data-state={selected === lane.id ? 'selected' : undefined}
                tabIndex={0}
                aria-label={`${lane.id} · ${lane.title}`}
                onClick={() => {
                  onOpen(lane.id)
                }}
                onKeyDown={(event) => {
                  onKey(event, lane.id)
                }}
              >
                <TableCell className={styles.first}>
                  <EpicId lane={lane} />
                </TableCell>
                <TableCell className={styles.tt}>
                  <Truncated text={lane.title} className={styles.title} />
                  {lane.goal && <Truncated text={lane.goal} className={styles.goal} />}
                </TableCell>
                <TableCell>
                  <EpicBadge lane={lane} />
                  {stage && <span className={styles.stage}>{stage}</span>}
                </TableCell>
                <TableCell className={styles.colPipe}>
                  {tone === 'queued' ? (
                    <span className={styles.dim}>—</span>
                  ) : (
                    <MiniPipeline lane={lane} />
                  )}
                </TableCell>
                <TableCell className={styles.colTok}>
                  {lane.tokens > 0 ? formatTokens(lane.tokens) : '—'}
                </TableCell>
                <TableCell className={styles.colCost}>
                  {tone === 'preparing' ? (
                    <Skeleton className={styles.skel} />
                  ) : lane.cost_usd > 0 ? (
                    formatUsd(lane.cost_usd)
                  ) : (
                    '—'
                  )}
                </TableCell>
                <TableCell className={styles.colDeps}>{deps(lane)}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <EpicCards lanes={lanes} selected={selected} onOpen={onOpen} />
    </div>
  )
}

/** Celular: um card por faixa (id, título em até 2 linhas, status + etapa, pipeline e tokens). */
function EpicCards({ lanes, selected, onOpen }: EpicTableProps) {
  return (
    <ul className={styles.cards} aria-label="Épicos">
      {lanes.map((lane) => {
        const tone = EPIC_TONE[lane.status]
        const stage = laneStage(lane)
        return (
          <li key={lane.id}>
            <button
              type="button"
              className={styles.card}
              data-lane={lane.id}
              data-tone={tone}
              data-state={selected === lane.id ? 'selected' : undefined}
              aria-label={`${lane.id} · ${lane.title}`}
              onClick={() => {
                onOpen(lane.id)
              }}
            >
              <span className={styles.cardTop}>
                <EpicId lane={lane} />
                <b className={styles.cardTitle}>{lane.title}</b>
              </span>
              <span className={styles.cardRow}>
                <EpicBadge lane={lane} />
                {stage && <span className={styles.stageInline}>{stage}</span>}
              </span>
              {tone !== 'queued' && (
                <span className={styles.cardRow}>
                  <MiniPipeline lane={lane} />
                  {lane.tokens > 0 && (
                    <span className={styles.num}>{formatTokens(lane.tokens)} tok</span>
                  )}
                </span>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

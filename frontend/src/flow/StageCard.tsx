import { useId } from 'react'
import type { ReactNode } from 'react'
import type { StageKey, StageStatus } from '../contracts/aliases'
import type { Counters } from '../contracts/generated'
import { cx } from '../lib/cx'
import { STAGE_META, stageIcon, stageTag } from './stages'
import styles from './StageCard.module.css'

interface StageCardProps {
  stageKey: StageKey
  status: StageStatus
  /** Texto a mostrar no lugar da descrição fixa (já resolvido por `stageDescription`). */
  description: string
  counters?: Counters | null
  open: boolean
  onToggle: () => void
  /** Id do painel controlado pelo header. Gerado se omitido. */
  panelId?: string
  /** Conteúdo exibido só quando aberto. Sem `children`, o card é só o header. */
  children?: ReactNode
}

/** Card de estágio: título + descrição fechados; detalhes só ao expandir por clique. */
export function StageCard({
  stageKey,
  status,
  description,
  counters,
  open,
  onToggle,
  panelId,
  children,
}: StageCardProps) {
  const generatedId = useId()
  const bodyId = panelId ?? generatedId
  const meta = STAGE_META[stageKey]
  const tag = stageTag(stageKey, status, counters)

  return (
    <div
      className={cx(styles.card, styles[status], open && styles.open)}
      id={`stage-${stageKey}`}
      data-stage={stageKey}
      data-status={status}
    >
      <button
        type="button"
        className={styles.hd}
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        onClick={onToggle}
      >
        <span className={styles.ic} aria-hidden="true">
          {stageIcon(stageKey, status)}
        </span>
        <span className={styles.txt}>
          <span className={styles.tt}>{meta.title}</span>
          <span className={styles.ds}>{description}</span>
        </span>
        <span className={styles.tag}>{tag}</span>
        <span className={styles.chev} aria-hidden="true">
          ▾
        </span>
      </button>
      {open && children !== undefined && (
        <div id={bodyId} className={styles.bd} role="region" aria-label={meta.title}>
          {children}
        </div>
      )}
    </div>
  )
}

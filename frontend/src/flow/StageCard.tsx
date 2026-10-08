import { useId } from 'react'
import type { ReactNode } from 'react'
import type { StageKey, StageStatus } from '../contracts/aliases'
import type { Counters } from '../contracts/generated'
import { cx } from '../lib/cx'
import { STAGE_META, stageIcon, stageProgress, stageTag } from './stages'
import type { StageMeta, StageProgress } from './stages'
import styles from './StageCard.module.css'

function ProgressBar({ progress }: { progress: StageProgress }) {
  const determinate = progress.kind === 'determinate'
  return (
    <span
      className={cx(styles.bar, !determinate && styles.indeterminate)}
      role="progressbar"
      aria-label="Progresso da etapa"
      aria-valuemin={determinate ? 0 : undefined}
      aria-valuemax={determinate ? 100 : undefined}
      aria-valuenow={determinate ? Math.round(progress.value * 100) : undefined}
    >
      <span
        className={styles.fill}
        style={determinate ? { width: `${String(progress.value * 100)}%` } : undefined}
      />
    </span>
  )
}

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
  /** Id do card no DOM (padrão `stage-<key>`); faixas de épico usam um prefixo próprio. */
  domId?: string
  /** Título/ícone próprios de um card que não é um estágio (ex.: origem "Novo projeto"). */
  meta?: StageMeta
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
  domId,
  meta: metaOverride,
  children,
}: StageCardProps) {
  const generatedId = useId()
  const bodyId = panelId ?? generatedId
  const meta = metaOverride ?? STAGE_META[stageKey]
  const tag = stageTag(stageKey, status, counters)
  const progress = metaOverride ? null : stageProgress(stageKey, status, counters)

  return (
    <div
      className={cx(styles.card, styles[status], open && styles.open)}
      id={domId ?? `stage-${stageKey}`}
      data-stage={metaOverride ? undefined : stageKey}
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
          {metaOverride ? metaOverride.icon : stageIcon(stageKey, status)}
        </span>
        <span className={styles.txt}>
          <span className={styles.tt}>{meta.title}</span>
          <span className={styles.ds}>{description}</span>
          {progress && <ProgressBar progress={progress} />}
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

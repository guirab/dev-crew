import { Badge } from '../components/ui/badge'
import type { EpicView } from '../contracts/generated'
import { EPIC_STATUS_LABEL, EPIC_TONE } from './lanes'
import styles from './EpicParts.module.css'

/** O id da faixa num quadradinho (⇄ na integração de um merge com conflito). */
export function EpicId({ lane }: { lane: EpicView }) {
  return <span className={styles.id}>{lane.kind === 'integration' ? '⇄' : lane.id}</span>
}

/** Status da faixa: só ele fica vermelho quando ela precisa de você. */
export function EpicBadge({ lane }: { lane: EpicView }) {
  return (
    <Badge variant="outline" className={styles.badge} data-tone={EPIC_TONE[lane.status]}>
      {EPIC_STATUS_LABEL[lane.status]}
    </Badge>
  )
}

const PIPE = ['developer', 'tester', 'reviewer'] as const

/** Dev · Test · Merge (Rev no review final), pintados pelo status de cada estágio, e as voltas pro Developer. */
export function MiniPipeline({ lane }: { lane: EpicView }) {
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

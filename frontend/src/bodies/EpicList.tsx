import type { Epic, EpicEstimate } from '../contracts/generated'
import { formatTokens, formatUsd } from '../lib/format'
import styles from './EpicList.module.css'
import b from './body.module.css'

const SIZE_LABEL = { S: 'P', M: 'M', L: 'G' } as const

export interface EpicSelection {
  selected: ReadonlySet<string>
  onToggle: (epicId: string) => void
  /** Épicos que já rodaram (ou estão rodando) e não podem ser marcados de novo. */
  locked?: ReadonlySet<string>
}

/** Épicos do plano dividido (D53). Com `selection`, cada um ganha "rodar agora". */
export function EpicList({
  epics,
  estimates = [],
  selection,
}: {
  epics: readonly Epic[]
  estimates?: readonly EpicEstimate[]
  selection?: EpicSelection
}) {
  const estimateOf = new Map(estimates.map((e) => [e.epic_id, e]))
  return (
    <div className={b.sec}>
      <h4>Épicos ({epics.length})</h4>
      <ol className={styles.list}>
        {epics.map((epic) => {
          const estimate = estimateOf.get(epic.id)
          const locked = selection?.locked?.has(epic.id) ?? false
          return (
            <li key={epic.id} className={styles.epic}>
              <div className={styles.head}>
                {selection && (
                  <input
                    type="checkbox"
                    aria-label={`rodar ${epic.id} agora`}
                    checked={selection.selected.has(epic.id)}
                    disabled={locked}
                    onChange={() => {
                      selection.onToggle(epic.id)
                    }}
                  />
                )}
                <b className={b.mono}>{epic.id}</b>
                <span className={styles.title}>{epic.title}</span>
                <span className={styles.size} title="tamanho">
                  {SIZE_LABEL[epic.size]}
                </span>
              </div>
              <p className={styles.goal}>{epic.goal}</p>
              <p className={styles.meta}>
                {epic.depends_on.length > 0
                  ? `depende de ${epic.depends_on.join(', ')}`
                  : 'sem dependências'}
                {' · '}
                {epic.files.length} arquivo{epic.files.length === 1 ? '' : 's'}
                {estimate &&
                  ` · ~${formatTokens(estimate.tokens)} tokens · ~${formatUsd(estimate.usd)}`}
              </p>
              <details className={styles.details}>
                <summary>passos, arquivos e critérios</summary>
                <ol>
                  {epic.steps.map((step, i) => (
                    <li key={`${i}|${step}`}>{step}</li>
                  ))}
                </ol>
                <div className={b.chips}>
                  {epic.files.map((file) => (
                    <span key={file.path} className={b.chip} data-change={file.change}>
                      {file.path}
                    </span>
                  ))}
                </div>
                <ul>
                  {epic.acceptance_criteria.map((criterion, i) => (
                    <li key={`${i}|${criterion}`}>{criterion}</li>
                  ))}
                </ul>
              </details>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

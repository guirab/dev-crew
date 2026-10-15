import { Fragment } from 'react'
import type { TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import type { RailKey, RailStep } from './rail'
import { CONNECTOR_EDGES, connectorState } from './stages'
import styles from './StageRail.module.css'

export const FOCUS_PANEL_ID = 'focus-panel'

interface StageRailProps {
  steps: readonly RailStep[]
  edges: TaskView['edges']
  selected: RailKey
  onSelect: (key: RailKey) => void
}

/** Trilho horizontal do pipeline: cada etapa é uma aba que mostra os detalhes no painel de foco. */
export function StageRail({ steps, edges, selected, onSelect }: StageRailProps) {
  return (
    <div role="tablist" aria-label="Etapas da tarefa" className={styles.rail}>
      {steps.map((step) => (
        <Fragment key={step.key}>
          {step.connector && (
            <span
              className={styles.seg}
              data-connector={step.connector}
              data-state={connectorState(edges, CONNECTOR_EDGES[step.connector])}
              aria-hidden="true"
            />
          )}
          <button
            type="button"
            role="tab"
            id={`step-${step.key}`}
            aria-selected={selected === step.key}
            aria-controls={FOCUS_PANEL_ID}
            data-stage={step.key}
            data-status={step.status}
            className={cx(styles.step, styles[step.status])}
            onClick={() => {
              onSelect(step.key)
            }}
          >
            <span className={styles.dot} aria-hidden="true">
              {step.icon}
            </span>
            <span className={styles.label}>{step.title}</span>
            {step.lanes && (
              <span className={styles.lanes} aria-hidden="true">
                {step.lanes.map((status, i) => (
                  <i key={i} data-lane-status={status} />
                ))}
              </span>
            )}
            {step.tag && <span className={styles.tag}>{step.tag}</span>}
          </button>
        </Fragment>
      ))}
    </div>
  )
}

import type { TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { CONNECTOR_EDGES, connectorState } from './stages'
import type { ConnectorId, ConnectorState } from './stages'
import styles from './Connector.module.css'

interface ConnectorProps {
  id: ConnectorId
  edges: TaskView['edges'] | null
}

/** Linha vertical entre cards. O estado vem só de `view.edges`. */
export function Connector({ id, edges }: ConnectorProps) {
  const state: ConnectorState = connectorState(edges, CONNECTOR_EDGES[id])
  return (
    <div
      className={cx(styles.conn, state === 'on' && styles.on, state === 'active' && styles.active)}
      data-connector={id}
      data-state={state}
      aria-hidden="true"
    />
  )
}

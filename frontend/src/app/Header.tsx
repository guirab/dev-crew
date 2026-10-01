import { useSendCommand } from '../api/commands'
import type { TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { Button } from '../ui/Button'
import styles from './Header.module.css'

const PHASE_LABEL: Partial<Record<TaskView['phase'], string>> = {
  cancelled: 'cancelada',
  failed: 'falhou',
}

export function Header({ view }: { view: TaskView | null }) {
  const dismissTask = useCrewStore((s) => s.dismissTask)
  const cancel = useSendCommand()
  const finished = view?.phase === 'done' || view?.phase === 'cancelled'

  return (
    <header className={styles.header}>
      <h1 className={styles.brand}>
        <span className={styles.prompt}>&gt;</span> dev-crew
        <span className={styles.caret} aria-hidden="true" />
      </h1>
      {view && (
        <span className={styles.task}>
          <b>{view.task_id}</b> · {view.title}
          {PHASE_LABEL[view.phase] && (
            <span className={styles.phase}>{PHASE_LABEL[view.phase]}</span>
          )}
        </span>
      )}
      <span className={styles.sp} />
      {cancel.error && (
        <span role="alert" className={styles.error}>
          {cancel.error.message}
        </span>
      )}
      {view &&
        (finished ? (
          <Button variant="primary" size="sm" onClick={dismissTask}>
            Nova tarefa
          </Button>
        ) : (
          <Button
            variant="link"
            disabled={cancel.isPending}
            onClick={() => {
              if (window.confirm('Cancelar a tarefa atual? As alterações locais ficam no repo.')) {
                cancel.mutate({ type: 'cancel_task' })
              }
            }}
          >
            cancelar tarefa
          </Button>
        ))}
    </header>
  )
}

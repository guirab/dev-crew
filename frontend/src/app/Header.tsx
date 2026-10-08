import { useSendCommand } from '../api/commands'
import type { TaskView } from '../contracts/generated'
import { isRunning, useCrewStore } from '../store/crew'
import { Button } from '../ui/Button'
import styles from './Header.module.css'
import { UsageChip } from './UsageChip'

const PHASE_LABEL: Partial<Record<TaskView['phase'], string>> = {
  cancelled: 'cancelada',
  failed: 'falhou',
}

export function Header({ view }: { view: TaskView | null }) {
  const screen = useCrewStore((s) => s.screen)
  const setScreen = useCrewStore((s) => s.setScreen)
  const cancel = useSendCommand()
  const shown = screen === 'task' ? view : null

  return (
    <header className={styles.header}>
      <h1 className={styles.brand}>
        <span className={styles.prompt}>&gt;</span> dev-crew
        <span className={styles.caret} aria-hidden="true" />
      </h1>
      <div role="tablist" aria-label="Seções" className={styles.tabs}>
        <button
          type="button"
          role="tab"
          aria-selected={screen !== 'history'}
          className={styles.tab}
          onClick={() => {
            setScreen('new')
          }}
        >
          Nova tarefa
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={screen === 'history'}
          className={styles.tab}
          onClick={() => {
            setScreen('history')
          }}
        >
          Histórico
        </button>
      </div>
      {shown && (
        <span className={styles.task}>
          <b>{shown.task_id}</b> · {shown.title}
          {PHASE_LABEL[shown.phase] && (
            <span className={styles.phase}>{PHASE_LABEL[shown.phase]}</span>
          )}
        </span>
      )}
      <span className={styles.sp} />
      <UsageChip />
      {cancel.error && (
        <span role="alert" className={styles.error}>
          {cancel.error.message}
        </span>
      )}
      {shown && isRunning(shown) && (
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
      )}
    </header>
  )
}

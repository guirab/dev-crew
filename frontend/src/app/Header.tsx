import type { TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import styles from './Header.module.css'
import { UsageChip } from './UsageChip'

/** Marca, abas e a tarefa aberta. Estado e "cancelar" ficam na faixa Agora (`NowBar`). */
export function Header({ view }: { view: TaskView | null }) {
  const screen = useCrewStore((s) => s.screen)
  const setScreen = useCrewStore((s) => s.setScreen)
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
        </span>
      )}
      <span className={styles.sp} />
      <UsageChip />
    </header>
  )
}

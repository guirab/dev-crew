import { isRunning, useCrewStore } from '../store/crew'
import styles from './RunningTaskNotice.module.css'

/** Aviso na aba "Nova tarefa" quando há tarefa em andamento, com link pro fluxo dela. */
export function RunningTaskNotice() {
  const view = useCrewStore((s) => s.view)
  const setScreen = useCrewStore((s) => s.setScreen)
  if (!isRunning(view)) return null

  return (
    <div role="status" className={styles.notice}>
      <span className={styles.text}>
        Tarefa em andamento: <b>{view.task_id}</b> · {view.title}
      </span>
      <button
        type="button"
        className={styles.link}
        onClick={() => {
          setScreen('task')
        }}
      >
        ver tarefa
      </button>
    </div>
  )
}

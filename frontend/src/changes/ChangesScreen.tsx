import type { FinalReport, TaskView } from '../contracts/generated'
import { ChangeCount } from '../flow/TaskScreen'
import { useCrewStore } from '../store/crew'
import { ChangesPanel } from './ChangesPanel'
import styles from './Changes.module.css'

/**
 * Tela Alterações: o que a tarefa mudou, estilo git. Hoje só existe com resultado (`FileDiff`, D75);
 * diff durante a execução e filtro por épico esperam o pedido de contrato.
 */
export function ChangesScreen({ view, final }: { view: TaskView; final: FinalReport }) {
  const setScreen = useCrewStore((s) => s.setScreen)
  const split = final.commits.length > 0 || view.epics.length > 0

  return (
    <section aria-label="Alterações">
      <button
        type="button"
        className={styles.back}
        onClick={() => {
          setScreen('task')
        }}
      >
        ← {view.task_id} · {view.title}
      </button>
      <div className={styles.trow}>
        <h2 className={styles.title}>Alterações</h2>
        <span className={styles.sp} />
        <ChangeCount view={view} />
      </div>
      <p className={styles.sub}>
        na <span className={styles.mono}>{final.branch}</span> ·{' '}
        {split ? 'commitado na branch da tarefa, sem push' : 'nada commitado'}
      </p>
      <ChangesPanel taskId={view.task_id} files={final.files} />
    </section>
  )
}

import { useSendCommand } from '../api/commands'
import { CommandErrorMessage } from '../bodies/CommandErrorMessage'
import type { TaskView } from '../contracts/generated'
import { formatClock } from '../lib/format'
import { isRunning, useCrewStore } from '../store/crew'
import { TaskTimeline } from './TaskTimeline'
import styles from './TaskScreen.module.css'

/** "8 arquivos +345 −11" do resultado. */
export function ChangeCount({ view }: { view: TaskView }) {
  const files = view.final?.files ?? []
  return (
    <span className={styles.count}>
      <span className={styles.dim}>
        {files.length} arquivo{files.length === 1 ? '' : 's'}
      </span>{' '}
      <span className={styles.add}>+{files.reduce((sum, f) => sum + f.added, 0)}</span>{' '}
      <span className={styles.rem}>−{files.reduce((sum, f) => sum + f.removed, 0)}</span>
    </span>
  )
}

/** Título, botão Alterações (só com resultado: o diff de hoje é o do fim) e a linha de contexto. */
function TaskHeading({ view }: { view: TaskView }) {
  const setScreen = useCrewStore((s) => s.setScreen)
  const send = useSendCommand()
  const branch = view.final?.branch
  const ended = view.ended_at

  return (
    <div className={styles.heading}>
      <div className={styles.trow}>
        <h2 className={styles.title}>{view.title}</h2>
        <span className={styles.sp} />
        {view.final && (
          <button
            type="button"
            className={styles.chg}
            onClick={() => {
              setScreen('changes')
            }}
          >
            Alterações <ChangeCount view={view} />
          </button>
        )}
      </div>
      <p className={styles.sub}>
        <span className={styles.mono}>{view.task_id}</span>
        <span className={styles.dim}>·</span>
        <span>▣ {view.repo}</span>
        {branch && (
          <>
            <span className={styles.dim}>·</span>
            <span className={styles.mono}>{branch}</span>
          </>
        )}
        <span className={styles.dim}>·</span>
        <span>
          {ended
            ? `terminou ${formatClock(ended).slice(0, 5)}`
            : `começou ${formatClock(view.started_at).slice(0, 5)}`}
        </span>
        {isRunning(view) && (
          <>
            <span className={styles.sp} />
            <button
              type="button"
              className={styles.cancel}
              disabled={send.isPending}
              onClick={() => {
                if (
                  window.confirm('Cancelar a tarefa atual? As alterações locais ficam no repo.')
                ) {
                  send.mutate({ type: 'cancel_task' })
                }
              }}
            >
              cancelar tarefa
            </button>
          </>
        )}
      </p>
      <CommandErrorMessage error={send.error} />
    </div>
  )
}

/** Tela da tarefa: título e a linha do tempo de agentes. */
export function TaskScreen({ view }: { view: TaskView }) {
  return (
    <section aria-label={`Tarefa ${view.task_id}`}>
      <TaskHeading view={view} />
      {/* key: cada tarefa começa com os nós no automático */}
      <TaskTimeline key={view.task_id} view={view} />
    </section>
  )
}

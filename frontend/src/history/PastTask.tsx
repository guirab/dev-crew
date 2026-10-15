import { useQuery } from '@tanstack/react-query'
import { taskQuery } from '../api/queries'
import { DoneBody } from '../bodies/DoneBody'
import type { TaskSummary } from '../contracts/generated'
import { Button } from '../ui/Button'
import styles from './HistoryList.module.css'

/** Tarefa antiga aberta do Histórico: só leitura, sem comandos. A tarefa atual não muda. */
export function PastTask({
  task,
  status,
  onBack,
}: {
  task: TaskSummary
  status: string
  onBack: () => void
}) {
  const { data, isPending, isError, error } = useQuery(taskQuery(task.task_id))

  return (
    <section aria-label={`Tarefa ${task.task_id}`}>
      <div className={styles.pastHead}>
        <Button variant="link" onClick={onBack}>
          ← Histórico
        </Button>
        <b className={styles.id}>{task.task_id}</b>
        <span className={styles.title}>{task.title}</span>
        <span className={styles.status}>{status}</span>
      </div>
      {isPending ? (
        <p className={styles.hint}>carregando…</p>
      ) : isError ? (
        <p role="alert" className={styles.error}>
          {error.message}
        </p>
      ) : data.final ? (
        <DoneBody view={data} stage={data.stages.done} />
      ) : (
        <p className={styles.hint}>Sem resultado: a tarefa terminou antes de gerar alterações.</p>
      )}
    </section>
  )
}

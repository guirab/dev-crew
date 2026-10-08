import { useTaskHistory } from '../api/queries'
import type { TaskPhase } from '../contracts/aliases'
import type { TaskSummary } from '../contracts/generated'
import { cx } from '../lib/cx'
import { formatDateTime, formatDuration, formatTokens, formatUsd } from '../lib/format'
import styles from './HistoryList.module.css'

const STATUS_LABEL: Record<TaskPhase, string> = {
  interviewing: 'em andamento',
  planning: 'em andamento',
  awaiting_approval: 'aguardando aprovação',
  developing: 'em andamento',
  testing: 'em andamento',
  reviewing: 'em andamento',
  executing: 'em andamento',
  awaiting_selection: 'aguardando escolha',
  escalated: 'escalada',
  limited: 'limitada',
  done: 'concluída',
  cancelled: 'cancelada',
  failed: 'falhou',
}

function statusClass(phase: TaskPhase): string | undefined {
  if (phase === 'done') return styles.done
  if (phase === 'failed') return styles.failed
  if (phase === 'cancelled') return styles.cancelled
  return styles.running
}

function Item({ task }: { task: TaskSummary }) {
  return (
    <li className={styles.item}>
      <div className={styles.head}>
        <b className={styles.id}>{task.task_id}</b>
        <span className={styles.title}>{task.title}</span>
        <span className={cx(styles.status, statusClass(task.phase))}>
          {STATUS_LABEL[task.phase]}
        </span>
      </div>
      <p className={styles.summary}>
        {task.summary}
        {task.files_changed !== null && (
          <span className={styles.files}>
            {' · '}
            {task.files_changed}{' '}
            {task.files_changed === 1 ? 'arquivo alterado' : 'arquivos alterados'}
          </span>
        )}
      </p>
      <p className={styles.meta}>
        <span>{task.repo}</span>
        <span>{formatDateTime(task.started_at)}</span>
        <span>{formatDuration(task.duration_s)}</span>
        <span>{formatUsd(task.cost_usd)}</span>
        <span>{formatTokens(task.tokens)} tokens</span>
      </p>
    </li>
  )
}

/** Lista só informativa das tarefas já executadas (mais recente primeiro). */
export function HistoryList() {
  const { data, isPending, isError, error } = useTaskHistory()

  if (isPending) return <p className={styles.hint}>carregando…</p>
  if (isError) {
    return (
      <p role="alert" className={styles.error}>
        {error.message}
      </p>
    )
  }
  if (data.length === 0) return <p className={styles.hint}>Nenhuma tarefa executada ainda.</p>

  return (
    <ul className={styles.list} aria-label="Histórico de tarefas">
      {data.map((task) => (
        <Item key={task.task_id} task={task} />
      ))}
    </ul>
  )
}

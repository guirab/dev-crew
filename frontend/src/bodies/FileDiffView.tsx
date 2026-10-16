import { useQuery } from '@tanstack/react-query'
import { fileDiffQuery } from '../api/queries'
import { diffRows } from '../changes/diff'
import type { FinalFile } from '../contracts/generated'
import { cx } from '../lib/cx'
import styles from './FileDiffView.module.css'

const SIGN = { hunk: '', add: '+', del: '−', ctx: ' ' } as const

function Patch({ taskId, path }: { taskId: string; path: string }) {
  const { data, isPending, isError, error } = useQuery(fileDiffQuery(taskId, path))

  if (isPending) return <p className={styles.note}>carregando diff…</p>
  if (isError) {
    return (
      <p role="alert" className={styles.error}>
        {error.message}
      </p>
    )
  }
  if (data.binary) return <p className={styles.note}>Arquivo binário: sem diff de texto.</p>
  const rows = diffRows(data.patch)
  if (rows.length === 0) return <p className={styles.note}>Sem alterações de texto.</p>
  return (
    <>
      <div className={styles.body} role="table" aria-label={`Diff de ${path}`}>
        {/* linhas do patch não têm id; a lista é estática por arquivo */}
        {rows.map((row, i) => (
          <div key={i} role="row" className={cx(styles.dl, styles[row.kind])}>
            <span role="cell">{row.old ?? ''}</span>
            <span role="cell">{row.new ?? ''}</span>
            <code role="cell">
              {SIGN[row.kind]}
              {row.text}
            </code>
          </div>
        ))}
      </div>
      {data.truncated && (
        <p className={styles.note}>Diff cortado: arquivo grande demais pra mostrar inteiro.</p>
      )}
    </>
  )
}

/** Diff de um arquivo do resultado estilo git: cabeçalho com status e contagem, linhas numeradas. */
export function FileDiffView({ taskId, file }: { taskId: string; file: FinalFile }) {
  return (
    <section className={styles.view} aria-label={file.path}>
      <div className={styles.head}>
        <span className={cx(styles.st, styles[file.status])}>{file.status}</span>
        <span className={styles.path}>{file.path}</span>
        <span className={styles.count}>
          <span className={styles.plus}>+{file.added}</span>{' '}
          <span className={styles.minus}>−{file.removed}</span>
        </span>
      </div>
      <Patch key={file.path} taskId={taskId} path={file.path} />
    </section>
  )
}

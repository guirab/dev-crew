import { useQuery } from '@tanstack/react-query'
import { fileDiffQuery } from '../api/queries'
import styles from './FileDiffView.module.css'

/** Linhas do patch a partir do primeiro hunk (o cabeçalho do git só repete o caminho). */
function hunkLines(patch: string): string[] {
  const lines = patch.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n')
  const first = lines.findIndex((line) => line.startsWith('@@'))
  return first === -1 ? [] : lines.slice(first)
}

function lineClass(line: string): string | undefined {
  if (line.startsWith('@@')) return styles.hunk
  if (line.startsWith('+')) return styles.add
  if (line.startsWith('-')) return styles.del
  return undefined
}

/** Patch de um arquivo do resultado, buscado ao abrir. */
export function FileDiffView({ taskId, path, id }: { taskId: string; path: string; id: string }) {
  const { data, isPending, isError, error } = useQuery(fileDiffQuery(taskId, path))

  if (isPending) {
    return (
      <p id={id} className={styles.note}>
        carregando diff…
      </p>
    )
  }
  if (isError) {
    return (
      <p id={id} role="alert" className={styles.error}>
        {error.message}
      </p>
    )
  }
  if (data.binary) {
    return (
      <p id={id} className={styles.note}>
        Arquivo binário: sem diff de texto.
      </p>
    )
  }
  const lines = hunkLines(data.patch)
  if (lines.length === 0) {
    return (
      <p id={id} className={styles.note}>
        Sem alterações de texto.
      </p>
    )
  }
  return (
    <div id={id} className={styles.wrap}>
      <pre className={styles.patch} aria-label={`Diff de ${path}`}>
        {/* linhas do patch não têm id; a lista é estática por arquivo */}
        {lines.map((line, i) => (
          <span key={i} className={lineClass(line)}>
            {line}
          </span>
        ))}
      </pre>
      {data.truncated && (
        <p className={styles.note}>Diff cortado: arquivo grande demais pra mostrar inteiro.</p>
      )}
    </div>
  )
}

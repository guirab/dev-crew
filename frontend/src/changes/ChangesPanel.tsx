import { useState } from 'react'
import { FileDiffView } from '../bodies/FileDiffView'
import type { FinalFile } from '../contracts/generated'
import { cx } from '../lib/cx'
import styles from './Changes.module.css'

/** Arquivos agrupados pela pasta, na ordem em que aparecem. */
function byFolder(files: readonly FinalFile[]): [string, FinalFile[]][] {
  const groups = new Map<string, FinalFile[]>()
  for (const file of files) {
    const cut = file.path.lastIndexOf('/')
    const dir = cut === -1 ? '' : file.path.slice(0, cut + 1)
    groups.set(dir, [...(groups.get(dir) ?? []), file])
  }
  return [...groups]
}

/** Estilo git: árvore de arquivos à esquerda, diff do escolhido à direita (embaixo no celular). */
export function ChangesPanel({ taskId, files }: { taskId: string; files: readonly FinalFile[] }) {
  const [picked, setPicked] = useState<string | null>(null)
  const shown = files.find((file) => file.path === picked) ?? files[0]
  if (!shown) return <p className={styles.empty}>Nenhum arquivo alterado.</p>

  return (
    <div className={styles.chg}>
      <nav className={styles.tree} aria-label="Arquivos alterados">
        {byFolder(files).map(([dir, group]) => (
          <div key={dir}>
            {dir && <div className={styles.dir}>▾ {dir}</div>}
            {group.map((file) => (
              <button
                key={file.path}
                type="button"
                title={file.path}
                className={cx(styles.tf, !dir && styles.root)}
                aria-current={file === shown ? 'true' : undefined}
                onClick={() => {
                  setPicked(file.path)
                }}
              >
                <span className={styles[file.status]}>{file.status}</span>
                <span className={styles.nm}>{file.path.slice(dir.length)}</span>
                <span className={styles.add}>+{file.added}</span>
                <span className={styles.rem}>{file.removed ? `−${String(file.removed)}` : ''}</span>
              </button>
            ))}
          </div>
        ))}
      </nav>
      <FileDiffView taskId={taskId} file={shown} />
    </div>
  )
}

import { useId, useState } from 'react'
import type { FinalFile } from '../contracts/generated'
import { cx } from '../lib/cx'
import { formatDuration, formatTokens, formatUsd } from '../lib/format'
import { CopyButton } from './CopyButton'
import { Empty } from './Empty'
import { FileDiffView } from './FileDiffView'
import type { BodyProps } from './types'
import b from './body.module.css'
import styles from './DoneBody.module.css'

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

export function DoneBody({ view }: BodyProps) {
  // um diff aberto por vez: o id do painel não precisa variar por arquivo
  const [openPath, setOpenPath] = useState<string | null>(null)
  const diffId = useId()
  const final = view?.final ?? null
  if (!view || !final) {
    return (
      <Empty>
        Fim do fluxo: alterações ficam no repo local, nada é commitado. Você recebe a mensagem de
        commit sugerida.
      </Empty>
    )
  }

  const split = final.commits.length > 0 || view.epics.length > 0
  const testRuns = split
    ? view.epics.reduce((sum, e) => sum + e.test_runs.length, 0)
    : view.test_runs.length
  const reviews = split
    ? view.epics.reduce((sum, e) => sum + e.counters.review_round, 0)
    : view.counters.review_round
  const added = final.files.reduce((sum, f) => sum + f.added, 0)
  const removed = final.files.reduce((sum, f) => sum + f.removed, 0)
  const biggest = Math.max(1, ...final.files.map((f) => f.added + f.removed))

  return (
    <>
      <div className={cx(b.sec, b.kv)}>
        <div>
          <b>{final.files.length}</b>
          <span>arquivos alterados</span>
        </div>
        <div>
          <b>
            <span className={styles.add}>+{added}</span>{' '}
            <span className={styles.del}>−{removed}</span>
          </b>
          <span>linhas</span>
        </div>
        <div>
          <b>{testRuns}</b>
          <span>execuções de teste</span>
        </div>
        <div>
          <b>{reviews}</b>
          <span>rodadas de review</span>
        </div>
        <div>
          <b>{formatDuration(final.duration_s)}</b>
          <span>duração</span>
        </div>
        <div>
          <b>{formatUsd(final.cost_usd)}</b>
          <span>equivalente API</span>
        </div>
        {final.tokens > 0 && (
          <div>
            <b>{formatTokens(final.tokens)}</b>
            <span>tokens</span>
          </div>
        )}
      </div>

      <section className={cx(b.sec, styles.next)} aria-label="Próximo passo">
        <div className={styles.nextHead}>
          <div>
            <b>
              {split
                ? `Próximo passo: juntar ${final.branch} na sua branch`
                : 'Próximo passo: revisar e commitar'}
            </b>
            <p className={styles.where}>
              branch {final.branch} · {final.worktree_path}
            </p>
          </div>
          <div className={b.row}>
            <CopyButton text={final.worktree_path} label="Copiar caminho" variant="default" />
            <CopyButton text={final.commit_message} />
          </div>
        </div>
        <h4>
          {split
            ? 'Mensagem se quiser juntar tudo num commit (squash)'
            : 'Mensagem de commit sugerida'}
        </h4>
        <pre className={b.commit}>{final.commit_message}</pre>
      </section>

      {split && (
        <div className={b.sec}>
          <h4>Commits por épico</h4>
          <ol className={styles.commits}>
            {final.commits.map((commit) => (
              <li key={commit.sha}>
                <span className={styles.sha}>{commit.sha.slice(0, 8)}</span>
                <span className={styles.epic}>{commit.epic_id}</span>
                {commit.message.split('\n')[0]}
              </li>
            ))}
          </ol>
          {final.pending_epics.length > 0 && (
            <p className={b.muted} style={{ margin: '8px 0 0' }}>
              Ficaram pendentes no plano: {final.pending_epics.join(', ')}
            </p>
          )}
        </div>
      )}

      <div className={b.sec}>
        <h4>
          Alterações · {view.repo} · {split ? 'commitado na branch, sem push' : 'não commitado'}
        </h4>
        {byFolder(final.files).map(([dir, files]) => (
          <div key={dir} className={styles.folder}>
            {dir && <div className={styles.dir}>{dir}</div>}
            {files.map((file) => (
              <div key={file.path}>
                <button
                  type="button"
                  className={styles.file}
                  title={file.path}
                  aria-expanded={openPath === file.path}
                  aria-controls={openPath === file.path ? diffId : undefined}
                  onClick={() => {
                    setOpenPath(openPath === file.path ? null : file.path)
                  }}
                >
                  <span className={cx(styles.status, styles[file.status])}>{file.status}</span>
                  <span className={styles.name}>{file.path.slice(dir.length)}</span>
                  <span className={styles.count}>
                    <span className={styles.add}>+{file.added}</span>{' '}
                    <span className={styles.del}>−{file.removed}</span>
                  </span>
                  <span className={styles.bar} aria-hidden="true">
                    <i
                      className={styles.barAdd}
                      style={{ width: `${String((file.added / biggest) * 100)}%` }}
                    />
                    <i
                      className={styles.barDel}
                      style={{ width: `${String((file.removed / biggest) * 100)}%` }}
                    />
                  </span>
                </button>
                {openPath === file.path && (
                  <FileDiffView taskId={view.task_id} path={file.path} id={diffId} />
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      {final.plan_doc && (
        <div className={cx(b.sec, b.muted, b.mono)} style={{ fontSize: 12 }}>
          plano salvo em {final.plan_doc}
        </div>
      )}
    </>
  )
}

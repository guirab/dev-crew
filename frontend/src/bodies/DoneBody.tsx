import { CopyButton } from './CopyButton'
import { Empty } from './Empty'
import type { BodyProps } from './types'
import b from './body.module.css'
import styles from './DoneBody.module.css'

/** Resultado: mensagem de commit sugerida, onde ficou e, com épicos, os commits de cada um. O diff mora em Alterações. */
export function DoneBody({ view }: BodyProps) {
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

  return (
    <>
      <div className={b.sec}>
        <div className={styles.head}>
          <h4>
            {split
              ? 'Mensagem se quiser juntar tudo num commit (squash)'
              : 'Mensagem de commit sugerida'}
          </h4>
          <CopyButton text={final.commit_message} variant="default" />
        </div>
        <pre className={b.commit}>{final.commit_message}</pre>
      </div>

      <div className={styles.where}>
        <span>
          branch {final.branch} · {final.worktree_path} ·{' '}
          {split ? 'commitado na branch, sem push' : 'não commitado'}
        </span>
        <CopyButton text={final.worktree_path} label="Copiar caminho" variant="default" />
      </div>

      {split && final.commits.length > 0 && (
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
        </div>
      )}
      {final.pending_epics.length > 0 && (
        <p className={b.muted}>Ficaram pendentes no plano: {final.pending_epics.join(', ')}</p>
      )}
      {final.plan_doc && (
        <p className={b.muted} style={{ fontSize: 12 }}>
          plano salvo em <span className={b.mono}>{final.plan_doc}</span>
        </p>
      )}
    </>
  )
}

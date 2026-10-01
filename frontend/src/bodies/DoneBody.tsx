import { cx } from '../lib/cx'
import { formatDuration, formatUsd } from '../lib/format'
import { CopyButton } from './CopyButton'
import { Empty } from './Empty'
import type { BodyProps } from './types'
import b from './body.module.css'

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

  return (
    <>
      <div className={cx(b.sec, b.kv)}>
        <div>
          <b>{final.files.length}</b>
          <span>arquivos alterados</span>
        </div>
        <div>
          <b>{view.test_runs.length}</b>
          <span>execuções de teste</span>
        </div>
        <div>
          <b>{view.counters.review_round}</b>
          <span>rodadas de review</span>
        </div>
        <div>
          <b>{formatDuration(final.duration_s)}</b>
          <span>duração</span>
        </div>
        <div>
          <b>{formatUsd(final.cost_usd)}</b>
          <span>custo</span>
        </div>
      </div>
      <div className={b.sec}>
        <h4>Alterações · {view.repo} · não commitado</h4>
        <div className={b.files}>
          {final.files.map((file) => (
            <div key={file.path}>
              <span className={b[file.status]}>{file.status}</span>
              {'  '}
              {file.path}{' '}
              <span className={b.muted}>
                +{file.added} −{file.removed}
              </span>
            </div>
          ))}
        </div>
        <div className={cx(b.muted, b.mono)} style={{ fontSize: 12, marginTop: 8 }}>
          branch {final.branch} · {final.worktree_path}
        </div>
      </div>
      <div className={b.sec}>
        <h4>Mensagem de commit sugerida</h4>
        <pre className={b.commit}>{final.commit_message}</pre>
        <div className={cx(b.row, b.end)} style={{ marginTop: 10 }}>
          <CopyButton text={final.commit_message} />
        </div>
      </div>
    </>
  )
}

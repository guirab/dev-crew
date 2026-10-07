import { cx } from '../lib/cx'
import { formatDuration, formatTokens, formatUsd } from '../lib/format'
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

  const split = final.commits.length > 0 || view.epics.length > 0
  const testRuns = split
    ? view.epics.reduce((sum, e) => sum + e.test_runs.length, 0)
    : view.test_runs.length
  const reviews = split
    ? view.epics.reduce((sum, e) => sum + e.counters.review_round, 0)
    : view.counters.review_round
  return (
    <>
      <div className={cx(b.sec, b.kv)}>
        <div>
          <b>{final.files.length}</b>
          <span>arquivos alterados</span>
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
      {split && (
        <div className={b.sec}>
          <h4>Commits por épico · branch {final.branch}</h4>
          <div className={b.files}>
            {final.commits.map((commit) => (
              <div key={commit.epic_id}>
                <span className={b.mono}>{commit.sha.slice(0, 8)}</span> {commit.epic_id} ·{' '}
                {commit.message.split('\n')[0]}
              </div>
            ))}
          </div>
          {final.pending_epics.length > 0 && (
            <p className={b.muted} style={{ margin: '8px 0 0' }}>
              Ficaram pendentes no plano: {final.pending_epics.join(', ')}
            </p>
          )}
        </div>
      )}
      {final.plan_doc && (
        <div className={cx(b.muted, b.mono)} style={{ fontSize: 12 }}>
          plano salvo em {final.plan_doc}
        </div>
      )}
      <div className={b.sec}>
        <h4>
          Alterações · {view.repo} · {split ? 'commitado na branch, sem push' : 'não commitado'}
        </h4>
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
        <h4>
          {split
            ? 'Mensagem se quiser juntar tudo num commit (squash)'
            : 'Mensagem de commit sugerida'}
        </h4>
        <pre className={b.commit}>{final.commit_message}</pre>
        <div className={cx(b.row, b.end)} style={{ marginTop: 10 }}>
          <CopyButton text={final.commit_message} />
        </div>
      </div>
    </>
  )
}

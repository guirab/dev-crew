import { cx } from '../lib/cx'
import { formatPercent } from '../lib/format'
import { ActivityLog } from './ActivityLog'
import { Empty } from './Empty'
import { EscalationPanel } from './EscalationPanel'
import type { BodyProps } from './types'
import b from './body.module.css'

export function TesterBody({ view, stage }: BodyProps) {
  const runs = view?.test_runs ?? []
  return (
    <>
      {view?.escalation?.stage === 'tester' && <EscalationPanel reason={view.escalation.reason} />}
      {runs.length > 0 ? (
        <div className={b.sec}>
          <h4>Execuções</h4>
          {runs
            .map((run, i) => ({ run, attempt: i + 1 }))
            .reverse()
            .map(({ run, attempt }) => (
              <div key={attempt} className={b.item}>
                <div className={b.h}>
                  <span className={cx(b.pill, run.ok ? b.ok : b.err)}>
                    {run.ok ? 'PASSOU' : 'FALHOU'}
                  </span>
                  <b>Tentativa {attempt}</b>
                  {run.coverage !== null && (
                    <span className={cx(b.muted, b.mono)}>
                      cobertura {formatPercent(run.coverage)}
                    </span>
                  )}
                  <span className={b.sp} />
                  <span className={b.mono}>
                    {run.passed}/{run.total}
                  </span>
                </div>
                {run.failures.map((failure) => (
                  <div key={failure.test} className={b.fail}>
                    {failure.test} — {failure.message}
                  </div>
                ))}
              </div>
            ))}
        </div>
      ) : (
        <Empty>Nenhuma execução ainda.</Empty>
      )}
      <ActivityLog logs={stage.logs} />
    </>
  )
}

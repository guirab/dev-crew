import { cx } from '../lib/cx'
import { ActivityLog } from './ActivityLog'
import { Empty } from './Empty'
import { EscalationPanel } from './EscalationPanel'
import type { BodyProps } from './types'
import b from './body.module.css'

export function DeveloperBody({ view, stage }: BodyProps) {
  const rounds = view?.dev_rounds ?? []
  return (
    <>
      {view?.escalation?.stage === 'developer' && (
        <EscalationPanel reason={view.escalation.reason} />
      )}
      {rounds.length > 0 ? (
        <div className={b.sec}>
          <h4>Rodadas · repo local, sem commit</h4>
          {rounds.map((round) => (
            <div key={round.round} className={b.item}>
              <span className={cx(b.mono, b.g)}>#{round.round}</span> {round.summary}
              {round.files_changed.length > 0 && (
                <div className={b.chips} style={{ marginTop: 8 }}>
                  {round.files_changed.map((file) => (
                    <span key={file.path} className={b.chip} data-change={file.change}>
                      {file.path}
                    </span>
                  ))}
                </div>
              )}
              {round.notes && (
                <div className={b.muted} style={{ marginTop: 6 }}>
                  {round.notes}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Empty>Aguardando plano aprovado.</Empty>
      )}
      <ActivityLog logs={stage.logs} />
    </>
  )
}

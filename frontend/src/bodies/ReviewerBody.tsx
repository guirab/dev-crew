import type { ReviewComment } from '../contracts/generated'
import { cx } from '../lib/cx'
import { ActivityLog } from './ActivityLog'
import { Empty } from './Empty'
import { EscalationPanel } from './EscalationPanel'
import type { BodyProps } from './types'
import b from './body.module.css'

function pillFor(comment: ReviewComment): { label: string; className: string | undefined } {
  if (comment.resolved) return { label: 'RESOLVIDO', className: b.ok }
  switch (comment.severity) {
    case 'major':
      return { label: 'MAJOR', className: b.err }
    case 'minor':
      return { label: 'MINOR', className: b.warn }
    case 'nit':
      return { label: 'NIT', className: b.nit }
  }
}

export function ReviewerBody({ view, stage }: BodyProps) {
  const comments = view?.review?.comments ?? []
  return (
    <>
      {view?.escalation?.stage === 'reviewer' && (
        <EscalationPanel reason={view.escalation.reason} />
      )}
      {comments.length > 0 ? (
        <div className={b.sec}>
          <h4>Comentários</h4>
          {comments.map((comment, i) => {
            const pill = pillFor(comment)
            const where = comment.line === null ? comment.file : `${comment.file}:${comment.line}`
            return (
              <div key={`${i}|${where}`} className={b.item}>
                <div className={b.h}>
                  <span className={cx(b.pill, pill.className)}>{pill.label}</span>
                  <span className={cx(b.mono, b.muted)}>{where}</span>
                </div>
                <div style={{ marginTop: 5 }}>{comment.text}</div>
              </div>
            )
          })}
        </div>
      ) : (
        <Empty>Nenhum comentário ainda.</Empty>
      )}
      <ActivityLog logs={stage.logs} />
    </>
  )
}

import { cx } from '../lib/cx'
import { ActivityLog } from './ActivityLog'
import { Empty } from './Empty'
import type { BodyProps } from './types'
import b from './body.module.css'

/** Padrões (D82): a base criada (arquivos + o que o dev-crew decidiu sozinho) ou a que já existia. */
export function StandardsBody({ view, stage }: BodyProps) {
  const result = view?.standards ?? null
  return (
    <>
      {stage.status === 'error' ? (
        <p className={cx(b.sec, b.muted)}>A tarefa segue sem a base de padrões.</p>
      ) : result ? (
        <>
          <p className={b.sec}>{result.summary}</p>
          {result.files.length > 0 && (
            <div className={b.sec}>
              <h4>Arquivos em standards/</h4>
              <div className={b.chips}>
                {result.files.map((file) => (
                  <span key={file} className={b.chip}>
                    {file}
                  </span>
                ))}
              </div>
            </div>
          )}
          {result.decisions.length > 0 && (
            <div className={b.sec}>
              <h4>Decidido pelo dev-crew</h4>
              <ul>
                {result.decisions.map((decision, i) => (
                  <li key={`${i}|${decision}`}>{decision}</li>
                ))}
              </ul>
            </div>
          )}
          {result.notes && <p className={cx(b.sec, b.muted)}>{result.notes}</p>}
        </>
      ) : (
        <Empty>Analisa o repositório e escreve a base de padrões, sem perguntar nada.</Empty>
      )}
      <ActivityLog logs={stage.logs} />
    </>
  )
}

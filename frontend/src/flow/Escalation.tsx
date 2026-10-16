import { EscalationPanel } from '../bodies/EscalationPanel'
import type { TestResult } from '../contracts/generated'
import styles from './Timeline.module.css'

/** O loop estourou: a última saída do Tester e a decisão (instruir, +2 tentativas, replanejar fora de épico). */
export function Escalation({
  reason,
  runs,
  epicId,
}: {
  reason: string
  runs: readonly TestResult[]
  epicId: string | null
}) {
  const last = runs.at(-1)
  return (
    <>
      {last && !last.ok && (
        <pre className={styles.term} aria-label="Última saída do Tester">
          <span className={styles.cmd}>$ {last.command}</span>
          {last.failures.map((failure) => (
            <span key={failure.test}>
              {'\n'}
              <span className={styles.fail}>FAIL</span> {failure.test}
              {'\n  '}
              {failure.message}
            </span>
          ))}
          {`\n${String(last.passed)}/${String(last.total)} passaram`}
        </pre>
      )}
      <EscalationPanel reason={reason} epicId={epicId} />
    </>
  )
}

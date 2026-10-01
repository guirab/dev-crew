import type { LogLine } from '../contracts/generated'
import { formatClock } from '../lib/format'
import b from './body.module.css'

export function ActivityLog({ logs }: { logs: readonly LogLine[] }) {
  if (logs.length === 0) return null
  return (
    <div className={b.sec}>
      <h4>Atividade</h4>
      <div className={b.logs}>
        {logs.map((line, i) => (
          <div key={`${line.ts}|${i}`}>
            <time dateTime={line.ts}>{formatClock(line.ts)}</time>
            {line.text}
          </div>
        ))}
      </div>
    </div>
  )
}

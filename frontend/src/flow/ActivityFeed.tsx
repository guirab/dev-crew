import { useState } from 'react'
import type { TaskView } from '../contracts/generated'
import { formatClock } from '../lib/format'
import { isRunning, useCrewStore } from '../store/crew'
import { activityEvents } from './activity'
import styles from './ActivityFeed.module.css'

const ALL = 'Tudo'

/** Coluna da direita: tudo que os agentes fizeram, de todas as etapas e faixas, filtrável. */
export function ActivityFeed({ view }: { view: TaskView }) {
  const progress = useCrewStore((s) => s.progress)
  const [filter, setFilter] = useState(ALL)
  const events = activityEvents(view, progress)
  // com épicos filtra por faixa; sem, por agente
  const split = view.epics.length > 0
  const keyOf = (e: (typeof events)[number]) => (split ? e.lane : e.who)
  const options = [ALL, ...new Set(events.map(keyOf).filter((k): k is string => k !== null))]
  const shown = filter === ALL ? events : events.filter((e) => keyOf(e) === filter)

  return (
    <aside className={styles.feed} aria-label="Atividade">
      <div className={styles.head}>
        <h2 className={styles.title}>
          Atividade
          {isRunning(view) && <span className={styles.live}>● ao vivo</span>}
        </h2>
        {options.length > 2 && (
          <div className={styles.filters} role="group" aria-label="Filtrar atividade">
            {options.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={filter === option}
                onClick={() => {
                  setFilter(option)
                }}
              >
                {option}
              </button>
            ))}
          </div>
        )}
      </div>
      {shown.length === 0 ? (
        <p className={styles.empty}>nada ainda</p>
      ) : (
        <ol className={styles.events}>
          {shown.map((e, i) => (
            <li key={`${e.ts}|${String(i)}`}>
              <time dateTime={e.ts}>{formatClock(e.ts)}</time>
              <span className={styles.who}>
                {e.who}
                {e.lane && <span className={styles.lane}>{e.lane}</span>}
              </span>
              <p>{e.text}</p>
            </li>
          ))}
        </ol>
      )}
    </aside>
  )
}

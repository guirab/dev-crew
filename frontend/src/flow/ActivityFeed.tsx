import { useState } from 'react'
import { Badge } from '../components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '../components/ui/collapsible'
import { ScrollArea } from '../components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select'
import type { TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { formatClock } from '../lib/format'
import { isRunning, useCrewStore } from '../store/crew'
import { activityEvents, attentionCount, filterEvents, groupEvents } from './activity'
import type { ActivityRow, FeedMode } from './activity'
import styles from './ActivityFeed.module.css'

const ANY = '__any'

/** Acima disso a mensagem fica em 2 linhas com "mostrar tudo" (o jsdom não mede altura). */
const LONG_TEXT = 140

/**
 * Feed de atividade ao lado do painel de foco: tudo que os agentes fizeram, de todas as etapas e
 * faixas. Filtra por "precisa de você", erros e origem; recolhe pra uma coluna fina com o contador.
 */
export function ActivityFeed({ view }: { view: TaskView }) {
  const progress = useCrewStore((s) => s.progress)
  const [open, setOpen] = useState(true)
  const [mode, setMode] = useState<FeedMode>('all')
  const [source, setSource] = useState<string | null>(null)
  const events = activityEvents(view, progress)
  const needing = attentionCount(view)
  // com épicos a origem é a faixa; sem, o agente
  const split = view.epics.length > 0
  const sources = [
    ...new Set(events.map((e) => (split ? e.lane : e.who)).filter((k): k is string => k !== null)),
  ]
  const rows = groupEvents(filterEvents(events, mode, source, split))

  const modeButton = (value: FeedMode, label: string) => (
    <button
      type="button"
      aria-pressed={mode === value}
      data-mode={value}
      onClick={() => {
        setMode(value)
        if (value === 'all') setSource(null)
      }}
    >
      {label}
    </button>
  )

  return (
    <Collapsible open={open} onOpenChange={setOpen} asChild>
      <aside
        className={cx(styles.feed, !open && styles.closed)}
        aria-label="Atividade"
        data-feed={open ? 'open' : 'closed'}
      >
        {open ? (
          <div className={styles.head}>
            <h2 className={styles.title}>Atividade</h2>
            {isRunning(view) && <span className={styles.live}>● ao vivo</span>}
            <CollapsibleTrigger asChild>
              <button type="button" className={styles.toggle} aria-label="Recolher feed">
                ⇥
              </button>
            </CollapsibleTrigger>
          </div>
        ) : (
          <div className={styles.mini}>
            <CollapsibleTrigger asChild>
              <button type="button" className={styles.toggle} aria-label="Abrir feed">
                ⇤
              </button>
            </CollapsibleTrigger>
            {needing > 0 && (
              <span className={styles.count} title={`${String(needing)} precisa de você`}>
                {needing}
              </span>
            )}
          </div>
        )}
        <CollapsibleContent className={styles.content}>
          <div className={styles.filters} role="group" aria-label="Filtrar atividade">
            {modeButton('all', 'Tudo')}
            {modeButton(
              'attention',
              needing > 0 ? `Precisa de você · ${String(needing)}` : 'Precisa de você',
            )}
            {modeButton('errors', 'Erros')}
            {sources.length > 1 && (
              <Select
                value={source ?? ANY}
                onValueChange={(value) => {
                  setSource(value === ANY ? null : value)
                }}
              >
                <SelectTrigger
                  size="sm"
                  className={styles.source}
                  aria-label={split ? 'Filtrar por épico' : 'Filtrar por agente'}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className={styles.sourceMenu}>
                  <SelectItem value={ANY}>{split ? 'Épico' : 'Agente'}</SelectItem>
                  {sources.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          {rows.length === 0 ? (
            <p className={styles.empty}>nada ainda</p>
          ) : (
            <ScrollArea className={styles.scroll}>
              <ol className={styles.events}>
                {rows.map((row, i) => (
                  <Row key={`${row.ts}|${String(i)}`} row={row} />
                ))}
              </ol>
            </ScrollArea>
          )}
        </CollapsibleContent>
      </aside>
    </Collapsible>
  )
}

function Row({ row }: { row: ActivityRow }) {
  const long = row.text.length > LONG_TEXT
  const [expanded, setExpanded] = useState(false)
  const [lane] = row.lanes
  const single = row.lanes.length === 1
  return (
    <li className={cx(row.highlight && styles.wait)} data-highlight={row.highlight || undefined}>
      <time dateTime={row.ts}>{formatClock(row.ts)}</time>
      <span className={styles.who}>
        {row.who}
        {single && lane && <span className={styles.lane}>{lane}</span>}
      </span>
      <p className={cx(long && !expanded && styles.clamp)}>{row.text}</p>
      {long && !expanded && (
        <button
          type="button"
          className={styles.more}
          onClick={() => {
            setExpanded(true)
          }}
        >
          mostrar tudo
        </button>
      )}
      {row.lanes.length > 1 && (
        <span className={styles.group}>
          {row.lanes.map((id) => (
            <Badge key={id} variant="outline" className={styles.laneBadge}>
              {id}
            </Badge>
          ))}
        </span>
      )}
    </li>
  )
}

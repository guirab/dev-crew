import { useState } from 'react'
import { useSendCommand } from '../api/commands'
import { CommandErrorMessage } from '../bodies/CommandErrorMessage'
import b from '../bodies/body.module.css'
import { EpicList, selectionTotal } from '../bodies/EpicList'
import type { TaskView } from '../contracts/generated'
import { Button } from '../ui/Button'
import { EpicBoard, EpicGraph } from './EpicBoard'
import styles from './EpicsSection.module.css'

type EpicsMode = 'board' | 'graph'

const MODES: readonly { id: EpicsMode; label: string }[] = [
  { id: 'board', label: 'Board' },
  { id: 'graph', label: 'Grafo' },
]

/** Épicos de um plano dividido (D53): board kanban por padrão ou o grafo de dependências. */
export function EpicsSection({ view }: { view: TaskView }) {
  const [mode, setMode] = useState<EpicsMode>('board')
  const lanes = view.epics
  const running = lanes.filter((l) => l.status === 'running' || l.status === 'preparing').length
  return (
    <section aria-label="Épicos">
      <div className={styles.title}>
        <span className={styles.count}>
          {lanes.filter((l) => l.kind === 'epic' && l.status === 'merged').length}/
          {lanes.filter((l) => l.kind === 'epic').length} prontos
          {running > 0 && ` · ${running} em paralelo`}
        </span>
        <span className={styles.toggle} role="group" aria-label="Vista dos épicos">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={styles.mode}
              aria-pressed={mode === m.id}
              onClick={() => {
                setMode(m.id)
              }}
            >
              {m.label}
            </button>
          ))}
        </span>
      </div>
      {view.phase === 'awaiting_selection' && <NextBatch view={view} />}
      {mode === 'board' ? <EpicBoard view={view} /> : <EpicGraph view={view} />}
    </section>
  )
}

/** Os épicos escolhidos ficaram prontos: rodar os próximos ou concluir com o que já foi feito. */
function NextBatch({ view }: { view: TaskView }) {
  const send = useSendCommand()
  const epics = view.plan?.epics ?? []
  const pending = new Set(view.epics.filter((e) => e.status === 'pending').map((e) => e.id))
  const locked = new Set(epics.map((e) => e.id).filter((id) => !pending.has(id)))
  const [picked, setPicked] = useState<ReadonlySet<string>>(() => new Set(pending))
  const toggle = (id: string) => {
    const next = new Set(picked)
    if (!next.delete(id)) next.add(id)
    setPicked(next)
  }
  const chosen = epics.map((e) => e.id).filter((id) => picked.has(id) && pending.has(id))

  return (
    <div className={styles.next} role="group" aria-label="Próximos épicos">
      <p className={styles.lead}>
        Os épicos escolhidos estão prontos na branch. Rode os próximos ou conclua agora: o Reviewer
        revisa a tarefa inteira uma vez e os pendentes ficam registrados no plano.
      </p>
      <EpicList
        epics={epics}
        estimates={view.estimate?.epics ?? []}
        selection={{ selected: picked, onToggle: toggle, locked }}
      />
      <div className={b.actionbar}>
        <span className={b.total}>{selectionTotal(chosen, view.estimate?.epics ?? [])}</span>
        <Button
          variant="primary"
          disabled={send.isPending || chosen.length === 0}
          onClick={() => {
            send.mutate({ type: 'run_epics', epics: chosen })
          }}
        >
          Rodar {chosen.length} épico{chosen.length === 1 ? '' : 's'}
        </Button>
        <Button
          disabled={send.isPending}
          onClick={() => {
            send.mutate({ type: 'finish_task' })
          }}
        >
          Concluir agora
        </Button>
      </div>
      <CommandErrorMessage error={send.error} />
    </div>
  )
}

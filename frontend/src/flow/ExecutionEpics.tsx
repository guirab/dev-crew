import { useId, useState } from 'react'
import { useSendCommand } from '../api/commands'
import { CommandErrorMessage } from '../bodies/CommandErrorMessage'
import b from '../bodies/body.module.css'
import { DeveloperBody } from '../bodies/DeveloperBody'
import { EpicList, selectionTotal } from '../bodies/EpicList'
import { TesterBody } from '../bodies/TesterBody'
import type { EpicView, TaskView } from '../contracts/generated'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { Escalation } from './Escalation'
import { EPIC_STATUS_LABEL, EPIC_TONE, laneView, lanesNeedingYou } from './lanes'
import type { EpicTone } from './lanes'
import { executionLanes } from './timeline'
import styles from './ExecutionEpics.module.css'

/** Grupos por quem age, na ordem da tela. */
const GROUPS: readonly { label: string; tones: readonly EpicTone[]; you?: true }[] = [
  { label: 'precisa de você', tones: ['attention'], you: true },
  { label: 'rodando', tones: ['running', 'preparing'] },
  { label: 'na fila', tones: ['queued'] },
  { label: 'prontos', tones: ['done'] },
]

/** O que vai à direita do título: "trabalhando", "espera E1 e E2", "juntando"... */
function laneNote(lane: EpicView, lanes: readonly EpicView[]): string {
  if (lane.status === 'running') return 'trabalhando'
  if (EPIC_TONE[lane.status] === 'queued') {
    const open = lane.depends_on.filter(
      (id) => lanes.find((other) => other.id === id)?.status !== 'merged',
    )
    return open.length > 0 ? `espera ${open.join(' e ')}` : ''
  }
  return lane.status === 'merged' || lane.status === 'escalated'
    ? ''
    : EPIC_STATUS_LABEL[lane.status]
}

function EpicBody({ view, lane }: { view: TaskView; lane: EpicView }) {
  if (lane.escalation) {
    return <Escalation reason={lane.escalation.reason} runs={lane.test_runs} epicId={lane.id} />
  }
  const goal = <p className={styles.goal}>{lane.goal || lane.title}</p>
  if (EPIC_TONE[lane.status] === 'queued') return goal
  const pseudo: TaskView = { ...laneView(view, lane), escalation: null }
  return (
    <>
      {goal}
      {lane.status === 'failed' && lane.stages.tester.now && (
        <p className={styles.fail}>{lane.stages.tester.now}</p>
      )}
      {lane.commit && <p className={cx(b.mono, b.muted)}>commit {lane.commit.slice(0, 8)}</p>}
      <DeveloperBody view={pseudo} stage={lane.stages.developer} />
      <TesterBody view={pseudo} stage={lane.stages.tester} />
    </>
  )
}

function EpicRow({
  view,
  lane,
  lanes,
  open,
  onToggle,
}: {
  view: TaskView
  lane: EpicView
  lanes: readonly EpicView[]
  open: boolean
  onToggle: () => void
}) {
  const bodyId = useId()
  const tone = EPIC_TONE[lane.status]
  const note = laneNote(lane, lanes)
  return (
    <li data-lane={lane.id} data-status={lane.status}>
      <button
        type="button"
        className={cx(styles.ep, styles[tone], open && styles.open)}
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        onClick={onToggle}
      >
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.id}>{lane.kind === 'integration' ? '⇄' : lane.id}</span>
        <span className={styles.ti}>{lane.title}</span>
        <span className={note === 'trabalhando' ? styles.work : styles.note}>{note}</span>
        <span className={styles.chev} aria-hidden="true">
          ›
        </span>
      </button>
      {open && (
        <div
          id={bodyId}
          className={styles.body}
          role="region"
          aria-label={`${lane.id} · ${lane.title}`}
        >
          <EpicBody view={view} lane={lane} />
        </div>
      )}
    </li>
  )
}

/**
 * Os épicos dentro do nó Execução, agrupados por quem age. Cada um é só id, título e estado; o que
 * precisa de você abre sozinho com o motivo, a saída do Tester e as ações.
 */
export function ExecutionEpics({ view }: { view: TaskView }) {
  const lanes = executionLanes(view)
  const needing = lanesNeedingYou(lanes).map((lane) => lane.id)
  // `undefined` = sem escolha: abre o primeiro que precisa de você. Muda o conjunto, volta pro automático.
  const [picked, setPicked] = useState<string | null | undefined>(undefined)
  const [needingKey, setNeedingKey] = useState(needing.join('|'))
  let choice = picked
  if (needing.join('|') !== needingKey) {
    setNeedingKey(needing.join('|'))
    choice = undefined
    setPicked(undefined)
  }
  const shown = choice === undefined ? (needing[0] ?? null) : choice

  if (lanes.length === 0) return <p className={styles.goal}>Preparando os épicos…</p>
  return (
    <div className={styles.groups}>
      {GROUPS.map((group) => {
        const members = lanes.filter((lane) => group.tones.includes(EPIC_TONE[lane.status]))
        if (members.length === 0) return null
        return (
          <section key={group.label} className={styles.grp} aria-label={group.label}>
            <h4 className={cx(styles.kicker, group.you && styles.you)}>{group.label}</h4>
            <ul>
              {members.map((lane) => (
                <EpicRow
                  key={lane.id}
                  view={view}
                  lane={lane}
                  lanes={lanes}
                  open={shown === lane.id}
                  onToggle={() => {
                    setPicked(shown === lane.id ? null : lane.id)
                  }}
                />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

/** Os épicos escolhidos ficaram prontos: rodar os próximos ou concluir com o que já foi feito. */
export function NextBatch({ view }: { view: TaskView }) {
  const send = useSendCommand()
  const epics = view.plan?.epics ?? []
  const pending = new Set(view.epics.filter((e) => e.status === 'pending').map((e) => e.id))
  const [picked, setPicked] = useState<ReadonlySet<string>>(() => new Set(pending))
  const toggle = (id: string) => {
    const next = new Set(picked)
    if (!next.delete(id)) next.add(id)
    setPicked(next)
  }
  const chosen = epics.map((e) => e.id).filter((id) => picked.has(id) && pending.has(id))

  return (
    <div role="group" aria-label="Próximos épicos">
      <h3 className={styles.title}>O que rodar agora?</h3>
      <p className={styles.goal}>
        Os épicos escolhidos estão prontos na branch. Rode os próximos ou termine aqui: o Reviewer
        revisa a tarefa inteira uma vez e os pendentes ficam registrados no plano.
      </p>
      <EpicList
        epics={epics.filter((e) => pending.has(e.id))}
        estimates={view.estimate?.epics ?? []}
        selection={{ selected: picked, onToggle: toggle }}
      />
      <div className={b.actionbar}>
        <Button
          disabled={send.isPending}
          onClick={() => {
            send.mutate({ type: 'finish_task' })
          }}
        >
          Terminar aqui
        </Button>
        <span className={b.total}>{selectionTotal(chosen, view.estimate?.epics ?? [])}</span>
        <Button
          variant="primary"
          disabled={send.isPending || chosen.length === 0}
          onClick={() => {
            send.mutate({ type: 'run_epics', epics: chosen })
          }}
        >
          {chosen.length === 1
            ? `Rodar ${chosen[0] ?? ''}`
            : `Rodar ${String(chosen.length)} épicos`}
        </Button>
      </div>
      <CommandErrorMessage error={send.error} />
    </div>
  )
}

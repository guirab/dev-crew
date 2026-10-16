import { useState } from 'react'
import { useSendCommand } from '../api/commands'
import { CommandErrorMessage } from '../bodies/CommandErrorMessage'
import b from '../bodies/body.module.css'
import { EpicList, selectionTotal } from '../bodies/EpicList'
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import type { EpicView, TaskView } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { Button } from '../ui/Button'
import { EpicBoard, EpicGraph } from './EpicBoard'
import { EpicSheet } from './EpicSheet'
import { EpicTable } from './EpicTable'
import { dependentsOf, epicsSummary, lanesNeedingYou, sortLanes } from './lanes'
import styles from './EpicsSection.module.css'

/**
 * Épicos de um plano dividido (D53): tabela densa por padrão, board e grafo como vistas alternativas.
 * O que precisa de você vira um Alert no topo; o detalhe do épico abre no painel lateral.
 */
export function EpicsSection({ view }: { view: TaskView }) {
  const openEpic = useCrewStore((s) => s.openEpic)
  const setOpenEpic = useCrewStore((s) => s.setOpenEpic)
  const lanes = view.epics
  const open = lanes.find((lane) => lane.id === openEpic) ?? null

  return (
    <section aria-label="Épicos">
      <Tabs defaultValue="table" className={styles.tabs}>
        <div className={styles.head}>
          <h2 className={styles.title}>Épicos</h2>
          <span className={styles.sum}>{epicsSummary(lanes)}</span>
          <TabsList aria-label="Vista dos épicos" className={styles.views}>
            <TabsTrigger value="table">Tabela</TabsTrigger>
            <TabsTrigger value="board">Board</TabsTrigger>
            <TabsTrigger value="graph">Grafo</TabsTrigger>
          </TabsList>
        </div>
        {view.phase === 'awaiting_selection' && <NextBatch view={view} />}
        {lanesNeedingYou(lanes).map((lane) => (
          <NeedsYouAlert key={lane.id} lane={lane} lanes={lanes} onOpen={setOpenEpic} />
        ))}
        <TabsContent value="table">
          <EpicTable lanes={sortLanes(lanes)} selected={openEpic} onOpen={setOpenEpic} />
        </TabsContent>
        <TabsContent value="board">
          <EpicBoard lanes={sortLanes(lanes)} onOpen={setOpenEpic} />
        </TabsContent>
        <TabsContent value="graph">
          <EpicGraph lanes={lanes} onOpen={setOpenEpic} />
        </TabsContent>
      </Tabs>
      <EpicSheet
        view={view}
        lane={open}
        onClose={() => {
          setOpenEpic(null)
        }}
      />
    </section>
  )
}

/** Um épico parado esperando você: título, motivo, quem espera por ele e as ações rápidas. */
function NeedsYouAlert({
  lane,
  lanes,
  onOpen,
}: {
  lane: EpicView
  lanes: readonly EpicView[]
  onOpen: (id: string) => void
}) {
  const send = useSendCommand()
  const waiting = dependentsOf(lanes, lane.id).map((dep) => dep.id)
  const reason = lane.escalation?.reason ?? 'O épico falhou'
  const sentence = /[.!?]$/.test(reason) ? reason : `${reason}.`
  const blocked =
    waiting.length > 0
      ? ` ${waiting.join(', ')} ${waiting.length === 1 ? 'está' : 'estão'} esperando o ${lane.id}.`
      : ''

  return (
    <Alert className={styles.alert} data-lane={lane.id}>
      <span className={styles.icon} aria-hidden="true">
        !
      </span>
      <AlertTitle className={styles.alertTitle}>
        {lane.id} · {lane.title} precisa de você
      </AlertTitle>
      <AlertDescription className={styles.alertText}>
        {sentence}
        {blocked}
      </AlertDescription>
      <div className={styles.alertActions}>
        <Button
          variant="primary"
          size="sm"
          onClick={() => {
            onOpen(lane.id)
          }}
        >
          Abrir {lane.id}
        </Button>
        {lane.escalation && (
          <Button
            size="sm"
            disabled={send.isPending}
            onClick={() => {
              send.mutate({ type: 'escalation', action: 'more_attempts', epic_id: lane.id })
            }}
          >
            +2 tentativas
          </Button>
        )}
      </div>
      <div className={styles.alertError}>
        <CommandErrorMessage error={send.error} />
      </div>
    </Alert>
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

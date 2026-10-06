import { useState } from 'react'
import { Connector } from '../flow/Connector'
import { LoopRail } from '../flow/LoopRail'
import { StageCard } from '../flow/StageCard'
import type { ConnectorId } from '../flow/stages'
import type { StageKey, StageStatus } from '../contracts/aliases'
import type { Counters, TaskView } from '../contracts/generated'
import { Button } from '../ui/Button'
import styles from './Gallery.module.css'

const STATUSES: readonly StageStatus[] = [
  'pick',
  'idle',
  'active',
  'waiting',
  'done',
  'error',
  'skipped',
]

const SAMPLE_NOW: Record<StageStatus, string> = {
  pick: 'Você descreve a tarefa',
  idle: 'Escreve e roda os testes',
  active: '$ pytest -q && npm test',
  waiting: 'Aguardando você — expanda pra revisar o plano',
  done: 'PASSOU · 48/48 · cobertura 87%',
  error: 'Limite 3/3 atingido — expanda pra decidir',
  skipped: 'Pulado — etapa não se aplica a esta tarefa.',
}

const COUNTERS: Counters = {
  dev_round: 2,
  test_attempt: 2,
  max_test_attempts: 3,
  review_round: 1,
  max_review_rounds: 2,
}

const CONNECTORS: readonly { id: ConnectorId; edges: TaskView['edges'] }[] = [
  { id: 'plan', edges: {} },
  { id: 'plan', edges: { 'pl-ap': 'on' } },
  { id: 'plan', edges: { 'pl-ap': 'active' } },
]

function GalleryCard({ stageKey, status }: { stageKey: StageKey; status: StageStatus }) {
  const [open, setOpen] = useState(false)
  return (
    <StageCard
      stageKey={stageKey}
      status={status}
      description={SAMPLE_NOW[status]}
      counters={COUNTERS}
      open={open}
      onToggle={() => {
        setOpen((o) => !o)
      }}
    >
      <p style={{ margin: 0 }}>Corpo expandido de exemplo ({status}).</p>
    </StageCard>
  )
}

/** `/dev/gallery` (só em dev): todos os status do StageCard, conectores e loops lado a lado. */
export default function Gallery() {
  return (
    <main className={styles.wrap}>
      <h1 className={styles.title}>
        <span className={styles.prompt}>&gt;</span> galeria
      </h1>

      <h2 className={styles.h2}>StageCard · todos os status</h2>
      <div className={styles.stack}>
        {STATUSES.map((status) => (
          <GalleryCard key={status} stageKey="tester" status={status} />
        ))}
      </div>

      <h2 className={styles.h2}>Connector · idle / on / active</h2>
      <div className={styles.row}>
        {CONNECTORS.map((c, i) => (
          <Connector key={i} id={c.id} edges={c.edges} />
        ))}
      </div>

      <h2 className={styles.h2}>LoopRail · falhou ativo, ajustes em uso</h2>
      <LoopRail edges={{ 'ts-dv': 'active', 'rv-dv': 'on' }}>
        <GalleryCard stageKey="developer" status="done" />
        <Connector id="develop" edges={{ 'dv-ts': 'on' }} />
        <GalleryCard stageKey="tester" status="error" />
        <Connector id="test" edges={{}} />
        <GalleryCard stageKey="reviewer" status="idle" />
      </LoopRail>

      <h2 className={styles.h2}>Botões</h2>
      <div className={styles.buttons}>
        <Button>Padrão</Button>
        <Button variant="primary">Primário</Button>
        <Button variant="primary" disabled>
          Desabilitado
        </Button>
        <Button variant="link">cancelar tarefa</Button>
      </div>
    </main>
  )
}

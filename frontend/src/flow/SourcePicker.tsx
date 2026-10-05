import { useId } from 'react'
import type { TaskView } from '../contracts/generated'
import { useRepoChoice } from '../bodies/RepoSelect'
import { ManualForm } from '../bodies/ManualForm'
import b from '../bodies/body.module.css'
import { cx } from '../lib/cx'
import { StageCard } from './StageCard'
import { stageDescription } from './stages'
import styles from './SourcePicker.module.css'

function TaskSummary({ view }: { view: TaskView }) {
  return (
    <>
      <div className={b.sec}>
        <h4>Tarefa</h4>
        <b>{view.title}</b>
        <p className={b.muted} style={{ margin: '4px 0 0' }}>
          {view.description}
        </p>
      </div>
      <div className={cx(b.sec, b.muted)}>Repo: {view.repo}</div>
    </>
  )
}

export type SourceKey = 'manual'

interface SourcePickerProps {
  view: TaskView | null
  open: SourceKey | null
  onOpenChange: (open: SourceKey | null) => void
}

/**
 * Card Manual + painel do formulário. Com tarefa ativa vira modo leitura
 * (uma tarefa por vez): mostra o resumo, sem formulário.
 */
export function SourcePicker({ view, open, onOpenChange }: SourcePickerProps) {
  const panelId = useId()
  const repoChoice = useRepoChoice()
  const close = () => {
    onOpenChange(null)
  }

  return (
    <>
      <div className={styles.row}>
        {(['manual'] as const).map((source) => {
          const stage = view?.stages[source] ?? null
          return (
            <StageCard
              key={source}
              stageKey={source}
              status={stage?.status ?? 'pick'}
              description={stageDescription(source, stage)}
              open={open === source}
              panelId={panelId}
              onToggle={() => {
                onOpenChange(open === source ? null : source)
              }}
            />
          )
        })}
      </div>
      {open && (
        <section id={panelId} className={styles.panel} aria-label={`Origem: ${open}`}>
          {view ? (
            <TaskSummary view={view} />
          ) : (
            <ManualForm repoChoice={repoChoice} onStarted={close} />
          )}
        </section>
      )}
    </>
  )
}

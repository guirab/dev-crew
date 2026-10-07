import { useId } from 'react'
import type { TaskView } from '../contracts/generated'
import { useRepoChoice } from '../bodies/RepoSelect'
import { ManualForm } from '../bodies/ManualForm'
import { NewProjectForm } from '../bodies/NewProjectForm'
import b from '../bodies/body.module.css'
import { cx } from '../lib/cx'
import { StageCard } from './StageCard'
import { NEW_PROJECT_META, stageDescription } from './stages'
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

export type SourceKey = 'manual' | 'project'

interface SourcePickerProps {
  view: TaskView | null
  open: SourceKey | null
  onOpenChange: (open: SourceKey | null) => void
}

/**
 * Cards de origem (Manual, Novo projeto) + painel do formulário. Com tarefa ativa só o Manual
 * fica, em modo leitura (uma tarefa por vez): mostra o resumo, sem formulário.
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
        <StageCard
          stageKey="manual"
          status={view?.stages.manual.status ?? 'pick'}
          description={stageDescription('manual', view?.stages.manual ?? null)}
          open={open === 'manual'}
          panelId={panelId}
          onToggle={() => {
            onOpenChange(open === 'manual' ? null : 'manual')
          }}
        />
        {!view && (
          <StageCard
            stageKey="manual"
            meta={NEW_PROJECT_META}
            domId="source-project"
            status="pick"
            description={NEW_PROJECT_META.desc}
            open={open === 'project'}
            panelId={panelId}
            onToggle={() => {
              onOpenChange(open === 'project' ? null : 'project')
            }}
          />
        )}
      </div>
      {open && (
        <section
          id={panelId}
          className={styles.panel}
          aria-label={open === 'project' ? 'Origem: novo projeto' : 'Origem: manual'}
        >
          {view ? (
            <TaskSummary view={view} />
          ) : open === 'project' ? (
            <NewProjectForm onStarted={close} />
          ) : (
            <ManualForm repoChoice={repoChoice} onStarted={close} />
          )}
        </section>
      )}
    </>
  )
}

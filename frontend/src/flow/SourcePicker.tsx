import { useId, useState } from 'react'
import { useRepoChoice } from '../bodies/RepoSelect'
import { AddRepoForm } from '../bodies/AddRepoForm'
import { ManualForm } from '../bodies/ManualForm'
import { NewProjectForm } from '../bodies/NewProjectForm'
import { cx } from '../lib/cx'
import { StageCard } from './StageCard'
import { ADD_REPO_META, NEW_PROJECT_META, STAGE_META } from './stages'
import styles from './SourcePicker.module.css'

export type SourceKey = 'manual' | 'project' | 'repo'

const SOURCE_LABEL: Record<SourceKey, string> = {
  manual: 'Origem: manual',
  project: 'Origem: novo projeto',
  repo: 'Origem: adicionar repositório',
}

/** Tela "Nova tarefa": cards de origem (Manual, Novo projeto, Adicionar repositório) + formulário. */
export function SourcePicker() {
  const panelId = useId()
  const repoChoice = useRepoChoice()
  const [open, setOpen] = useState<SourceKey | null>(null)
  const close = () => {
    setOpen(null)
  }
  const toggle = (key: SourceKey) => {
    setOpen(open === key ? null : key)
  }

  return (
    <>
      <div className={cx(styles.row, styles.three)}>
        <StageCard
          stageKey="manual"
          status="pick"
          description={STAGE_META.manual.desc}
          open={open === 'manual'}
          panelId={panelId}
          onToggle={() => {
            toggle('manual')
          }}
        />
        <StageCard
          stageKey="manual"
          meta={NEW_PROJECT_META}
          domId="source-project"
          status="pick"
          description={NEW_PROJECT_META.desc}
          open={open === 'project'}
          panelId={panelId}
          onToggle={() => {
            toggle('project')
          }}
        />
        <StageCard
          stageKey="manual"
          meta={ADD_REPO_META}
          domId="source-repo"
          status="pick"
          description={ADD_REPO_META.desc}
          open={open === 'repo'}
          panelId={panelId}
          onToggle={() => {
            toggle('repo')
          }}
        />
      </div>
      {!open && <p className={styles.hint}>escolha a origem da tarefa ↑</p>}
      {open && (
        <section id={panelId} className={styles.panel} aria-label={SOURCE_LABEL[open]}>
          {open === 'project' ? (
            <NewProjectForm onStarted={close} />
          ) : open === 'repo' ? (
            <AddRepoForm onAdded={close} />
          ) : (
            <ManualForm repoChoice={repoChoice} onStarted={close} />
          )}
        </section>
      )}
    </>
  )
}

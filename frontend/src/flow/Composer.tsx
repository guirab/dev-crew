import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useSendCommand } from '../api/commands'
import { AddRepoForm } from '../bodies/AddRepoForm'
import { CommandErrorMessage } from '../bodies/CommandErrorMessage'
import { NewProjectForm } from '../bodies/NewProjectForm'
import { RepoSelect, useRepoChoice } from '../bodies/RepoSelect'
import type { RepoAction } from '../bodies/RepoSelect'
import { Dialog, DialogContent, DialogTitle } from '../components/ui/dialog'
import { Button } from '../ui/Button'
import styles from './Composer.module.css'

const DIALOG_TITLE: Record<RepoAction, string> = {
  'new-project': 'Novo projeto',
  'add-folder': 'Adicionar pasta existente',
}

/**
 * Nova tarefa: título, detalhes e o repositório. Novo projeto e Adicionar pasta moram no menu do
 * repositório e abrem num diálogo.
 */
export function Composer() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dialog, setDialog] = useState<RepoAction | null>(null)
  const repoChoice = useRepoChoice()
  const send = useSendCommand()
  const { repo } = repoChoice
  const trimmed = title.trim()
  const canStart = !send.isPending && trimmed !== '' && repo !== null
  const close = () => {
    setDialog(null)
  }
  const start = () => {
    if (!canStart) return
    send.mutate({ type: 'start_task', repo, title: trimmed, description: description.trim() })
  }

  const ctrlEnter = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) start()
  }

  return (
    <section aria-label="Nova tarefa">
      <h2 className={styles.title}>O que a equipe vai fazer?</h2>
      <p className={styles.sub}>
        Descreva solto. O Entrevistador pergunta o que faltar antes do Planner entrar.
      </p>
      <div className={styles.compose}>
        <input
          className={styles.big}
          aria-label="título"
          placeholder="Ex.: Exportar pedidos filtrados em CSV"
          value={title}
          onKeyDown={ctrlEnter}
          onChange={(e) => {
            setTitle(e.target.value)
          }}
        />
        <textarea
          className={styles.details}
          aria-label="detalhes"
          placeholder="Detalhes, contexto, links… (opcional)"
          value={description}
          onKeyDown={ctrlEnter}
          onChange={(e) => {
            setDescription(e.target.value)
          }}
        />
        <div className={styles.foot}>
          <RepoSelect choice={repoChoice} onAction={setDialog} />
          <span className={styles.sp} />
          <span className={styles.hint}>Ctrl Enter</span>
          <Button variant="primary" disabled={!canStart} onClick={start}>
            {send.isPending ? 'Começando…' : 'Começar'}
          </Button>
        </div>
        <CommandErrorMessage error={send.error} />
      </div>
      <Dialog
        open={dialog !== null}
        onOpenChange={(next) => {
          if (!next) close()
        }}
      >
        <DialogContent
          aria-describedby={undefined}
          className="max-h-[85vh] gap-3 overflow-y-auto border border-(--glass-border) bg-(--glass-bg) p-5 shadow-(--glass-shadow) [-webkit-backdrop-filter:var(--glass-blur)] [backdrop-filter:var(--glass-blur)] sm:max-w-2xl"
        >
          {dialog && <DialogTitle>{DIALOG_TITLE[dialog]}</DialogTitle>}
          {dialog === 'new-project' && <NewProjectForm onStarted={close} />}
          {dialog === 'add-folder' && <AddRepoForm onAdded={close} />}
        </DialogContent>
      </Dialog>
    </section>
  )
}

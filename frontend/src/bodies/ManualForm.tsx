import { useState } from 'react'
import { useSendCommand } from '../api/commands'
import { Button } from '../ui/Button'
import { Field } from '../ui/Field'
import { CommandErrorMessage } from './CommandErrorMessage'
import { RepoSelect } from './RepoSelect'
import type { RepoChoice } from './RepoSelect'
import b from './body.module.css'

interface ManualFormProps {
  repoChoice: RepoChoice
  onStarted: () => void
}

/** Tarefa descrita à mão. Pode ser vaga: o Entrevistador pergunta o resto. */
export function ManualForm({ repoChoice, onStarted }: ManualFormProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const send = useSendCommand()
  const { repo } = repoChoice
  const trimmedTitle = title.trim()

  return (
    <>
      <Field label="título">
        {(id) => (
          <input
            id={id}
            value={title}
            placeholder="Exportar pedidos filtrados em CSV"
            onChange={(e) => {
              setTitle(e.target.value)
            }}
          />
        )}
      </Field>
      <Field label="descrição · pode ser vaga, o Entrevistador pergunta o resto">
        {(id) => (
          <textarea
            id={id}
            value={description}
            onChange={(e) => {
              setDescription(e.target.value)
            }}
          />
        )}
      </Field>
      <div className={b.row}>
        <RepoSelect choice={repoChoice} />
        <Button
          variant="primary"
          disabled={send.isPending || trimmedTitle === '' || repo === null}
          onClick={() => {
            if (repo === null) return
            send.mutate(
              {
                type: 'start_task',
                repo,
                title: trimmedTitle,
                description: description.trim(),
              },
              { onSuccess: onStarted },
            )
          }}
        >
          {send.isPending ? 'Iniciando…' : 'Iniciar'}
        </Button>
      </div>
      <CommandErrorMessage error={send.error} />
    </>
  )
}

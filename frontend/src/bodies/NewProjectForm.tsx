import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSendCommand } from '../api/commands'
import { reposQuery } from '../api/queries'
import { Button } from '../ui/Button'
import { Field } from '../ui/Field'
import { cx } from '../lib/cx'
import { NAME_RE } from '../lib/repoName'
import { CommandErrorMessage } from './CommandErrorMessage'
import b from './body.module.css'

/**
 * Projeto do zero (D58): o dev-crew cria a pasta, faz `git init` e o primeiro commit; o Planner
 * escolhe a stack e os comandos, e o plano começa pela fundação (E0).
 */
export function NewProjectForm({ onStarted }: { onStarted: () => void }) {
  const [name, setName] = useState('')
  const [parentDir, setParentDir] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const send = useSendCommand()
  const queryClient = useQueryClient()
  const trimmedName = name.trim()
  const trimmedTitle = title.trim()
  const badName = trimmedName !== '' && !NAME_RE.test(trimmedName)

  return (
    <>
      <div className={b.pair}>
        <Field label="nome do projeto · vira a pasta">
          {(id) => (
            <input
              id={id}
              value={name}
              placeholder="agenda-consultas"
              aria-invalid={badName}
              onChange={(e) => {
                setName(e.target.value)
              }}
            />
          )}
        </Field>
        <Field label="onde criar · vazio = Documentos">
          {(id) => (
            <input
              id={id}
              value={parentDir}
              placeholder="C:\Users\voce\Documents"
              onChange={(e) => {
                setParentDir(e.target.value)
              }}
            />
          )}
        </Field>
      </div>
      {badName && (
        <p className={b.muted}>Use letras, números, ponto, hífen ou _ (sem espaços, até 64).</p>
      )}
      <Field label="o que construir">
        {(id) => (
          <input
            id={id}
            value={title}
            placeholder="Agenda de consultas com lembretes"
            onChange={(e) => {
              setTitle(e.target.value)
            }}
          />
        )}
      </Field>
      <Field label="descrição · stack preferida, telas, regras (o Entrevistador pergunta o resto)">
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
      <p className={b.muted}>
        Cria a pasta com git e um primeiro commit. O plano define stack e comandos e começa pela
        fundação (E0).
      </p>
      <div className={cx(b.row, b.end)}>
        <Button
          variant="primary"
          disabled={send.isPending || trimmedTitle === '' || trimmedName === '' || badName}
          onClick={() => {
            send.mutate(
              {
                type: 'create_project',
                name: trimmedName,
                parent_dir: parentDir.trim(),
                title: trimmedTitle,
                description: description.trim(),
              },
              {
                onSuccess: () => {
                  void queryClient.invalidateQueries({ queryKey: reposQuery.queryKey })
                  onStarted()
                },
              },
            )
          }}
        >
          {send.isPending ? 'Criando…' : 'Criar e iniciar'}
        </Button>
      </div>
      <CommandErrorMessage error={send.error} />
    </>
  )
}

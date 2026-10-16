import { useId, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSendCommand } from '../api/commands'
import { reposQuery } from '../api/queries'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Label } from '../ui/Label'
import { cx } from '../lib/cx'
import { NAME_RE } from '../lib/repoName'
import { CommandErrorMessage } from './CommandErrorMessage'
import b from './body.module.css'

/**
 * Projeto do zero (D58): o dev-crew cria a pasta, faz `git init` e o primeiro commit; o Planner
 * escolhe a stack e os comandos, e o plano começa pela fundação (E0).
 */
export function NewProjectForm({ onStarted }: { onStarted: () => void }) {
  const uid = useId()
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
        <div className={b.field}>
          <Label htmlFor={`${uid}-name`}>nome do projeto · vira a pasta</Label>
          <Input
            id={`${uid}-name`}
            value={name}
            placeholder="agenda-consultas"
            aria-invalid={badName}
            onChange={(e) => {
              setName(e.target.value)
            }}
          />
        </div>
        <div className={b.field}>
          <Label htmlFor={`${uid}-parent`}>onde criar · vazio = Documentos</Label>
          <Input
            id={`${uid}-parent`}
            value={parentDir}
            placeholder="C:\Users\voce\Documents"
            onChange={(e) => {
              setParentDir(e.target.value)
            }}
          />
        </div>
      </div>
      {badName && (
        <p className={b.muted}>Use letras, números, ponto, hífen ou _ (sem espaços, até 64).</p>
      )}
      <div className={b.field}>
        <Label htmlFor={`${uid}-title`}>o que construir</Label>
        <Input
          id={`${uid}-title`}
          value={title}
          placeholder="Agenda de consultas com lembretes"
          onChange={(e) => {
            setTitle(e.target.value)
          }}
        />
      </div>
      <div className={b.field}>
        <Label htmlFor={`${uid}-description`}>
          descrição · stack preferida, telas, regras (o Entrevistador pergunta o resto)
        </Label>
        <textarea
          id={`${uid}-description`}
          value={description}
          onChange={(e) => {
            setDescription(e.target.value)
          }}
        />
      </div>
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

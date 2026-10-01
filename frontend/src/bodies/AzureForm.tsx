import { useState } from 'react'
import { useSendCommand } from '../api/commands'
import { useWorkItems } from '../api/queries'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { CommandErrorMessage } from './CommandErrorMessage'
import { RepoSelect } from './RepoSelect'
import type { RepoChoice } from './RepoSelect'
import a from './AzureForm.module.css'
import b from './body.module.css'

interface AzureFormProps {
  repoChoice: RepoChoice
  onStarted: () => void
}

/** Lista os work items (Azure, só leitura) e inicia a tarefa com o escolhido. */
export function AzureForm({ repoChoice, onStarted }: AzureFormProps) {
  const items = useWorkItems()
  const [picked, setPicked] = useState<number | null>(null)
  const send = useSendCommand()
  const { repo } = repoChoice

  return (
    <>
      <fieldset className={cx(b.sec, a.list)}>
        <legend className={a.legend}>Sprint atual · atribuídos a mim</legend>
        {items.isPending && <div className={b.muted}>carregando work items…</div>}
        {items.isError && (
          <div role="alert" className={b.error}>
            Não foi possível listar os work items.{' '}
            <Button
              size="sm"
              onClick={() => {
                void items.refetch()
              }}
            >
              Tentar de novo
            </Button>
          </div>
        )}
        {items.data?.length === 0 && (
          <div className={b.muted}>Nenhum work item atribuído a você nesta sprint.</div>
        )}
        {items.data?.map((item) => (
          <label key={item.id} className={cx(a.wi, picked === item.id && a.on)}>
            <input
              type="radio"
              name="work-item"
              className="sr-only"
              checked={picked === item.id}
              onChange={() => {
                setPicked(item.id)
              }}
            />
            <span className={b.mono}>#{item.id}</span>
            <span className={b.muted}>{item.type}</span>
            <span>{item.title}</span>
          </label>
        ))}
      </fieldset>
      <div className={cx(b.sec, b.row)}>
        <RepoSelect choice={repoChoice} />
        <Button
          variant="primary"
          disabled={send.isPending || picked === null || repo === null}
          onClick={() => {
            if (picked === null || repo === null) return
            send.mutate(
              { type: 'start_task', source: 'azure', repo, work_item_id: picked },
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

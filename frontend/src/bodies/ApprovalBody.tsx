import { useId, useState } from 'react'
import { useSendCommand } from '../api/commands'
import { formatTokens, formatUsd } from '../lib/format'
import { Button } from '../ui/Button'
import { Label } from '../ui/Label'
import { ActivityLog } from './ActivityLog'
import { CommandErrorMessage } from './CommandErrorMessage'
import { selectionTotal } from './EpicList'
import { Empty } from './Empty'
import { PlanView } from './PlanView'
import type { BodyProps } from './types'
import b from './body.module.css'

export function ApprovalBody({ view, stage }: BodyProps) {
  const adjustmentId = useId()
  const [adjustment, setAdjustment] = useState('')
  // null = ainda não mexeu: todos os épicos marcados
  const [picked, setPicked] = useState<ReadonlySet<string> | null>(null)
  const send = useSendCommand()

  if (!view?.plan) return <Empty>Aparece quando o Planner terminar.</Empty>
  if (stage.status !== 'waiting') {
    return (
      <>
        <PlanView plan={view.plan} estimate={view.estimate} />
        <ActivityLog logs={stage.logs} />
      </>
    )
  }

  const plan = view.plan
  const split = plan.execution === 'epics' && plan.epics.length > 0
  const selected = picked ?? new Set(plan.epics.map((e) => e.id))
  const toggle = (epicId: string) => {
    const next = new Set(selected)
    if (!next.delete(epicId)) next.add(epicId)
    setPicked(next)
  }
  const chosen = plan.epics.map((e) => e.id).filter((id) => selected.has(id))
  const text = adjustment.trim()
  return (
    <>
      <PlanView
        plan={plan}
        estimate={view.estimate}
        selection={split ? { selected, onToggle: toggle } : undefined}
      />
      <div className={b.sec}>
        <div className={b.field}>
          <Label htmlFor={adjustmentId}>ajuste pro Planner (opcional)</Label>
          <textarea
            id={adjustmentId}
            value={adjustment}
            placeholder="Ex.: não mexer no módulo de auth"
            onChange={(e) => {
              setAdjustment(e.target.value)
            }}
          />
        </div>
      </div>
      <div className={b.actionbar}>
        <span className={b.total}>
          {split
            ? selectionTotal(chosen, view.estimate)
            : view.estimate &&
              `~${formatTokens(view.estimate.tokens)} tokens · ~${formatUsd(view.estimate.usd)}`}
        </span>
        <Button
          disabled={send.isPending || text === ''}
          onClick={() => {
            send.mutate(
              { type: 'adjust_plan', text },
              {
                onSuccess: () => {
                  setAdjustment((current) => (current.trim() === text ? '' : current))
                },
              },
            )
          }}
        >
          Pedir ajuste
        </Button>
        <Button
          variant="primary"
          disabled={send.isPending || (split && selected.size === 0)}
          onClick={() => {
            send.mutate(split ? { type: 'approve_plan', epics: chosen } : { type: 'approve_plan' })
          }}
        >
          {split
            ? `Aprovar e rodar ${selected.size} épico${selected.size === 1 ? '' : 's'}`
            : 'Aprovar plano'}
        </Button>
      </div>
      <CommandErrorMessage error={send.error} />
    </>
  )
}

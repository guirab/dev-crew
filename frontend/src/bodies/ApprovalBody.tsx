import { useState } from 'react'
import { useSendCommand } from '../api/commands'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { Field } from '../ui/Field'
import { ActivityLog } from './ActivityLog'
import { CommandErrorMessage } from './CommandErrorMessage'
import { Empty } from './Empty'
import { PlanView } from './PlanView'
import type { BodyProps } from './types'
import b from './body.module.css'

export function ApprovalBody({ view, stage }: BodyProps) {
  const [adjustment, setAdjustment] = useState('')
  const send = useSendCommand()

  if (!view?.plan) return <Empty>Aparece quando o Planner terminar.</Empty>
  if (stage.status !== 'waiting') {
    return (
      <>
        <PlanView plan={view.plan} />
        <ActivityLog logs={stage.logs} />
      </>
    )
  }

  const text = adjustment.trim()
  return (
    <>
      <PlanView plan={view.plan} />
      <div className={b.sec}>
        <Field label="ajuste pro Planner (opcional)">
          {(id) => (
            <textarea
              id={id}
              value={adjustment}
              placeholder="Ex.: não mexer no módulo de auth"
              onChange={(e) => {
                setAdjustment(e.target.value)
              }}
            />
          )}
        </Field>
        <div className={cx(b.row, b.end)}>
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
            disabled={send.isPending}
            onClick={() => {
              send.mutate({ type: 'approve_plan' })
            }}
          >
            Aprovar plano
          </Button>
        </div>
        <CommandErrorMessage error={send.error} />
      </div>
    </>
  )
}

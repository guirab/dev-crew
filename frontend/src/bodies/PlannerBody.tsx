import { ActivityLog } from './ActivityLog'
import { Empty } from './Empty'
import { PlanView } from './PlanView'
import type { BodyProps } from './types'

export function PlannerBody({ view, stage }: BodyProps) {
  return (
    <>
      {view?.plan ? (
        <PlanView plan={view.plan} estimate={view.estimate} />
      ) : (
        <Empty>Ainda não gerou o plano.</Empty>
      )}
      <ActivityLog logs={stage.logs} />
    </>
  )
}

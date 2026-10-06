import type { JSX } from 'react'
import { ApprovalBody } from '../bodies/ApprovalBody'
import { DeveloperBody } from '../bodies/DeveloperBody'
import { DoneBody } from '../bodies/DoneBody'
import { InterviewBody } from '../bodies/InterviewBody'
import { PlannerBody } from '../bodies/PlannerBody'
import { ReviewerBody } from '../bodies/ReviewerBody'
import { TesterBody } from '../bodies/TesterBody'
import type { BodyProps } from '../bodies/types'
import type { FlowStageKey } from './stages'

const BODIES: Record<FlowStageKey, (props: BodyProps) => JSX.Element> = {
  interviewer: InterviewBody,
  planner: PlannerBody,
  approval: ApprovalBody,
  developer: DeveloperBody,
  tester: TesterBody,
  reviewer: ReviewerBody,
  done: DoneBody,
}

/** Corpo expandido de um estágio do fluxo (os cards de origem têm o painel do SourcePicker). */
export function StageBody({ stageKey, ...props }: BodyProps & { stageKey: FlowStageKey }) {
  const Body = BODIES[stageKey]
  return <Body {...props} />
}

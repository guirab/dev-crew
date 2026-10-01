// Aliases derivados dos tipos gerados (generated.ts não exporta os literais com nome).
// Nada aqui é redefinição de contrato: tudo sai de `TaskView`/`AgentProgress`.
import type { AgentProgress, Stages, StageView, TaskView } from './generated'

export type StageKey = keyof Stages
export type StageStatus = StageView['status']
export type EdgeKey = NonNullable<TaskView['active_edge']>
export type EdgeStatus = TaskView['edges'][string]
export type TaskPhase = TaskView['phase']
export type AgentName = AgentProgress['agent']

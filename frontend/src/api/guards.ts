import type { CommandReply, RepoInfo, TaskView, WsMessage } from '../contracts/generated'
import type { StageKey, TaskPhase } from '../contracts/aliases'

/**
 * Guardas estruturais pra dados que cruzam a rede (REST/WS/fixtures). São rasas de propósito:
 * o backend valida com Pydantic; aqui só impedimos que lixo/versão errada quebre a renderização.
 */

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

const STAGE_KEYS: readonly StageKey[] = [
  'manual',
  'interviewer',
  'planner',
  'approval',
  'developer',
  'tester',
  'reviewer',
  'done',
]

const PHASES: readonly TaskPhase[] = [
  'interviewing',
  'planning',
  'awaiting_approval',
  'developing',
  'testing',
  'reviewing',
  'escalated',
  'done',
  'cancelled',
  'failed',
]

const STATUSES: readonly unknown[] = [
  'idle',
  'pick',
  'active',
  'waiting',
  'done',
  'error',
  'skipped',
]

function isStageView(v: unknown): boolean {
  return (
    isRecord(v) &&
    STATUSES.includes(v.status) &&
    (v.now === null || typeof v.now === 'string') &&
    Array.isArray(v.logs)
  )
}

function isCounters(v: unknown): boolean {
  return (
    isRecord(v) &&
    typeof v.dev_round === 'number' &&
    typeof v.test_attempt === 'number' &&
    typeof v.max_test_attempts === 'number' &&
    typeof v.review_round === 'number' &&
    typeof v.max_review_rounds === 'number'
  )
}

export function isTaskView(v: unknown): v is TaskView {
  if (!isRecord(v)) return false
  const stages = v.stages
  return (
    typeof v.task_id === 'string' &&
    typeof v.title === 'string' &&
    typeof v.repo === 'string' &&
    PHASES.some((p) => p === v.phase) &&
    isRecord(stages) &&
    STAGE_KEYS.every((k) => isStageView(stages[k])) &&
    isRecord(v.edges) &&
    isCounters(v.counters) &&
    Array.isArray(v.dev_rounds) &&
    Array.isArray(v.test_runs)
  )
}

export function isNullableTaskView(v: unknown): v is TaskView | null {
  return v === null || isTaskView(v)
}

export function isWsMessage(v: unknown): v is WsMessage {
  if (!isRecord(v)) return false
  if (v.type === 'view') return isNullableTaskView(v.data)
  if (v.type === 'progress') {
    return (
      typeof v.task_id === 'string' &&
      isRecord(v.data) &&
      typeof v.data.agent === 'string' &&
      typeof v.data.text === 'string'
    )
  }
  return false
}

export function isCommandReply(v: unknown): v is CommandReply {
  return (
    isRecord(v) &&
    typeof v.ok === 'boolean' &&
    (v.error === undefined || v.error === null || typeof v.error === 'string') &&
    (v.view === undefined || isNullableTaskView(v.view))
  )
}

export function isRepoList(v: unknown): v is RepoInfo[] {
  return (
    Array.isArray(v) &&
    v.every((r) => isRecord(r) && typeof r.name === 'string' && typeof r.base_branch === 'string')
  )
}

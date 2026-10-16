/**
 * Estados derivados das fixtures do contrato, pra desenhar as telas que o cenário vivo não alcança
 * (`?fixture=<nome>`): épicos, próximo lote, limite de uso e falha.
 */
import type { EpicView, StageView, TaskView } from '../contracts/generated'
import { demoEpicPlan, demoLanes } from './epics'

type Load = (name: string) => Promise<TaskView>

const idle: StageView = { status: 'idle', now: null, logs: [] }

function epicsView(view: TaskView): TaskView {
  return {
    ...view,
    phase: 'executing',
    plan: view.plan && {
      ...view.plan,
      execution: 'epics',
      epics: demoEpicPlan(),
      split_rationale: 'E1, E2, E4, E5 e E6 mexem em arquivos separados; E3 espera o E2.',
    },
    stages: { ...view.stages, developer: idle, tester: idle, reviewer: idle },
    epics: demoLanes(view.task_id, view.repo, new Date()),
  }
}

/** Primeiro lote pronto: E3 e E6 ficaram de fora e esperam a escolha do próximo lote. */
function nextBatch(view: TaskView): TaskView {
  const base = epicsView(view)
  const done = (s: StageView): StageView => ({ ...s, status: 'done' })
  const epics = base.epics.map((lane): EpicView => {
    if (lane.kind === 'review' || lane.id === 'E3' || lane.id === 'E6') {
      return { ...lane, status: 'pending' }
    }
    return {
      ...lane,
      status: 'merged',
      escalation: null,
      commit: lane.commit ?? `${lane.id.toLowerCase()}9f3c1a20b7`,
      stages: {
        developer: done(lane.stages.developer),
        tester: done(lane.stages.tester),
        reviewer: done(lane.stages.reviewer),
      },
    }
  })
  return { ...base, phase: 'awaiting_selection', epics }
}

export const DEMO_VIEWS: Readonly<Record<string, (load: Load) => Promise<TaskView>>> = {
  epics: async (load) => epicsView(await load('developing')),
  'next-batch': async (load) => nextBatch(await load('developing')),
  limited: async (load) => {
    const view = await load('developing')
    return {
      ...view,
      phase: 'limited',
      limit: {
        kind: 'session',
        resets_at: new Date(Date.now() + 72 * 60_000).toISOString(),
        message: 'Limite da sessão da assinatura',
      },
    }
  },
  failed: async (load) => {
    const view = await load('developing')
    const developer = view.stages.developer
    return {
      ...view,
      phase: 'failed',
      ended_at: new Date().toISOString(),
      stages: {
        ...view.stages,
        developer: {
          status: 'error',
          now: 'npm ci saiu com código 1 no container',
          logs: [
            ...developer.logs,
            {
              ts: developer.logs.at(-1)?.ts ?? view.started_at,
              text: 'npm ERR! Missing: @js-temporal/polyfill@0.4.4 from lock file',
            },
          ],
        },
      },
    }
  },
}

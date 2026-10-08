import { beforeEach, describe, expect, it } from 'vitest'
import { fixture } from '../test/fixtures'
import { isRunning, resetCrewStore, useCrewStore } from './crew'

const progress = (task_id: string, text: string, agent: 'developer' | 'tester' = 'developer') =>
  ({
    type: 'progress',
    task_id,
    data: { agent, job_id: 'j1', kind: 'tool', text },
  }) as const

describe('useCrewStore', () => {
  beforeEach(() => {
    resetCrewStore()
  })

  it('applyView guarda o snapshot, marca hidratado e descarta o progresso', () => {
    const store = useCrewStore.getState()
    store.applyView(fixture('developing'))
    store.applyProgress(progress('T-107', 'Editando a.py'))
    expect(useCrewStore.getState().progress.developer).toHaveLength(1)

    useCrewStore.getState().applyView(fixture('developing'))
    const state = useCrewStore.getState()
    expect(state.hydrated).toBe(true)
    expect(state.progress).toEqual({})
    expect(state.viewVersion).toBe(2)
  })

  it('progress acumula por agente (máx. 50) e ignora outra tarefa ou ausência de view', () => {
    const { applyView, applyProgress } = useCrewStore.getState()
    applyProgress(progress('T-107', 'antes da view'))
    expect(useCrewStore.getState().progress).toEqual({})

    applyView(fixture('developing'))
    for (let i = 0; i < 55; i++) applyProgress(progress('T-107', `linha ${i}`))
    applyProgress(progress('T-999', 'outra tarefa'))
    applyProgress(progress('T-107', 'teste rodando', 'tester'))

    const state = useCrewStore.getState()
    expect(state.progress.developer).toHaveLength(50)
    expect(state.progress.developer?.at(-1)?.text).toBe('linha 54')
    expect(state.progress.tester?.[0]?.text).toBe('teste rodando')
  })

  it('hydrate (REST) é descartado se um snapshot do WS chegou no meio', () => {
    const store = useCrewStore.getState()
    const sinceVersion = store.viewVersion
    store.applyView(fixture('developing')) // WS chegou antes do REST responder
    useCrewStore.getState().hydrate(fixture('planning'), sinceVersion)

    const state = useCrewStore.getState()
    expect(state.view?.phase).toBe('developing')
    expect(state.hydrated).toBe(true)
  })

  it('hydrate aplica quando nada mais chegou', () => {
    const store = useCrewStore.getState()
    store.hydrate(fixture('planning'), store.viewVersion)
    expect(useCrewStore.getState().view?.phase).toBe('planning')
  })

  it('abre sempre no menu de nova tarefa, mesmo com uma tarefa terminal no primeiro snapshot', () => {
    expect(useCrewStore.getState().screen).toBe('new')
    useCrewStore.getState().applyView(fixture('done'))
    expect(useCrewStore.getState().screen).toBe('new')
  })

  it('o snapshot do REST na abertura também não troca a tela', () => {
    const store = useCrewStore.getState()
    store.hydrate(fixture('developing'), store.viewVersion)
    expect(useCrewStore.getState().screen).toBe('new')
  })

  it('tarefa nova depois do primeiro snapshot abre o fluxo; reconexão com a mesma não mexe', () => {
    const store = useCrewStore.getState()
    store.applyView(null)
    store.setScreen('history')
    useCrewStore.getState().applyView(fixture('interviewing'))
    expect(useCrewStore.getState().screen).toBe('task')

    useCrewStore.getState().setScreen('new')
    useCrewStore.getState().applyView({ ...fixture('interviewing'), phase: 'developing' }) // mesmo task_id
    expect(useCrewStore.getState().screen).toBe('new')

    useCrewStore.getState().applyView({ ...fixture('interviewing'), task_id: 'T-109' })
    expect(useCrewStore.getState().screen).toBe('task')
  })

  it('voltar a "sem tarefa" não troca a tela', () => {
    const store = useCrewStore.getState()
    store.applyView(fixture('developing'))
    store.setScreen('history')
    useCrewStore.getState().applyView(null)
    expect(useCrewStore.getState().screen).toBe('history')
  })

  it('isRunning: toda fase não terminal conta', () => {
    expect(isRunning(null)).toBe(false)
    for (const phase of ['awaiting_approval', 'escalated', 'limited', 'developing'] as const) {
      expect(isRunning({ ...fixture('developing'), phase }), phase).toBe(true)
    }
    for (const phase of ['done', 'cancelled', 'failed'] as const) {
      expect(isRunning({ ...fixture('done'), phase }), phase).toBe(false)
    }
  })

  it('setConnection', () => {
    useCrewStore.getState().setConnection('closed')
    expect(useCrewStore.getState().connection).toBe('closed')
  })
})

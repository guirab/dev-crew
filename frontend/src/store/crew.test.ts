import { beforeEach, describe, expect, it } from 'vitest'
import { fixture } from '../test/fixtures'
import { resetCrewStore, selectActiveView, useCrewStore } from './crew'

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

  it('dismissTask esconde só a tarefa dispensada; uma nova tarefa volta a aparecer', () => {
    useCrewStore.getState().applyView(fixture('done'))
    expect(selectActiveView(useCrewStore.getState())?.task_id).toBe('T-107')

    useCrewStore.getState().dismissTask()
    expect(selectActiveView(useCrewStore.getState())).toBeNull()

    useCrewStore.getState().applyView({ ...fixture('planning'), task_id: 'T-108' })
    expect(selectActiveView(useCrewStore.getState())?.task_id).toBe('T-108')
  })

  it('setConnection', () => {
    useCrewStore.getState().setConnection('closed')
    expect(useCrewStore.getState().connection).toBe('closed')
  })
})

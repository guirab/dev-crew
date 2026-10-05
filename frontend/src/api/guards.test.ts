import { describe, expect, it } from 'vitest'
import { fixture, fixtures } from '../test/fixtures'
import { isCommandReply, isNullableTaskView, isRepoList, isTaskView, isWsMessage } from './guards'

describe('isTaskView', () => {
  it('aceita as 8 fixtures do contrato', () => {
    expect(Object.keys(fixtures)).toHaveLength(8)
    for (const [name, view] of Object.entries(fixtures)) {
      expect(isTaskView(view), name).toBe(true)
    }
  })

  it('recusa lixo, fase desconhecida e estágio faltando', () => {
    const base = fixture('planning')
    expect(isTaskView(null)).toBe(false)
    expect(isTaskView('x')).toBe(false)
    expect(isTaskView({})).toBe(false)
    expect(isTaskView({ ...base, phase: 'dancing' })).toBe(false)
    expect(isTaskView({ ...base, stages: { ...base.stages, tester: undefined } })).toBe(false)
    expect(isTaskView({ ...base, counters: { dev_round: 1 } })).toBe(false)
  })

  it('null é um snapshot válido pro WS/REST ("sem tarefa")', () => {
    expect(isNullableTaskView(null)).toBe(true)
  })
})

describe('isWsMessage', () => {
  it('aceita view (com tarefa e null) e progress', () => {
    expect(isWsMessage({ type: 'view', data: fixture('done') })).toBe(true)
    expect(isWsMessage({ type: 'view', data: null })).toBe(true)
    expect(
      isWsMessage({
        type: 'progress',
        task_id: 'T-1',
        data: { agent: 'developer', job_id: 'j', kind: 'tool', text: 'Editando x' },
      }),
    ).toBe(true)
  })

  it('recusa tipos desconhecidos e payload quebrado', () => {
    expect(isWsMessage({ type: 'ping' })).toBe(false)
    expect(isWsMessage({ type: 'view', data: { task_id: 'T-1' } })).toBe(false)
    expect(isWsMessage({ type: 'progress', data: {} })).toBe(false)
    expect(isWsMessage('view')).toBe(false)
  })
})

describe('listas e respostas', () => {
  it('isRepoList', () => {
    expect(isRepoList([{ name: 'a', base_branch: 'main' }])).toBe(true)
    expect(isRepoList([{ name: 'a' }])).toBe(false)
  })

  it('isCommandReply tolera error/view ausentes', () => {
    expect(isCommandReply({ ok: true })).toBe(true)
    expect(isCommandReply({ ok: false, error: 'x', view: null })).toBe(true)
    expect(isCommandReply({ error: 'x' })).toBe(false)
  })
})

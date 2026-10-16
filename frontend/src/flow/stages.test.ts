import { describe, expect, it } from 'vitest'
import type { StageView } from '../contracts/generated'
import { withProgress } from './stages'

const stage = (overrides: Partial<StageView>): StageView => ({
  status: 'idle',
  now: null,
  logs: [],
  ...overrides,
})

describe('withProgress', () => {
  const active = stage({
    status: 'active',
    now: 'antes',
    logs: [{ ts: '2026-10-01T12:00:00Z', text: 'a' }],
  })
  const lines = [{ ts: '2026-10-01T12:00:05Z', text: 'Editando src/x.py' }]

  it('sobrepõe a última linha e anexa o log no estágio ativo', () => {
    const result = withProgress(active, lines)
    expect(result.now).toBe('Editando src/x.py')
    expect(result.logs).toHaveLength(2)
  })

  it('ignora progresso fora do estágio ativo ou vazio', () => {
    const done = stage({ status: 'done', now: 'ok' })
    expect(withProgress(done, lines)).toBe(done)
    expect(withProgress(active, [])).toBe(active)
    expect(withProgress(active, undefined)).toBe(active)
  })
})

import { describe, expect, it } from 'vitest'
import { formatDateTime, formatResetTime, formatTokens } from './format'

describe('formatResetTime', () => {
  const now = new Date(2026, 9, 6, 10, 0)

  it('hoje: só a hora', () => {
    expect(formatResetTime(new Date(2026, 9, 6, 15, 0).toISOString(), now)).toBe('às 15:00')
  })

  it('outro dia: dia da semana e hora', () => {
    const text = formatResetTime(new Date(2026, 9, 10, 12, 0).toISOString(), now)
    expect(text).toMatch(/^\S+ às 12:00$/)
  })

  it('ISO inválido: vazio', () => {
    expect(formatResetTime('x', now)).toBe('')
  })
})

describe('formatTokens', () => {
  it.each([
    [0, '0'],
    [999, '999'],
    [1234, '1,2 mil'],
    [2_500_000, '2,5 mi'],
  ])('%d → %s', (value, expected) => {
    expect(formatTokens(value)).toBe(expected)
  })
})

describe('formatDateTime', () => {
  it('data e hora locais', () => {
    expect(formatDateTime(new Date(2026, 9, 7, 14, 5).toISOString())).toBe('07/10/2026 14:05')
  })

  it('ISO inválido: vazio', () => {
    expect(formatDateTime('x')).toBe('')
  })
})

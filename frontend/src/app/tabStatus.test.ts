import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import type { TaskView } from '../contracts/generated'
import { fixture } from '../test/fixtures'
import { FAVICON_HREF, tabStatus, truncate, type FaviconKind } from './tabStatus'

function view(
  overrides: Partial<TaskView> & { interviewer?: TaskView['stages']['interviewer']['status'] },
): TaskView {
  const { interviewer, ...rest } = overrides
  const base = { ...fixture('interviewing'), title: 'Exportar CSV', escalation: null, ...rest }
  if (!interviewer) return base
  return {
    ...base,
    stages: { ...base.stages, interviewer: { ...base.stages.interviewer, status: interviewer } },
  }
}

describe('tabStatus', () => {
  it('sem tarefa: título e ícone base', () => {
    expect(tabStatus(null)).toEqual({ title: 'Dev Crew', favicon: 'base' })
  })

  it('interviewing waiting pede você', () => {
    expect(tabStatus(view({ phase: 'interviewing', interviewer: 'waiting' }))).toEqual({
      title: '● Precisa de você: responda a entrevista · Exportar CSV · Dev Crew',
      favicon: 'attention',
    })
  })

  it('interviewing active mostra o Entrevistador trabalhando', () => {
    expect(tabStatus(view({ phase: 'interviewing', interviewer: 'active' }))).toEqual({
      title: 'Entrevistador trabalhando · Exportar CSV · Dev Crew',
      favicon: 'working',
    })
  })

  it('awaiting_approval pede aprovação', () => {
    expect(tabStatus(view({ phase: 'awaiting_approval' }))).toEqual({
      title: '● Precisa de você: aprove o plano · Exportar CSV · Dev Crew',
      favicon: 'attention',
    })
  })

  it('escalated usa o nome do estágio', () => {
    const escalation = { stage: 'tester' as const, reason: 'sem progresso' }
    expect(tabStatus(view({ phase: 'escalated', escalation }))).toEqual({
      title: '● Precisa de você: escalada: Tester · Exportar CSV · Dev Crew',
      favicon: 'attention',
    })
  })

  it('escalated sem detalhe da escalada ainda pede você', () => {
    expect(tabStatus(view({ phase: 'escalated' })).title).toBe(
      '● Precisa de você: escalada · Exportar CSV · Dev Crew',
    )
  })

  it.each([
    ['planning', 'Planner'],
    ['developing', 'Developer'],
    ['testing', 'Tester'],
    ['reviewing', 'Reviewer'],
  ] as const)('%s: %s trabalhando', (phase, agent) => {
    expect(tabStatus(view({ phase }))).toEqual({
      title: `${agent} trabalhando · Exportar CSV · Dev Crew`,
      favicon: 'working',
    })
  })

  it.each([
    ['done', '✓ Concluída', 'done'],
    ['failed', '✗ Falhou', 'error'],
    ['cancelled', '⊘ Cancelada', 'error'],
  ] as const)('fase terminal %s', (phase, state, favicon) => {
    expect(tabStatus(view({ phase }))).toEqual({
      title: `${state} · Exportar CSV · Dev Crew`,
      favicon,
    })
  })

  it('trunca título longo em 40 caracteres com … e mantém o estado visível', () => {
    const long = 'x'.repeat(41)
    const { title } = tabStatus(view({ phase: 'done', title: long }))
    expect(title).toBe(`✓ Concluída · ${'x'.repeat(40)}… · Dev Crew`)
  })

  it('mantém título curto intacto', () => {
    expect(truncate('x'.repeat(40), 40)).toBe('x'.repeat(40))
  })

  it('título com exatamente 40 caracteres não leva …', () => {
    const { title } = tabStatus(view({ phase: 'done', title: 'x'.repeat(40) }))
    expect(title).toBe(`✓ Concluída · ${'x'.repeat(40)} · Dev Crew`)
  })
})

describe('assets do favicon', () => {
  const root = resolve(__dirname, '../..')
  const colors: [FaviconKind, string][] = [
    ['base', '#2bee86'],
    ['attention', '#f4b544'],
    ['working', '#2bee86'],
    ['done', '#2bee86'],
    ['error', '#ff5d5d'],
  ]

  it.each(colors)('SVG estático de %s existe com a cor do token', (kind, color) => {
    const svg = readFileSync(resolve(root, 'public', FAVICON_HREF[kind].slice(1)), 'utf8')
    expect(svg).toContain('viewBox="0 0 32 32"')
    expect(svg.toLowerCase()).toContain(color)
  })

  it('index.html referencia o ícone base num <link rel="icon"> estático', () => {
    const html = readFileSync(resolve(root, 'index.html'), 'utf8')
    expect(html).toMatch(/<link[^>]*rel="icon"[^>]*href="\/favicon\.svg"/)
    expect(html).toContain('<title>Dev Crew</title>')
  })
})

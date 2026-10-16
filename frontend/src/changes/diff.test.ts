import { describe, expect, it } from 'vitest'
import { diffRows } from './diff'

describe('diffRows', () => {
  it('numera antes/depois a partir do hunk e ignora o cabeçalho do git', () => {
    const patch = [
      'diff --git a/x b/x',
      '--- a/x',
      '+++ b/x',
      '@@ -10,3 +10,4 @@ fn',
      ' ctx',
      '-old',
      '+new',
      '+more',
      '\\ No newline at end of file',
      '@@ -40 +41 @@',
      ' tail',
    ].join('\r\n')
    expect(diffRows(patch)).toEqual([
      { kind: 'hunk', old: null, new: null, text: '@@ -10,3 +10,4 @@ fn' },
      { kind: 'ctx', old: 10, new: 10, text: 'ctx' },
      { kind: 'del', old: 11, new: null, text: 'old' },
      { kind: 'add', old: null, new: 11, text: 'new' },
      { kind: 'add', old: null, new: 12, text: 'more' },
      { kind: 'hunk', old: null, new: null, text: '@@ -40 +41 @@' },
      { kind: 'ctx', old: 40, new: 41, text: 'tail' },
    ])
  })

  it('sem hunk não há linhas', () => {
    expect(diffRows('')).toEqual([])
    expect(diffRows('Binary files differ')).toEqual([])
  })
})

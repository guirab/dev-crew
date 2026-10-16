/** Uma linha do diff unificado com os números de linha antes/depois (`null` onde não existe). */
export interface DiffRow {
  kind: 'hunk' | 'add' | 'del' | 'ctx'
  old: number | null
  new: number | null
  text: string
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/** Patch do git em linhas numeradas, a partir do primeiro hunk (o cabeçalho só repete o caminho). */
export function diffRows(patch: string): DiffRow[] {
  const lines = patch.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n')
  const first = lines.findIndex((line) => line.startsWith('@@'))
  if (first === -1) return []
  let oldLine = 0
  let newLine = 0
  const rows: DiffRow[] = []
  for (const line of lines.slice(first)) {
    const hunk = HUNK.exec(line)
    if (hunk) {
      oldLine = Number(hunk[1])
      newLine = Number(hunk[2])
      rows.push({ kind: 'hunk', old: null, new: null, text: line })
    } else if (line.startsWith('\\')) {
      continue // "\ No newline at end of file"
    } else if (line.startsWith('+')) {
      rows.push({ kind: 'add', old: null, new: newLine++, text: line.slice(1) })
    } else if (line.startsWith('-')) {
      rows.push({ kind: 'del', old: oldLine++, new: null, text: line.slice(1) })
    } else {
      rows.push({ kind: 'ctx', old: oldLine++, new: newLine++, text: line.slice(1) })
    }
  }
  return rows
}

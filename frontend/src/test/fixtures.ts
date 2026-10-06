import type { TaskView } from '../contracts/generated'
import { isTaskView } from '../api/guards'

const modules = import.meta.glob('../../../contracts/fixtures/view.*.json', {
  eager: true,
  import: 'default',
})

/** Todas as fixtures de `contracts/fixtures`, por nome (`escalated`, `done`, ...). */
export const fixtures: Record<string, TaskView> = {}

for (const [path, data] of Object.entries(modules)) {
  const name = /view\.([\w-]+)\.json$/.exec(path)?.[1]
  if (!name) continue
  if (!isTaskView(data)) throw new Error(`fixture ${name} fora do contrato`)
  fixtures[name] = data
}

export function fixture(name: string): TaskView {
  const view = fixtures[name]
  if (!view) throw new Error(`fixture ${name} não encontrada`)
  return view
}

import type { TaskView } from '../contracts/generated'
import { isTaskView } from '../api/guards'
import type { CommandOutcome, MockBackend } from './backend'
import { REPOS } from './data'

const fixtureLoaders = import.meta.glob('../../../contracts/fixtures/view.*.json', {
  import: 'default',
})

const FIXTURE_NAME = /view\.([\w-]+)\.json$/

export function fixtureNames(): string[] {
  return Object.keys(fixtureLoaders)
    .map((path) => FIXTURE_NAME.exec(path)?.[1])
    .filter((name): name is string => name !== undefined)
    .sort()
}

/** Carrega `contracts/fixtures/view.<name>.json` e valida contra o contrato antes de usar. */
export async function loadFixture(name: string): Promise<TaskView> {
  const path = Object.keys(fixtureLoaders).find((p) => FIXTURE_NAME.exec(p)?.[1] === name)
  const loader = path ? fixtureLoaders[path] : undefined
  if (!loader) {
    throw new Error(`Fixture "${name}" não existe. Disponíveis: ${fixtureNames().join(', ')}`)
  }
  const data = await loader()
  if (!isTaskView(data)) throw new Error(`Fixture "${name}" não bate com o contrato TaskView.`)
  return data
}

/** Backend de uma fixture estática: sempre devolve o mesmo snapshot; comandos são recusados. */
export class FixtureBackend implements MockBackend {
  readonly repos = REPOS

  constructor(
    private readonly view: TaskView,
    readonly name: string,
  ) {}

  getView(): TaskView {
    return this.view
  }

  subscribe(): () => void {
    return () => undefined
  }

  handle(): CommandOutcome {
    return {
      status: 409,
      reply: { ok: false, error: 'Modo fixture: somente leitura.', view: null },
    }
  }

  dispose(): void {
    // nada a liberar: o snapshot é estático
  }
}

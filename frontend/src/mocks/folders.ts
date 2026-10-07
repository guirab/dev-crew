import type {
  AddRepo,
  FolderEntry,
  FolderListing,
  FolderProbe,
  RepoInfo,
  TaskView,
} from '../contracts/generated'
import { NAME_RE } from '../lib/repoName'
import type { CommandOutcome } from './backend'
import { FAKE_DRIVES, FAKE_PROJECTS_DIR, REPOS, REPO_PATHS } from './data'
import type { FakeFolder } from './data'

const SEP = '\\'

/** `C:\\a\\b`, `C:/a/b` e `C:` viram `['C:', 'a', 'b']` (a unidade e as pastas, sem vazios). */
function parts(path: string): string[] {
  return path.split(/[\\/]+/).filter((p) => p !== '')
}

function join(segments: readonly string[]): string {
  if (segments.length === 0) return ''
  const [drive, ...rest] = segments
  return rest.length === 0 ? `${drive}${SEP}` : `${drive}${SEP}${rest.join(SEP)}`
}

function samePath(a: string, b: string): boolean {
  return join(parts(a)).toLowerCase() === join(parts(b)).toLowerCase()
}

/** Sistema de arquivos fictício do modo mock + o cadastro de repos adicionados pela UI. */
export class MockFolders {
  private readonly added: { repo: RepoInfo; path: string }[] = []
  private readonly initialized = new Map<string, string>()

  get repos(): readonly RepoInfo[] {
    return [...REPOS, ...this.added.map((a) => a.repo)]
  }

  private registeredPaths(): string[] {
    return [...Object.values(REPO_PATHS), ...this.added.map((a) => a.path)]
  }

  private isRegistered(path: string): boolean {
    return this.registeredPaths().some((p) => samePath(p, path))
  }

  /** Nós do caminho (unidade → pasta), ou `null` se algum segmento não existe. */
  private chain(path: string): FakeFolder[] | null {
    const [drive, ...rest] = parts(path)
    if (drive === undefined) return null
    const root: FakeFolder | undefined = FAKE_DRIVES[drive.toUpperCase()]
    if (!root) return null
    const nodes = [root]
    for (const segment of rest) {
      const dirs: Readonly<Record<string, FakeFolder>> = nodes[nodes.length - 1]?.dirs ?? {}
      const key = Object.keys(dirs).find((k) => k.toLowerCase() === segment.toLowerCase())
      const child = key === undefined ? undefined : dirs[key]
      if (!child) return null
      nodes.push(child)
    }
    return nodes
  }

  list(path: string | undefined): FolderListing | null {
    if (path === '') {
      const entries: FolderEntry[] = Object.keys(FAKE_DRIVES).map((drive) => ({
        name: drive,
        path: join([drive]),
        git_repo: false,
        registered: false,
      }))
      return { path: '', parent: null, entries }
    }
    const start = path ?? FAKE_PROJECTS_DIR
    const nodes = this.chain(start)
    const node = nodes?.[nodes.length - 1]
    if (!nodes || !node) return null
    const here = parts(start)
    const entries = Object.entries(node.dirs ?? {})
      .sort(([a], [b]) => a.localeCompare(b, 'pt-BR', { sensitivity: 'base' }))
      .map(([name, child]): FolderEntry => {
        const childPath = join([...here, name])
        return {
          name,
          path: childPath,
          git_repo: child.git !== undefined || this.initialized.has(childPath),
          registered: this.isRegistered(childPath),
        }
      })
    return {
      path: join(here),
      parent: here.length > 1 ? join(here.slice(0, -1)) : '',
      entries,
    }
  }

  probe(path: string): FolderProbe | null {
    const nodes = this.chain(path)
    const node = nodes?.[nodes.length - 1]
    if (!nodes || !node) return null
    const segments = parts(path)
    const normalized = join(segments)
    const base = { path: normalized, name: segments[segments.length - 1] ?? normalized }
    const registered = this.isRegistered(normalized)
    const initialBranch = this.initialized.get(normalized)
    if (initialBranch !== undefined) {
      return { ...base, git: 'ready', branch: initialBranch, registered }
    }
    if (nodes.slice(0, -1).some((n) => n.git !== undefined)) {
      return { ...base, git: 'inside_repo', branch: null, registered }
    }
    if (node.git === undefined) return { ...base, git: 'none', branch: null, registered }
    return {
      ...base,
      git: node.git,
      branch: node.branch ?? null,
      registered,
    }
  }

  add(command: AddRepo, view: TaskView | null): CommandOutcome {
    const refuse = (error: string): CommandOutcome => ({
      status: 422,
      reply: { ok: false, error, view: null },
    })
    const name = command.name.trim()
    if (!NAME_RE.test(name)) {
      return refuse(
        `nome de projeto inválido: '${name}' (use letras, números, ponto, hífen ou _; até 64)`,
      )
    }
    if (this.repos.some((r) => r.name === name)) {
      return refuse(`já existe um repositório chamado '${name}'`)
    }
    if (command.test_cmd.trim() === '') return refuse('informe o comando de teste (test_cmd)')
    const probe = this.probe(command.path)
    if (!probe) return refuse(`a pasta não existe: ${command.path}`)
    if (probe.registered) return refuse(`a pasta ${probe.path} já está cadastrada como repositório`)
    if (probe.git === 'inside_repo') {
      return refuse(
        `a pasta ${probe.path} é uma subpasta de outro repositório git: escolha a pasta raiz do repositório`,
      )
    }
    const branch = (command.base_branch ?? 'main').trim()
    if (probe.git === 'none' || probe.git === 'empty') {
      if (command.init_git !== true) {
        const what =
          probe.git === 'none'
            ? 'a pasta não é um repositório git'
            : 'o repositório não tem nenhum commit'
        return refuse(`${what}: use 'inicializar o git' para criar um commit inicial vazio`)
      }
      this.initialized.set(probe.path, branch)
    } else if (probe.branch !== branch) {
      return refuse(`a branch base '${branch}' não existe em ${probe.path}`)
    }
    this.added.push({ repo: { name, base_branch: branch }, path: probe.path })
    return { status: 200, reply: { ok: true, error: null, view } }
  }
}

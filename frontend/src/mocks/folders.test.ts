import { describe, expect, it } from 'vitest'
import type { AddRepo } from '../contracts/generated'
import { FAKE_PROJECTS_DIR } from './data'
import { MockFolders } from './folders'
import { ScenarioBackend } from './scenario'

const DOCS = FAKE_PROJECTS_DIR

function addRepo(path: string, over: Partial<AddRepo> = {}): AddRepo {
  return {
    type: 'add_repo',
    name: 'novo',
    path,
    base_branch: 'main',
    test_cmd: 'npm test',
    lint_cmd: null,
    setup_cmd: null,
    sandbox_image: null,
    deps_dirs: [],
    init_git: false,
    ...over,
  }
}

describe('MockFolders', () => {
  it('lista a pasta de projetos por padrão, marcando git e repos cadastrados', () => {
    const listing = new MockFolders().list(undefined)
    expect(listing?.path).toBe(DOCS)
    expect(listing?.parent).toBe('C:\\Users\\voce')
    const byName = Object.fromEntries((listing?.entries ?? []).map((e) => [e.name, e]))
    expect(byName['portal-vendas']).toMatchObject({ git_repo: true, registered: true })
    expect(byName.notas).toMatchObject({ git_repo: false, registered: false })
  })

  it("'' lista as unidades e a raiz da unidade sobe para elas", () => {
    const folders = new MockFolders()
    expect(folders.list('')?.entries.map((e) => e.name)).toEqual(['C:', 'D:'])
    expect(folders.list('C:\\')?.parent).toBe('')
  })

  it('caminho desconhecido devolve null', () => {
    const folders = new MockFolders()
    expect(folders.list('C:\\nada')).toBeNull()
    expect(folders.probe('C:\\nada')).toBeNull()
  })

  it('sonda os estados de git', () => {
    const folders = new MockFolders()
    expect(folders.probe(`${DOCS}\\notas`)).toMatchObject({ git: 'none', name: 'notas' })
    expect(folders.probe(`${DOCS}\\rascunho`)).toMatchObject({ git: 'empty' })
    expect(folders.probe(`${DOCS}\\blog-pessoal`)).toMatchObject({
      git: 'ready',
      branch: 'develop',
    })
    expect(folders.probe(`${DOCS}\\blog-pessoal\\src`)).toMatchObject({ git: 'inside_repo' })
    expect(folders.probe(`${DOCS}\\portal-vendas`)).toMatchObject({ registered: true })
  })

  it('add registra o repo e o some da lista de pastas livres', () => {
    const folders = new MockFolders()
    const outcome = folders.add(addRepo(`${DOCS}\\blog-pessoal`, { base_branch: 'develop' }), null)
    expect(outcome.status).toBe(200)
    expect(folders.repos.map((r) => r.name)).toContain('novo')
    expect(folders.probe(`${DOCS}\\blog-pessoal`)?.registered).toBe(true)
  })

  it('add recusa nome inválido, repetido, pasta cadastrada e subpasta de repo', () => {
    const folders = new MockFolders()
    const refused = (cmd: AddRepo) => folders.add(cmd, null)
    expect(refused(addRepo(`${DOCS}\\notas`, { name: 'a b' })).status).toBe(422)
    expect(refused(addRepo(`${DOCS}\\notas`, { name: 'api-pedidos' })).status).toBe(422)
    expect(refused(addRepo(`${DOCS}\\portal-vendas`)).reply.error).toMatch(/já está cadastrada/)
    expect(refused(addRepo(`${DOCS}\\blog-pessoal\\src`, { init_git: true })).reply.error).toMatch(
      /subpasta/,
    )
    expect(folders.repos).toHaveLength(2)
  })

  it('pasta sem git só entra com init_git', () => {
    const folders = new MockFolders()
    const first = folders.add(addRepo(`${DOCS}\\notas`), null)
    expect(first.status).toBe(422)
    expect(first.reply.error).toMatch(/inicializar o git/)

    expect(folders.add(addRepo(`${DOCS}\\notas`, { init_git: true }), null).status).toBe(200)
    expect(folders.probe(`${DOCS}\\notas`)).toMatchObject({ git: 'ready', branch: 'main' })
  })

  it('exige a branch base existente num repo com commits', () => {
    const outcome = new MockFolders().add(
      addRepo(`${DOCS}\\blog-pessoal`, { base_branch: 'main' }),
      null,
    )
    expect(outcome.status).toBe(422)
    expect(outcome.reply.error).toMatch(/branch base/)
  })
})

describe('ScenarioBackend add_repo', () => {
  it('o repo adicionado aparece em repos e pode ser usado por uma tarefa', () => {
    const backend = new ScenarioBackend()
    expect(
      backend.handle(addRepo(`${DOCS}\\blog-pessoal`, { base_branch: 'develop' })).status,
    ).toBe(200)
    expect(backend.repos.map((r) => r.name)).toContain('novo')
    expect(backend.getView()).toBeNull()
    expect(
      backend.handle({ type: 'start_task', repo: 'novo', title: 'Primeira tarefa' }).status,
    ).toBe(200)
    backend.dispose()
  })
})

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createQueryClient } from '../api/queryClient'
import { reposQuery } from '../api/queries'
import { createRestHandlers } from '../mocks/handlers'
import { ScenarioBackend } from '../mocks/scenario'
import { captureCommands } from '../test/commands'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { AddRepoForm } from './AddRepoForm'

let backend: ScenarioBackend

beforeEach(() => {
  backend = new ScenarioBackend()
  server.use(...createRestHandlers(backend))
})

async function pick(user: ReturnType<typeof userEvent.setup>, folder: string) {
  await user.click(await screen.findByRole('button', { name: `Selecionar ${folder}` }))
}

describe('AddRepoForm', () => {
  it('lista as pastas, marca as que já são repos e não deixa selecioná-las', async () => {
    renderWithClient(<AddRepoForm onAdded={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'Selecionar notas' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Selecionar portal-vendas' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Selecionar api-pedidos' })).toBeDisabled()
    expect(screen.getAllByText('já adicionado')).toHaveLength(2)
  })

  it('navega: entra numa pasta, sobe e vai até as unidades', async () => {
    const user = userEvent.setup()
    renderWithClient(<AddRepoForm onAdded={vi.fn()} />)
    expect(await screen.findByTitle('C:\\Users\\voce\\Documents')).toBeInTheDocument()

    await user.click(await screen.findByRole('button', { name: 'blog-pessoal' }))
    expect(await screen.findByTitle('C:\\Users\\voce\\Documents\\blog-pessoal')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Selecionar src' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Subir' }))
    expect(await screen.findByTitle('C:\\Users\\voce\\Documents')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Selecionar notas' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Unidades' }))
    expect(await screen.findByRole('button', { name: 'C:' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'D:' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Subir' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'D:' }))
    expect(await screen.findByRole('button', { name: 'Selecionar Backup' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Subir' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Subir' }))
    expect(await screen.findByRole('button', { name: 'C:' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'D:' }))
    expect(await screen.findByRole('button', { name: 'Selecionar Backup' })).toBeEnabled()
  })

  it('mostra o selo git nos repositórios e não nas pastas comuns', async () => {
    renderWithClient(<AddRepoForm onAdded={vi.fn()} />)
    const blog = (await screen.findByRole('button', { name: 'blog-pessoal' })).closest('li')
    const notas = screen.getByRole('button', { name: 'notas' }).closest('li')
    expect(blog).toHaveTextContent('git')
    expect(notas).not.toHaveTextContent('git')
  })

  it('subpasta de outro repositório: avisa e bloqueia o envio', async () => {
    const user = userEvent.setup()
    renderWithClient(<AddRepoForm onAdded={vi.fn()} />)
    await user.click(await screen.findByRole('button', { name: 'blog-pessoal' }))
    await pick(user, 'src')

    expect(await screen.findByRole('alert')).toHaveTextContent(/dentro de outro repositório git/)
    await user.type(screen.getByLabelText(/comando de teste/), 'npm test')
    expect(screen.getByRole('button', { name: 'Adicionar repositório' })).toBeDisabled()
  })

  it('invalida a lista de repositórios e a de pastas depois de adicionar', async () => {
    const client = createQueryClient({ retry: false })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={client}>
        <AddRepoForm onAdded={vi.fn()} />
      </QueryClientProvider>,
    )
    await pick(user, 'blog-pessoal')
    await waitFor(() => {
      expect(screen.getByLabelText('nome do repositório')).toHaveValue('blog-pessoal')
    })
    await user.type(screen.getByLabelText(/comando de teste/), 'npm test')
    await user.click(screen.getByRole('button', { name: 'Adicionar repositório' }))

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: reposQuery.queryKey })
    })
    expect(backend.repos.map((r) => r.name)).toContain('blog-pessoal')
  })

  it('apagar o comando de teste volta a desabilitar o botão', async () => {
    const user = userEvent.setup()
    renderWithClient(<AddRepoForm onAdded={vi.fn()} />)
    await pick(user, 'blog-pessoal')
    await waitFor(() => {
      expect(screen.getByLabelText('nome do repositório')).toHaveValue('blog-pessoal')
    })
    const test = screen.getByLabelText(/comando de teste/)
    await user.type(test, 'npm test')
    expect(screen.getByRole('button', { name: 'Adicionar repositório' })).toBeEnabled()
    await user.clear(test)
    expect(screen.getByRole('button', { name: 'Adicionar repositório' })).toBeDisabled()
  })

  it('sugere nome e branch pela pasta e envia o add_repo com test_cmd', async () => {
    const commands = captureCommands()
    const onAdded = vi.fn()
    const user = userEvent.setup()
    renderWithClient(<AddRepoForm onAdded={onAdded} />)
    await pick(user, 'blog-pessoal')

    await waitFor(() => {
      expect(screen.getByLabelText('nome do repositório')).toHaveValue('blog-pessoal')
    })
    expect(screen.getByLabelText('branch base')).toHaveValue('develop')

    const add = screen.getByRole('button', { name: 'Adicionar repositório' })
    expect(add).toBeDisabled()
    await user.type(screen.getByLabelText(/comando de teste/), 'npm test')
    expect(add).toBeEnabled()
    await user.type(screen.getByLabelText(/pastas de dependências/), 'node_modules, .venv')
    await user.click(add)

    await waitFor(() => {
      expect(commands.received).toEqual([
        {
          type: 'add_repo',
          name: 'blog-pessoal',
          path: 'C:\\Users\\voce\\Documents\\blog-pessoal',
          base_branch: 'develop',
          test_cmd: 'npm test',
          lint_cmd: null,
          setup_cmd: null,
          sandbox_image: null,
          deps_dirs: ['node_modules', '.venv'],
          init_git: false,
        },
      ])
    })
    await waitFor(() => {
      expect(onAdded).toHaveBeenCalled()
    })
  })

  it('desabilita o botão com nome inválido', async () => {
    const user = userEvent.setup()
    renderWithClient(<AddRepoForm onAdded={vi.fn()} />)
    await pick(user, 'blog-pessoal')
    await waitFor(() => {
      expect(screen.getByLabelText('nome do repositório')).toHaveValue('blog-pessoal')
    })
    await user.type(screen.getByLabelText(/comando de teste/), 'npm test')
    await user.clear(screen.getByLabelText('nome do repositório'))
    await user.type(screen.getByLabelText('nome do repositório'), 'blog pessoal')

    expect(screen.getByText(/sem espaços/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Adicionar repositório' })).toBeDisabled()
  })

  it('pasta sem git: mostra o erro e oferece "Inicializar o git", que reenvia com init_git', async () => {
    const user = userEvent.setup()
    const onAdded = vi.fn()
    renderWithClient(<AddRepoForm onAdded={onAdded} />)
    await pick(user, 'notas')
    await waitFor(() => {
      expect(screen.getByLabelText('nome do repositório')).toHaveValue('notas')
    })
    expect(screen.queryByRole('button', { name: 'Inicializar o git' })).not.toBeInTheDocument()

    await user.type(screen.getByLabelText(/comando de teste/), 'pytest')
    await user.click(screen.getByRole('button', { name: 'Adicionar repositório' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/não é um repositório git/)

    await user.click(screen.getByRole('button', { name: 'Inicializar o git' }))
    await waitFor(() => {
      expect(onAdded).toHaveBeenCalled()
    })
    expect(backend.repos.map((r) => r.name)).toContain('notas')
  })
})

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { REPOS } from '../mocks/data'
import { captureCommands } from '../test/commands'
import { renderWithClient } from '../test/render'
import { Composer } from './Composer'

const [first, second] = REPOS

describe('Composer (nova tarefa)', () => {
  it('título obrigatório; Começar envia start_task com o repo escolhido', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    renderWithClient(<Composer />)

    const start = screen.getByRole('button', { name: 'Começar' })
    expect(start).toBeDisabled()
    await user.type(screen.getByLabelText('título'), 'Exportar pedidos em CSV')
    await user.type(screen.getByLabelText('detalhes'), 'Mandar pro financeiro')
    await user.click(await screen.findByRole('combobox', { name: 'repositório' }))
    await user.click(await screen.findByRole('option', { name: second?.name }))
    await user.click(start)

    await waitFor(() => {
      expect(commands.received).toEqual([
        {
          type: 'start_task',
          repo: second?.name,
          title: 'Exportar pedidos em CSV',
          description: 'Mandar pro financeiro',
        },
      ])
    })
  })

  it('Ctrl+Enter começa a tarefa', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    renderWithClient(<Composer />)
    await screen.findByRole('combobox', { name: 'repositório' })
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: 'repositório' })).toHaveTextContent(
        first?.name ?? '',
      )
    })
    await user.type(screen.getByLabelText('título'), 'Algo{Control>}{Enter}{/Control}')
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'start_task', repo: first?.name, title: 'Algo', description: '' },
      ])
    })
  })

  it('erro do gateway aparece inline e não trava o formulário', async () => {
    captureCommands({
      status: 409,
      body: { ok: false, error: 'Já existe uma tarefa ativa.', view: null },
    })
    const user = userEvent.setup()
    renderWithClient(<Composer />)
    await screen.findByRole('combobox', { name: 'repositório' })
    await user.type(screen.getByLabelText('título'), 'Algo')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Começar' })).toBeEnabled()
    })
    await user.click(screen.getByRole('button', { name: 'Começar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Já existe uma tarefa ativa.')
    expect(screen.getByRole('button', { name: 'Começar' })).toBeEnabled()
    expect(screen.getByLabelText('título')).toHaveValue('Algo')
  })

  it('"Novo projeto" no menu abre o formulário e cria o projeto', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    renderWithClient(<Composer />)
    await user.click(await screen.findByRole('combobox', { name: 'repositório' }))
    await user.click(await screen.findByRole('option', { name: '+ Novo projeto' }))

    const dialog = screen.getByRole('dialog', { name: 'Novo projeto' })
    await user.type(within(dialog).getByLabelText(/nome do projeto/), 'agenda consultas')
    expect(within(dialog).getByText(/sem espaços/)).toBeInTheDocument()
    await user.clear(within(dialog).getByLabelText(/nome do projeto/))
    await user.type(within(dialog).getByLabelText(/nome do projeto/), 'agenda-consultas')
    await user.type(within(dialog).getByLabelText(/o que construir/), 'Agenda de consultas')
    await user.click(within(dialog).getByRole('button', { name: 'Criar e iniciar' }))

    await waitFor(() => {
      expect(commands.received).toEqual([
        {
          type: 'create_project',
          name: 'agenda-consultas',
          parent_dir: '',
          title: 'Agenda de consultas',
          description: '',
        },
      ])
    })
    // o repo escolhido não muda pro item de ação
    expect(screen.getByRole('combobox', { name: 'repositório' })).toHaveTextContent(
      first?.name ?? '',
    )
  })

  it('"Adicionar pasta existente" abre o navegador de pastas; Esc fecha', async () => {
    const user = userEvent.setup()
    renderWithClient(<Composer />)
    await user.click(await screen.findByRole('combobox', { name: 'repositório' }))
    await user.click(await screen.findByRole('option', { name: '⌂ Adicionar pasta existente' }))

    const dialog = screen.getByRole('dialog', { name: 'Adicionar pasta existente' })
    expect(await within(dialog).findByRole('list', { name: 'Pastas' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { captureCommands } from '../test/commands'
import { renderWithClient } from '../test/render'
import { SourcePicker } from './SourcePicker'

describe('origem Novo projeto (D58)', () => {
  it('cria o projeto com nome, pasta e o que construir', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    renderWithClient(<SourcePicker />)
    await user.click(screen.getByRole('button', { name: /Novo projeto/ }))
    expect(screen.getByRole('region', { name: 'Origem: novo projeto' })).toBeInTheDocument()

    const create = screen.getByRole('button', { name: 'Criar e iniciar' })
    expect(create).toBeDisabled()
    await user.type(screen.getByLabelText(/nome do projeto/), 'agenda consultas')
    expect(screen.getByText(/sem espaços/)).toBeInTheDocument()
    await user.clear(screen.getByLabelText(/nome do projeto/))
    await user.type(screen.getByLabelText(/nome do projeto/), 'agenda-consultas')
    await user.type(screen.getByLabelText(/o que construir/), 'Agenda de consultas')
    await user.type(screen.getByLabelText(/^descrição/), 'React + FastAPI')
    await user.click(create)

    await waitFor(() => {
      expect(commands.received).toEqual([
        {
          type: 'create_project',
          name: 'agenda-consultas',
          parent_dir: '',
          title: 'Agenda de consultas',
          description: 'React + FastAPI',
        },
      ])
    })
  })
})

describe('origem Adicionar repositório', () => {
  it('sem tarefa ativa abre o dialog com o navegador de pastas e fecha pelo Esc', async () => {
    const user = userEvent.setup()
    renderWithClient(<SourcePicker />)

    await user.click(screen.getByRole('button', { name: /Adicionar repositório/ }))
    const dialog = screen.getByRole('dialog', { name: 'Adicionar repositório' })
    expect(await within(dialog).findByRole('list', { name: 'Pastas' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })

  it('fecha o dialog pelo botão de fechar', async () => {
    const user = userEvent.setup()
    renderWithClient(<SourcePicker />)

    await user.click(screen.getByRole('button', { name: /Adicionar repositório/ }))
    const dialog = screen.getByRole('dialog', { name: 'Adicionar repositório' })
    await user.click(within(dialog).getByRole('button', { name: 'Close' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
  })
})

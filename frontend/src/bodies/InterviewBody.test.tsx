import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { InterviewBody } from './InterviewBody'

const view = fixture('interviewing')

function setup(overrides = view) {
  return renderWithClient(<InterviewBody view={overrides} stage={overrides.stages.interviewer} />)
}

describe('InterviewBody', () => {
  it('mostra histórico (resposta aceita vs. própria), pergunta pendente com recomendação e spec', () => {
    setup()
    expect(screen.getByText('✓ Aceito a recomendação.')).toBeInTheDocument()
    expect(screen.getAllByText('Recomendo:').length).toBeGreaterThanOrEqual(2)
    expect(view.interview?.pending).not.toBeNull()
    expect(screen.getByText(view.interview?.pending?.question ?? '')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Spec' })).toBeInTheDocument()
  })

  it('"Aceitar recomendação" envia answer_interview com text null', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Aceitar recomendação' }))
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'answer_interview', text: null }])
    })
  })

  it('responder diferente: "Enviar" só habilita com texto e envia o texto; limpa o campo', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    setup()
    const send = screen.getByRole('button', { name: 'Enviar' })
    const input = screen.getByRole('textbox', { name: 'Responder diferente' })
    expect(send).toBeDisabled()

    await user.type(input, 'Só CSV, sem XLSX')
    expect(send).toBeEnabled()
    await user.click(send)

    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'answer_interview', text: 'Só CSV, sem XLSX' }])
    })
    await waitFor(() => {
      expect(input).toHaveValue('')
    })
  })

  it('não apaga o que o usuário digitou enquanto o envio anterior ainda estava em andamento', async () => {
    const commands = captureCommands()
    commands.hold()
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Aceitar recomendação' }))
    const input = screen.getByRole('textbox', { name: 'Responder diferente' })
    await user.type(input, 'próxima resposta')

    commands.release()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Aceitar recomendação' })).toBeEnabled()
    })
    expect(input).toHaveValue('próxima resposta')
  })

  it('Enter no campo envia', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    setup()
    await user.type(screen.getByRole('textbox', { name: 'Responder diferente' }), 'resposta{Enter}')
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'answer_interview', text: 'resposta' }])
    })
  })

  it('desabilita os botões durante o envio', async () => {
    const commands = captureCommands()
    commands.hold()
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Aceitar recomendação' }))
    expect(screen.getByRole('button', { name: 'Aceitar recomendação' })).toBeDisabled()
    commands.release()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Aceitar recomendação' })).toBeEnabled()
    })
  })

  it('mostra o erro do servidor inline e preserva o que foi digitado', async () => {
    captureCommands({
      status: 409,
      body: { ok: false, error: 'Nenhuma pergunta aguardando resposta.', view: null },
    })
    const user = userEvent.setup()
    setup()
    const input = screen.getByRole('textbox', { name: 'Responder diferente' })
    await user.type(input, 'minha resposta')
    await user.click(screen.getByRole('button', { name: 'Enviar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nenhuma pergunta aguardando resposta.',
    )
    expect(input).toHaveValue('minha resposta')
  })

  it('o que foi digitado sobrevive a um novo snapshot', async () => {
    const user = userEvent.setup()
    const { rerender } = setup()
    const input = screen.getByRole('textbox', { name: 'Responder diferente' })
    await user.type(input, 'rascunho')
    rerender(<InterviewBody view={{ ...view, cost_usd: 1 }} stage={view.stages.interviewer} />)
    expect(screen.getByRole('textbox', { name: 'Responder diferente' })).toHaveValue('rascunho')
  })

  it('sem pergunta aguardando resposta não mostra o campo', () => {
    setup({
      ...view,
      stages: { ...view.stages, interviewer: { ...view.stages.interviewer, status: 'active' } },
    })
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('tarefa do Azure: explica que o estágio foi pulado', () => {
    const azure = fixture('planning')
    renderWithClient(<InterviewBody view={azure} stage={azure.stages.interviewer} />)
    expect(screen.getByText('Pulado — tarefa veio do Azure DevOps.')).toBeInTheDocument()
  })

  it('sem tarefa: explica quando o estágio entra', () => {
    renderWithClient(<InterviewBody view={null} stage={{ status: 'idle', now: null, logs: [] }} />)
    expect(screen.getByText(/Entra só em tarefa manual/)).toBeInTheDocument()
  })
})
